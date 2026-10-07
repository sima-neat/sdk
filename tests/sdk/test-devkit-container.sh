#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
export DEVKIT_CONTAINER_REMOTE_SCRIPT="${ROOT_DIR}/scripts/devkit-container-remote.sh"

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
if [[ "${1:-}" == "run" && "${FAKE_DOCKER_RUN_STATUS:-0}" != "0" ]]; then
  exit "${FAKE_DOCKER_RUN_STATUS}"
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
  local detach_stdin=0
  local found_host=0
  local arg
  local remote_command=""
  for arg in "$@"; do
    if [[ "${arg}" == -n ]]; then
      detach_stdin=1
    elif [[ "${found_host}" == "1" ]]; then
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
  if [[ "${FAKE_REQUIRE_DETACHED_SSH:-0}" == 1 ]]; then
    FAKE_SSH_SEQUENCE=$((${FAKE_SSH_SEQUENCE:-0} + 1))
    if [[ "${FAKE_SSH_SEQUENCE}" == 1 && "${detach_stdin}" != 1 ]]; then
      fail "non-workload SSH preflight did not detach caller stdin"
    fi
  fi
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

: > "${DOCKER_LOG}"
export FAKE_DOCKER_RUN_STATUS=42
status=0
devkit-container run hello-neat:develop --rm || status=$?
unset FAKE_DOCKER_RUN_STATUS
[[ "${status}" == 42 ]] || fail "container exit status 42 was not preserved"
if grep -Fqx 'INSTALL_REQUESTED' "${DOCKER_LOG}"; then
  fail "container exit status 42 was mistaken for missing Docker"
fi

grep -Fq '"data-root"] = "/data/docker"' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not configure the Modalix Docker data root"
grep -Fq '/data/containerd /var/lib/containerd none bind 0 0' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not persist containerd storage under /data"
grep -Fq 'docker-ce docker-ce-cli containerd.io' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not install the supported Docker CE packages"
grep -Fq 'data["insecure-registries"]' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not configure the scoped SDK registry"
grep -Fq '.sima-sdk-install-in-progress' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not preserve retry state after an interrupted installation"
grep -Fq 'containerd_entries' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "containerd migration is not resumable"
grep -Fq 'Resuming an interrupted Docker installation.' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not report or resume interrupted work"
grep -Fq 'Resuming with the eLxr package mirror temporarily disabled.' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not restore the eLxr mirror after interruption"
grep -Fq 'Docker services remain stopped until containerd storage setup is completed.' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer can restart Docker before containerd storage migration is complete"
grep -Fq '.sima-sdk-containerd-migrated' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "installer does not record completed containerd copies before deleting their source"
grep -Fq 'sima-sdk-registry-applied' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "registry setup does not retry an interrupted Docker reload"
grep -Fq 'sima-sdk-registry-address' "${ROOT_DIR}/scripts/devkit-container-remote.sh" || \
  fail "SDK does not own the DevKit registry state"
grep -Fq 'COPY scripts/devkit-container-remote.sh /usr/local/libexec/sima-sdk/devkit-container-remote.sh' \
  "${ROOT_DIR}/Dockerfile" || fail "SDK image does not install the DevKit container helper"

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
[[ "$(grep -c '^BEGIN$' "${DOCKER_LOG}")" == "5" ]] || \
  fail "deploy should configure the registry, then check Docker, pull, inspect, and run"
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
export FAKE_REQUIRE_DETACHED_SSH=1
export FAKE_SSH_SEQUENCE=0
printf 'keyboard input\n' | devkit-container run hello-neat:develop -i -- /bin/sh
unset FAKE_DOCKER_READ_STDIN
unset FAKE_REQUIRE_DETACHED_SSH
unset FAKE_SSH_SEQUENCE
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

{
  declare -f devkit-container-usage
  declare -f devkit-container-image-ref
  declare -f devkit-container-remote
  declare -f devkit-container-install-docker
  declare -f devkit-container-remote-with-setup
  declare -f devkit-container-ensure-registry
  declare -f devkit-container
} > "${TMP_DIR}/persisted-container-functions.sh"
bash --noprofile --norc -c '
  source "$1"
  for name in devkit-container-install-docker devkit-container-remote-with-setup devkit-container-ensure-registry; do
    declare -F "$name" >/dev/null || exit 1
  done
' -- "${TMP_DIR}/persisted-container-functions.sh" || \
  fail "persisted SDK shell is missing a container helper dependency"
for name in devkit-container-install-docker devkit-container-remote-with-setup devkit-container-ensure-registry; do
  grep -Fq "declare -f ${name}" "${ROOT_DIR}/scripts/devkit.sh" || \
    fail "devkit.sh does not persist ${name} for new SDK shells"
done

: > "${DOCKER_LOG}"
dk container pull hello-neat:develop
grep -Fqx 'ARG=pull' "${DOCKER_LOG}" || fail "dk did not dispatch the container command"

unset SIMA_DEVKIT_CONTAINER_REGISTRY
if devkit-container-image-ref hello-neat:develop >/dev/null 2>&1; then
  fail "missing registry configuration should fail"
fi

bash -n "${ROOT_DIR}/scripts/devkit.sh" "${ROOT_DIR}/scripts/devkit-container-remote.sh"
echo "DevKit container command tests passed"
