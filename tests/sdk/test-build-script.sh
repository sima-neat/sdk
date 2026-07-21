#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${TMP_DIR}/bin"
cat > "${TMP_DIR}/bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "buildx" && "${2:-}" == "version" ]]; then
  exit 0
fi

printf '%s\n' "$@" > "${DOCKER_ARGS_LOG:?}"
SH
chmod +x "${TMP_DIR}/bin/docker"

cat > "${TMP_DIR}/bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

printf '%s' 'abcdef123456'
SH
chmod +x "${TMP_DIR}/bin/curl"

run_build() {
  DOCKER_ARGS_LOG="${TMP_DIR}/docker-args" \
    PATH="${TMP_DIR}/bin:${PATH}" \
    DOCKER_PLATFORM=linux/amd64 \
    NEAT_CORE_SOURCE_REF=1111111111111111111111111111111111111111 \
    NEAT_APPS_SOURCE_REF=2222222222222222222222222222222222222222 \
    CONTEXT_DIR="${ROOT_DIR}" \
    DOCKERFILE="${ROOT_DIR}/Dockerfile" \
    "$@"
}

assert_arg() {
  local expected="$1"
  if ! grep -Fqx -- "${expected}" "${TMP_DIR}/docker-args"; then
    echo "Missing expected Docker argument: ${expected}" >&2
    cat "${TMP_DIR}/docker-args" >&2
    exit 1
  fi
}

BUILDX_OUTPUT=push \
BUILDX_CACHE_FROM="ghcr.io/sima-neat/sdk-buildcache:test-x86_64 ghcr.io/sima-neat/sdk-buildcache:develop-x86_64" \
BUILDX_CACHE_TO=ghcr.io/sima-neat/sdk-buildcache:test-x86_64 \
BUILDX_PROVENANCE=false \
  run_build "${ROOT_DIR}/build.sh" example/sdk test

assert_arg buildx
assert_arg build
assert_arg --push
assert_arg linux/amd64
assert_arg type=registry,ref=ghcr.io/sima-neat/sdk-buildcache:develop-x86_64
assert_arg type=registry,ref=ghcr.io/sima-neat/sdk-buildcache:test-x86_64
assert_arg type=registry,ref=ghcr.io/sima-neat/sdk-buildcache:test-x86_64,mode=max,oci-mediatypes=true,image-manifest=true
assert_arg --provenance=false
assert_arg NEAT_CORE_SOURCE_REF=1111111111111111111111111111111111111111
assert_arg NEAT_APPS_SOURCE_REF=2222222222222222222222222222222222222222
assert_arg SIMA_CLI_REF=v2.1.15
assert_arg SIMA_CLI_VERSION=latest
assert_arg example/sdk:test

SIMA_CLI_REF=main:latest BUILDX_OUTPUT=load \
  run_build "${ROOT_DIR}/build.sh" example/sdk branch-cli
assert_arg SIMA_CLI_REF=main
assert_arg SIMA_CLI_VERSION=abcdef123456
assert_arg example/sdk:branch-cli

BUILDX_OUTPUT=load run_build "${ROOT_DIR}/build.sh" example/sdk local
assert_arg --load
assert_arg example/sdk:local

if BUILDX_OUTPUT=invalid run_build "${ROOT_DIR}/build.sh" example/sdk invalid >/dev/null 2>&1; then
  echo "Expected an unsupported Buildx output mode to fail." >&2
  exit 1
fi

palette_marker_line="$(grep -nF "SDK Version = %s_Palette_SDK" "${ROOT_DIR}/Dockerfile" | head -n 1 | cut -d: -f1)"
sima_cli_install_line="$(grep -nF 'install-sima-cli.sh &&' "${ROOT_DIR}/Dockerfile" | tail -n 1 | cut -d: -f1)"
resource_install_line="$(grep -nF 'install-neat-resources.sh' "${ROOT_DIR}/Dockerfile" | tail -n 1 | cut -d: -f1)"
release_marker_line="$(grep -nF 'SDK Release = %s' "${ROOT_DIR}/Dockerfile" | head -n 1 | cut -d: -f1)"

if (( palette_marker_line >= sima_cli_install_line )); then
  echo "The stable Palette SDK marker must exist before sima-cli installs dependencies." >&2
  exit 1
fi
if (( release_marker_line <= resource_install_line )); then
  echo "The volatile SDK release marker must remain after dependency/resource layers." >&2
  exit 1
fi

echo "SDK build helper tests passed."
