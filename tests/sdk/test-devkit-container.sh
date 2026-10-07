#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

sed -n '/^devkit-container-usage()/,/^# Run a local \/workspace binary/p' \
  "${ROOT_DIR}/scripts/devkit.sh" > "${TMP_DIR}/devkit-container-functions.sh"
# shellcheck source=/dev/null
source "${TMP_DIR}/devkit-container-functions.sh"

mkdir -p "${TMP_DIR}/bin"
cat > "${TMP_DIR}/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
{
  echo BEGIN
  printf 'ARG=%s\n' "$@"
} >> "${DOCKER_LOG:?}"
if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
  printf '%s\n' "${FAKE_DOCKER_ARCH:-arm64}"
fi
if [[ "${1:-}" == "run" && "${FAKE_DOCKER_READ_STDIN:-0}" == "1" ]]; then
  IFS= read -r line
  printf 'STDIN=%s\n' "${line}" >> "${DOCKER_LOG:?}"
fi
EOF
chmod +x "${TMP_DIR}/bin/docker"

cat > "${TMP_DIR}/bin/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == -n ]]; then
  shift
fi
printf 'SUDO_ARG=%s\n' "$@" >> "${DOCKER_LOG:?}"
case "${1:-}" in
  true|usermod|systemctl) exit 0 ;;
  python3)
    cat >/dev/null
    printf 'unchanged\n'
    ;;
  docker)
    shift
    exec docker "$@"
    ;;
  *)
    echo "unexpected sudo command in test: $*" >&2
    exit 1
    ;;
esac
EOF
chmod +x "${TMP_DIR}/bin/sudo"

ssh() {
  local found_host=0
  local arg
  local remote_command=""
  for arg in "$@"; do
    if [[ "${found_host}" == "1" ]]; then
      if [[ -n "${remote_command}" ]]; then
        remote_command+=" "
      fi
      remote_command+="${arg}"
    elif [[ "${arg}" == *@* ]]; then
      found_host=1
    fi
  done
  [[ "${found_host}" == "1" ]] || fail "mock ssh did not receive a remote host"
  [[ -n "${remote_command}" ]] || fail "mock ssh did not receive a remote command"
  if [[ "${FAKE_SSH_DOCKER_MISSING_COUNT:-0}" -gt 0 ]]; then
    FAKE_SSH_DOCKER_MISSING_COUNT=$((FAKE_SSH_DOCKER_MISSING_COUNT - 1))
    echo "Docker is not installed on the DevKit." >&2
    return 42
  fi
  # OpenSSH sends a space-joined command string to the login shell. Reparse it
  # here so the test catches quoting bugs hidden by direct argv forwarding.
  bash --noprofile --norc -c "${remote_command}"
}

export DEVKIT_SYNC_DEVKIT_IP=192.0.2.20
export DEVKIT_SYNC_DEVKIT_USER=sima
export DEVKIT_SYNC_DEVKIT_PORT=22
export SIMA_CONTAINER_REGISTRY=localhost:5050
export SIMA_DEVKIT_CONTAINER_REGISTRY=192.0.2.10:5050
export DOCKER_LOG="${TMP_DIR}/docker.log"
export INJECTION_MARKER="${TMP_DIR}/injected"
export PATH="${TMP_DIR}/bin:${PATH}"

: > "${DOCKER_LOG}"
devkit-container setup --yes
grep -Fqx 'SUDO_ARG=usermod' "${DOCKER_LOG}" || fail "setup did not configure the docker group"
grep -Fqx 'SUDO_ARG=systemctl' "${DOCKER_LOG}" || fail "setup did not enable Docker services"
grep -Fqx 'SUDO_ARG=192.0.2.10:5050' "${DOCKER_LOG}" || \
  fail "setup did not configure the scoped SDK registry"

FAKE_SSH_DOCKER_MISSING_COUNT=1
export FAKE_SSH_DOCKER_MISSING_COUNT
if devkit-container list >"${TMP_DIR}/missing.out" 2>&1; then
  fail "noninteractive Docker installation should require explicit approval"
fi
grep -Fq 'dk container setup --yes' "${TMP_DIR}/missing.out" || \
  fail "missing Docker error did not explain explicit setup"

devkit-container-install-docker() {
  printf 'INSTALL_REQUESTED\n' >> "${DOCKER_LOG}"
}
: > "${DOCKER_LOG}"
FAKE_SSH_DOCKER_MISSING_COUNT=1
export FAKE_SSH_DOCKER_MISSING_COUNT
devkit-container list
grep -Fqx 'INSTALL_REQUESTED' "${DOCKER_LOG}" || fail "missing Docker did not offer installation"
grep -Fqx 'ARG=ps' "${DOCKER_LOG}" || fail "container command was not retried after installation"

grep -Fq '"data-root"] = "/data/docker"' "${ROOT_DIR}/scripts/devkit.sh" || \
  fail "installer does not configure the Modalix Docker data root"
grep -Fq '/data/containerd /var/lib/containerd none bind 0 0' "${ROOT_DIR}/scripts/devkit.sh" || \
  fail "installer does not persist containerd storage under /data"
