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
    SDK_APT_CHANNEL="${SDK_APT_CHANNEL:-release}" \
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
assert_arg NEAT_CORE_SOURCE_REASON=
grep -Eq '^NEAT_CORE_RESOLUTION_ATTEMPT=(local-[0-9]{14}-[0-9]+|[0-9]+-[0-9]+)$' "${TMP_DIR}/docker-args"
assert_arg NEAT_APPS_SOURCE_REF=2222222222222222222222222222222222222222
assert_arg SIMA_CLI_REF=v2.1.20
assert_arg SIMA_CLI_VERSION=latest
assert_arg example/sdk:test

SIMA_CLI_REF=main:latest BUILDX_OUTPUT=load \
  run_build "${ROOT_DIR}/build.sh" example/sdk branch-cli
assert_arg SIMA_CLI_REF=main
assert_arg SIMA_CLI_VERSION=abcdef123456
assert_arg SDK_CROSS_TOOLCHAIN_IMAGE=debian:trixie
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
release_marker_line="$(grep -nF 'write-sdk-release.sh &&' "${ROOT_DIR}/Dockerfile" | tail -n 1 | cut -d: -f1)"

if (( palette_marker_line >= sima_cli_install_line )); then
  echo "The stable Palette SDK marker must exist before sima-cli installs dependencies." >&2
  exit 1
fi
if (( release_marker_line <= resource_install_line )); then
  echo "The volatile SDK release marker must remain after dependency/resource layers." >&2
  exit 1
fi

dockerfile="${ROOT_DIR}/Dockerfile"
workflow="${ROOT_DIR}/.github/workflows/docker-build.yml"
readme="${ROOT_DIR}/README.md"
# Editor inputs, including build ARGs, must stay outside the GCC parent stage.
python3 - "${dockerfile}" <<'PYTEST'
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).read_text()
platform, final = source.rsplit("FROM sdk-platform\n", 1)
for editor_input in (
    "ARG CODE_SERVER_",
    "ENV CODE_SERVER_VERSION=",
    "COPY vscode-extension/",
    "COPY tools/brand_code_server.py",
    "COPY scripts/install-neat-vscode-extension.py",
):
    assert editor_input not in platform, f"Editor input invalidates GCC: {editor_input}"
    assert editor_input in final, f"Editor input missing from final image: {editor_input}"
PYTEST
grep -Fq '      binutils \' "${dockerfile}"
grep -Eq '^ARG CODEX_CLI_VERSION=[0-9]+[.][0-9]+[.][0-9]+$' "${dockerfile}"
grep -Eq '^ARG DOCKER_CLI_VERSION=[0-9]+[.][0-9]+[.][0-9]+$' "${dockerfile}"
grep -Eq '^ARG DOCKER_BUILDX_VERSION=[0-9]+[.][0-9]+[.][0-9]+$' "${dockerfile}"
grep -Fq '/usr/local/lib/docker/cli-plugins/docker-buildx' "${dockerfile}"
grep -Fq 'docker buildx version | grep -F "v${DOCKER_BUILDX_VERSION}"' "${dockerfile}"
grep -Fq 'uses: docker/setup-qemu-action@v4' "${workflow}"
grep -Fq 'platforms: arm64' "${workflow}"
grep -Fq '"${SCRIPT_DIR}/container-build/run-sdk-image.sh" "${IMAGE_REF}"' "${ROOT_DIR}/tests/sdk/run-smoke-tests.sh"
grep -Fq 'Skipping SDK container-build smoke test: Neat Core is not installed.' "${ROOT_DIR}/tests/sdk/container-build/run.sh"
grep -Fq "Hello from sima-neat" "${ROOT_DIR}/tests/sdk/container-build/run.sh"
grep -Fq 'ENTRYPOINT ["/usr/local/bin/sima_neat_hello"]' "${ROOT_DIR}/tests/sdk/container-build/context/Dockerfile"
grep -Fq 'Neat SDK 3.0 and newer containers automatically receive access' "${readme}"
grep -Fq 'com.sima.sdk.platform.version="${BASE_SDK_VERSION}"' "${dockerfile}"
grep -Fq 'npm install -g "@openai/codex@${CODEX_CLI_VERSION}"' "${dockerfile}"
grep -Fq 'test "$(codex --version)" = "codex-cli ${CODEX_CLI_VERSION}"' "${dockerfile}"
if grep -Fq 'apt-get purge -y npm' "${dockerfile}"; then
  echo "The SDK must retain npm so sudo codex update can update the global Codex installation." >&2
  exit 1
