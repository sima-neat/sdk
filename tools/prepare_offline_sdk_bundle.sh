#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: tools/prepare_offline_sdk_bundle.sh \
  --output-dir <path> \
  --image-ref <ghcr.io/sima-neat/sdk:tag> \
  --target-arch <x86_64|aarch64> \
  [--version <package-version>] \
  [--release <release-id>]

Builds an architecture-specific offline SDK package. The package contains a
compressed Docker image archive and an installer script that loads the image
before running the normal SDK setup flow.
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR=""
IMAGE_REF=""
TARGET_ARCH=""
PACKAGE_VERSION=""
PACKAGE_RELEASE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --image-ref)
      IMAGE_REF="${2:-}"
      shift 2
      ;;
    --target-arch)
      TARGET_ARCH="${2:-}"
      shift 2
      ;;
    --version)
      PACKAGE_VERSION="${2:-}"
      shift 2
      ;;
    --release)
      PACKAGE_RELEASE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${OUTPUT_DIR}" || -z "${IMAGE_REF}" || -z "${TARGET_ARCH}" ]]; then
  echo "Missing required arguments." >&2
  usage >&2
  exit 1
fi

case "${TARGET_ARCH}" in
  x86_64)
    DOCKER_PLATFORM="linux/amd64"
    ;;
  aarch64|arm64)
    TARGET_ARCH="aarch64"
    DOCKER_PLATFORM="linux/arm64"
    ;;
  *)
    echo "Unsupported target architecture: ${TARGET_ARCH}" >&2
    exit 1
    ;;
esac

for tool in docker sima-cli zstd sha256sum; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "Required command not found: ${tool}" >&2
    exit 1
  fi
done

if [[ -z "${PACKAGE_VERSION}" ]]; then
  if [[ "${GITHUB_REF_TYPE:-}" == "tag" && -n "${GITHUB_REF_NAME:-}" ]]; then
    PACKAGE_VERSION="${GITHUB_REF_NAME#v}"
  elif [[ -n "${GITHUB_HEAD_REF:-}" ]]; then
    PACKAGE_VERSION="${GITHUB_HEAD_REF}"
  elif [[ -n "${GITHUB_REF_NAME:-}" ]]; then
    PACKAGE_VERSION="${GITHUB_REF_NAME}"
  else
    PACKAGE_VERSION="$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
  fi
fi

if [[ -z "${PACKAGE_RELEASE}" ]]; then
  PACKAGE_RELEASE="${PACKAGE_VERSION}"
fi

tmp_dir="$(mktemp -d /tmp/sima-sdk-offline-package-XXXXXX)"
cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

artifacts_dir="${tmp_dir}/artifacts"
mkdir -p "${artifacts_dir}"

archive_name="sdk-image-${TARGET_ARCH}.tar.zst"
archive_path="${artifacts_dir}/${archive_name}"
package_name="sdk-offline-${TARGET_ARCH}"

echo "Pulling SDK image for ${DOCKER_PLATFORM}: ${IMAGE_REF}"
docker pull --platform "${DOCKER_PLATFORM}" "${IMAGE_REF}"

echo "Saving and compressing SDK image archive: ${archive_name}"
docker save "${IMAGE_REF}" | zstd -T0 -10 -o "${archive_path}"

echo "Cleaning local Docker image data after archive creation."
docker image rm "${IMAGE_REF}" >/dev/null 2>&1 || true
docker system prune -af >/dev/null 2>&1 || true

install -m 0755 "${ROOT_DIR}/tools/install_offline_sdk.sh" "${artifacts_dir}/install_offline_sdk.sh"

cat > "${artifacts_dir}/README.txt" <<EOF
SiMa.ai Neat SDK offline bundle
================================

Image: ${IMAGE_REF}
Architecture: ${TARGET_ARCH}

To install:

  bash ./install_offline_sdk.sh

The installer loads ${archive_name} into Docker and then runs the normal
sima-cli SDK setup flow. sima-cli and Docker must already be installed on the
target host.
EOF

(
  cd "${artifacts_dir}"
  sha256sum "${archive_name}" install_offline_sdk.sh README.txt > SHA256SUMS
)

SIMA_CLI_CHECK_FOR_UPDATE=0 sima-cli packages build "${artifacts_dir}" \
  --name "${package_name}" \
  --version "${PACKAGE_VERSION}" \
  --description "SiMa.ai Neat SDK offline install bundle (${TARGET_ARCH})" \
  --install-script "install_offline_sdk.sh" \
  --host-platform "ubuntu@22.04,ubuntu@24.04" \
  --host-platform "windows" \
  --host-platform "mac" \
  --host-arch "${TARGET_ARCH}"

python3 - "${artifacts_dir}/metadata.json" "${PACKAGE_RELEASE}" "${TARGET_ARCH}" "${IMAGE_REF}" <<'PY'
import json
import sys
from pathlib import Path

metadata_path = Path(sys.argv[1])
release = sys.argv[2]
target_arch = sys.argv[3]
image_ref = sys.argv[4]

metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
metadata["release"] = release
metadata["installation"]["post-message"] = (
    "[bold green]Offline SDK setup complete.[/bold green]\n"
    "Run [cyan]sima-cli sdk neat[/cyan] to open the Neat SDK container.\n"
)
metadata["offline"] = {
    "container-image": image_ref,
    "architecture": target_arch,
    "archive": f"sdk-image-{target_arch}.tar.zst",
}
metadata_path.write_text(json.dumps(metadata, indent=4) + "\n", encoding="utf-8")
PY

python3 -m json.tool "${artifacts_dir}/metadata.json" >/dev/null

rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"
cp -f "${artifacts_dir}/"* "${OUTPUT_DIR}/"

echo "Prepared SDK offline package:"
ls -lh "${OUTPUT_DIR}"