grep -Fq 'docker-ce docker-ce-cli containerd.io' "${ROOT_DIR}/scripts/devkit.sh" || \
  fail "installer does not install the supported Docker CE packages"
grep -Fq 'data["insecure-registries"]' "${ROOT_DIR}/scripts/devkit.sh" || \
  fail "installer does not configure the scoped SDK registry"

resolved="$(devkit-container-image-ref hello-neat:develop)"
[[ "${resolved}" == "192.0.2.10:5050/hello-neat:develop" ]] || \
  fail "short image name did not use the DevKit registry: ${resolved}"

resolved="$(devkit-container-image-ref localhost:5050/team/hello-neat:develop)"
[[ "${resolved}" == "192.0.2.10:5050/team/hello-neat:develop" ]] || \
  fail "SDK registry address was not replaced: ${resolved}"

: > "${DOCKER_LOG}"
# These literal payloads must reach Docker unchanged, never expand locally or remotely.
# shellcheck disable=SC2016
devkit-container deploy localhost:5050/team/hello-neat:develop \
  --name hello-neat --network host -- /app --label "two words" \
  '; touch "$INJECTION_MARKER"; #' '$(touch "$INJECTION_MARKER")' ""
[[ "$(grep -c '^BEGIN$' "${DOCKER_LOG}")" == "4" ]] || \
  fail "deploy should check Docker, pull, inspect, and run"
grep -Fqx 'ARG=pull' "${DOCKER_LOG}" || fail "deploy did not pull"
grep -Fqx 'ARG=inspect' "${DOCKER_LOG}" || fail "deploy did not inspect image architecture"
grep -Fqx 'ARG=192.0.2.10:5050/team/hello-neat:develop' "${DOCKER_LOG}" || \
  fail "deploy used the wrong remote image"
grep -Fqx 'ARG=--name' "${DOCKER_LOG}" || fail "Docker run option was not forwarded"
grep -Fqx 'ARG=/app' "${DOCKER_LOG}" || fail "container command was not forwarded"
grep -Fqx 'ARG=two words' "${DOCKER_LOG}" || fail "quoted container argument was not preserved"
# shellcheck disable=SC2016
grep -Fqx 'ARG=; touch "$INJECTION_MARKER"; #' "${DOCKER_LOG}" || \
  fail "semicolon container argument was not preserved"
# shellcheck disable=SC2016
grep -Fqx 'ARG=$(touch "$INJECTION_MARKER")' "${DOCKER_LOG}" || \
  fail "command-substitution container argument was not preserved"
grep -Fqx 'ARG=' "${DOCKER_LOG}" || fail "empty container argument was not preserved"
[[ ! -e "${INJECTION_MARKER}" ]] || fail "container argument was executed by the remote shell"

: > "${DOCKER_LOG}"
export FAKE_DOCKER_READ_STDIN=1
printf 'keyboard input\n' | devkit-container run hello-neat:develop -i -- /bin/sh
unset FAKE_DOCKER_READ_STDIN
grep -Fqx 'STDIN=keyboard input' "${DOCKER_LOG}" || \
  fail "interactive container did not receive caller stdin"

: > "${DOCKER_LOG}"
devkit-container run hello-neat:develop --rm
[[ "$(grep -c '^BEGIN$' "${DOCKER_LOG}")" == "3" ]] || \
  fail "run should check Docker, inspect, and start without an explicit pull"
if grep -Fqx 'ARG=pull' "${DOCKER_LOG}"; then
  fail "run unexpectedly pulled the image"
fi
grep -Fqx 'ARG=--rm' "${DOCKER_LOG}" || fail "run option was not forwarded"

: > "${DOCKER_LOG}"
export FAKE_DOCKER_ARCH=amd64
if devkit-container deploy hello-neat:develop --rm >/dev/null 2>&1; then
  fail "deploy should reject a non-ARM64 image"
fi
unset FAKE_DOCKER_ARCH
if grep -Fqx 'ARG=run' "${DOCKER_LOG}"; then
  fail "deploy ran a non-ARM64 image"
fi

: > "${DOCKER_LOG}"
devkit-container logs hello-neat --follow
grep -Fqx 'ARG=logs' "${DOCKER_LOG}" || fail "logs action was not used"
grep -Fqx 'ARG=--follow' "${DOCKER_LOG}" || fail "logs option was not forwarded"
[[ "$(tail -n 1 "${DOCKER_LOG}")" == "ARG=hello-neat" ]] || \
  fail "container name must follow docker logs options"

sed -n '/^dk()/,/^}/p' "${ROOT_DIR}/scripts/devkit.sh" > "${TMP_DIR}/dk-function.sh"
# shellcheck source=/dev/null
source "${TMP_DIR}/dk-function.sh"
: > "${DOCKER_LOG}"
dk container pull hello-neat:develop
grep -Fqx 'ARG=pull' "${DOCKER_LOG}" || fail "dk did not dispatch the container command"

unset SIMA_DEVKIT_CONTAINER_REGISTRY
if devkit-container-image-ref hello-neat:develop >/dev/null 2>&1; then
  fail "missing registry configuration should fail"
fi

bash -n "${ROOT_DIR}/scripts/devkit.sh"
echo "DevKit container command tests passed"