fi
grep -Fq 'sudo codex update' "${readme}"
grep -Fq -- '--mount=type=cache,id=sima-sdk-debs-v1,target=/var/cache/sima-sdk-debs,sharing=locked' "${dockerfile}"
grep -Fq 'SYSROOT_UPDATE_DOWNLOAD_DIR=/var/cache/sima-sdk-debs' "${dockerfile}"
grep -Fq 'path: .buildkit-cache/sima-sdk-debs' "${workflow}"
grep -Fq "key: sdk-debs-v1-\${{ runner.os }}-\${{ needs.resolve-platform-config.outputs.base_sdk_version }}-\${{ hashFiles('Dockerfile', 'scripts/setup-sdk-sysroot.sh', 'scripts/simaai_setup_sdk.py') }}-\${{ github.run_id }}-\${{ github.run_attempt }}" "${workflow}"
grep -Fq "sdk-debs-v1-\${{ runner.os }}-\${{ needs.resolve-platform-config.outputs.base_sdk_version }}-\${{ hashFiles('Dockerfile', 'scripts/setup-sdk-sysroot.sh', 'scripts/simaai_setup_sdk.py') }}-" "${workflow}"
grep -Fq 'reproducible-containers/buildkit-cache-dance@5de31fc1534ed8789e63d41ea933c5df9944a261' "${workflow}"
grep -Fq '"target": "/var/cache/sima-sdk-debs"' "${workflow}"
grep -Fq '"id": "sima-sdk-debs-v1"' "${workflow}"
grep -Fq 'skip-extraction: false' "${workflow}"
if grep -Fq 'skip-extraction: ${{ steps.sdk-deb-cache.outputs.cache-hit }}' "${workflow}"; then
  echo "An exact cache hit must not suppress persistence of repaired packages." >&2
  exit 1
fi
if grep -Fq 'shutil.rmtree(dldir' "${ROOT_DIR}/scripts/simaai_setup_sdk.py"; then
  echo "The persistent package cache must not be deleted before each SDK build." >&2
  exit 1
fi

installer_script="${ROOT_DIR}/scripts/install-sima-cli.sh"
grep -Fq 'installer_source_commit=6c29a46682bc74a5e95dd2410e8653c7c5264c53' "${installer_script}"
grep -Fq 'raw.githubusercontent.com/sima-neat/sima-cli/${installer_source_commit}/scripts/install/install.py' "${installer_script}"
grep -Fq 'installer_sha256=9d7acf0bfb24f7b32abd305754359744f1034bbd1a440b6310037eef90696c25' "${installer_script}"
if grep -Fq 'artifacts.neat.sima.ai/sima-cli/install.py' "${installer_script}"; then
  echo "The SDK must not checksum a mutable sima-cli installer URL." >&2
  exit 1
fi

echo "SDK build helper tests passed."

SDK_APT_CHANNEL=daily BASE_SDK_VERSION=3.0.0~git202609090513.9e68a68-1218 \
  run_build "${ROOT_DIR}/build.sh" example/sdk agate
assert_arg SDK_APT_CHANNEL=daily
assert_arg SDK_CROSS_TOOLCHAIN_IMAGE=debian:trixie
assert_arg BASE_SDK_VERSION=3.0.0~git202609090513.9e68a68-1218
assert_arg NEAT_CORE_SOURCE_REF=
assert_arg 'NEAT_CORE_SOURCE_REASON=platform-only SDK does not bundle Core'
assert_arg NEAT_APPS_SOURCE_REF=

# The unconfigured build helper uses the official release and resolves Core/Apps.
cat > "${TMP_DIR}/Packages" <<'EOF'
Package: simaai-palette-modalix
Version: 3.0.0~git202609090314.abcdef0-1211
Architecture: all

Package: simaai-palette-modalix
Version: 3.0.0~git202609090314.abcdef0-1218
Architecture: all
EOF
env -u SDK_APT_CHANNEL -u BASE_SDK_VERSION \
  DOCKER_ARGS_LOG="${TMP_DIR}/docker-args" PATH="${TMP_DIR}/bin:${PATH}" \
  PRE_RELEASE_PACKAGES_FILE="${TMP_DIR}/Packages" SDK_PKG_LIST=libpgm-dev DOCKER_PLATFORM=linux/amd64 \
  GITHUB_REF_NAME=3.0.0-prep GITHUB_REF_TYPE=branch \
  NEAT_CORE_SOURCE_REF=1111111111111111111111111111111111111111 \
  NEAT_APPS_SOURCE_REF=2222222222222222222222222222222222222222 \
  BUILDX_OUTPUT=load "${ROOT_DIR}/build.sh" example/sdk default-release
