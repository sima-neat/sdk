#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: tools/prepare_vscode_extension_package.sh \
  --output-dir <path> \
  [--version <package-version>] \
  [--release <release-id>]

Builds the SiMa Neat VS Code extension VSIX and Vulcan/sima-cli package
metadata. The package is compatible with Palette SDK containers and installs
the extension by invoking `code --install-extension`.
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTENSION_DIR="${ROOT_DIR}/vscode-extension"
OUTPUT_DIR=""
PACKAGE_VERSION=""
PACKAGE_RELEASE=""
PACKAGE_NAME="${SDK_VSCODE_EXTENSION_PACKAGE_NAME:-vscode-extension}"
INSTALL_SCRIPT_NAME="install_vscode_extension.sh"
VSIX_NAME="sima-neat.vsix"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="${2:-}"
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

if [[ -z "${OUTPUT_DIR}" ]]; then
  echo "Missing required --output-dir." >&2
  usage >&2
  exit 1
fi

if [[ ! -d "${EXTENSION_DIR}" ]]; then
  echo "Extension directory not found: ${EXTENSION_DIR}" >&2
  exit 1
fi

if ! command -v sima-cli >/dev/null 2>&1; then
  echo "sima-cli is required to build package metadata." >&2
  exit 1
fi

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
  PACKAGE_RELEASE="${GITHUB_SHA:-${PACKAGE_VERSION}}"
fi

tmp_dir="$(mktemp -d /tmp/sima-sdk-vscode-extension-package-XXXXXX)"
cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

artifacts_dir="${tmp_dir}/artifacts"
mkdir -p "${artifacts_dir}"

(
  cd "${EXTENSION_DIR}"
  npx --yes @vscode/vsce package \
    --no-dependencies \
    --out "${artifacts_dir}/${VSIX_NAME}"
)

install -m 0755 "${ROOT_DIR}/tools/${INSTALL_SCRIPT_NAME}" "${artifacts_dir}/${INSTALL_SCRIPT_NAME}"

SIMA_CLI_CHECK_FOR_UPDATE=0 sima-cli packages build "${artifacts_dir}" \
  --name "${PACKAGE_NAME}" \
  --version "${PACKAGE_VERSION}" \
  --description "SiMa Neat VS Code extension for SDK workspaces" \
  --install-script "./${INSTALL_SCRIPT_NAME}" \
  --palette-platform

python3 - "${artifacts_dir}/metadata.json" "${PACKAGE_RELEASE}" <<'PY'
import json
import sys
from pathlib import Path

metadata_path = Path(sys.argv[1])
release = sys.argv[2]

metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
metadata["release"] = release
metadata["installation"]["post-message"] = (
    "[bold green]SiMa Neat VS Code extension installed.[/bold green]\n"
    "Reload the Code window if the SiMa Neat activity bar view is already open.\n"
)
metadata_path.write_text(json.dumps(metadata, indent=4) + "\n", encoding="utf-8")
PY

python3 -m json.tool "${artifacts_dir}/metadata.json" >/dev/null

rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"
cp -f \
  "${artifacts_dir}/${VSIX_NAME}" \
  "${artifacts_dir}/${INSTALL_SCRIPT_NAME}" \
  "${artifacts_dir}/metadata.json" \
  "${OUTPUT_DIR}/"

echo "Prepared VS Code extension package:"
ls -lh "${OUTPUT_DIR}"