assert_arg SDK_APT_CHANNEL=release
assert_arg SDK_CROSS_TOOLCHAIN_IMAGE=debian:trixie
assert_arg BASE_SDK_VERSION=3.0.0
assert_arg NEAT_CORE_SOURCE_REF=1111111111111111111111111111111111111111
assert_arg NEAT_APPS_SOURCE_REF=2222222222222222222222222222222222222222
assert_arg SDK_PKG_LIST=libpgm-dev

# Master pre-release builds retain Core and Apps without an override flag.
SDK_APT_CHANNEL=pre-release BASE_SDK_VERSION=3.0.0~pre2372 \
  run_build "${ROOT_DIR}/build.sh" example/sdk master
assert_arg SDK_APT_CHANNEL=pre-release
assert_arg NEAT_CORE_SOURCE_REF=1111111111111111111111111111111111111111
assert_arg NEAT_APPS_SOURCE_REF=2222222222222222222222222222222222222222
assert_arg BASE_SDK_VERSION=3.0.0~pre2372

# Decide whether to bundle only after resolving a master selector from daily defaults.
cat > "${TMP_DIR}/MasterPackages" <<'EOF'
Package: simaai-palette-modalix
Version: 3.0.0~pre2372
Architecture: all
EOF
SDK_APT_CHANNEL=daily BASE_SDK_VERSION=3.0.0~pre2372 \
  PRE_RELEASE_PACKAGES_FILE="${TMP_DIR}/MasterPackages" \
  run_build "${ROOT_DIR}/build.sh" example/sdk resolved-master
assert_arg SDK_APT_CHANNEL=pre-release
assert_arg NEAT_CORE_SOURCE_REF=1111111111111111111111111111111111111111
assert_arg NEAT_APPS_SOURCE_REF=2222222222222222222222222222222222222222

# Execute the actual build-time marker command without writing to /etc.
python3 - "${ROOT_DIR}/Dockerfile" <<'PYTEST'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
start = source.index('RUN platform_version=')
command = source[start + 4:source.index('\n\n', start)].replace('/etc/sdk-release', 'sdk-release')
with tempfile.TemporaryDirectory() as directory:
    version_file = Path(directory) / 'platform-version'
    for version in ('3.0.0', '3.0.0~pre2372', '3.0.0~git202610260120.b3607b4-2381', '2.1.2.3'):
        version_file.write_text(version + '\n')
        subprocess.run(['/bin/sh', '-ec', command], cwd=directory,
                       env=dict(os.environ, SDK_PLATFORM_VERSION_FILE=str(version_file)), check=True)
        fields = dict(line.split(' = ', 1) for line in (Path(directory) / 'sdk-release').read_text().splitlines())
        assert fields['Platform Version'] == version
        assert fields['SDK Version'] == version + '_Palette_SDK'
        assert fields['Platform Base'] == version.split('~', 1)[0]
        # sima-cli's numeric compatibility comparison must accept this field.
        assert tuple(map(int, fields['Platform Base'].split('.')))
PYTEST

# Exercise Core-layer ordering and error propagation with no network or root writes.
python3 - "${ROOT_DIR}/Dockerfile" <<'PYTEST'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
start = source.index('RUN echo "Neat Core resolution attempt:')
command = source[start + 4:source.index('\n\n', start)]
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    for name, script in {
        'apt-get': 'echo apt >> "$CALL_LOG"; exit "${APT_STATUS:-0}"',
        'install-neat-resources.sh': 'echo "core $*" >> "$CALL_LOG"; exit "${CORE_STATUS:-0}"',
        'rm': 'echo cleanup >> "$CALL_LOG"',
    }.items():
        path = root / name
        path.write_text('#!/bin/sh\n' + script + '\n')
        path.chmod(0o755)
    for channel, apt_status, core_status, expected, status in (
        ('daily', 0, 0, ['core --skip platform-only SDK does not bundle Core'], 0),
        ('pre-release', 0, 0, ['apt', 'core ', 'cleanup'], 0),
        ('release', 0, 0, ['apt', 'core ', 'cleanup'], 0),
        ('pre-release', 42, 0, ['apt'], 42),
        ('pre-release', 0, 43, ['apt', 'core '], 43),
    ):
        log = root / 'calls'
        log.write_text('')
        env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                   CALL_LOG=str(log), SDK_APT_CHANNEL=channel,
                   APT_STATUS=str(apt_status), CORE_STATUS=str(core_status))
        result = subprocess.run(['/bin/sh', '-c', command], env=env, capture_output=True, text=True)
        assert result.returncode == status, (channel, result)
        assert log.read_text().splitlines() == expected, log.read_text()
PYTEST
