#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
vsix_path="${script_dir}/sima-neat.vsix"

if [[ ! -f "${vsix_path}" ]]; then
  echo "VS Code extension package not found: ${vsix_path}" >&2
  exit 1
fi

if command -v code >/dev/null 2>&1; then
  code --install-extension "${vsix_path}" --force
elif command -v openvscode-server >/dev/null 2>&1; then
  openvscode-server --install-extension "${vsix_path}" --force
elif [[ -x "${OPENVSCODE_SERVER_DIR:-/opt/openvscode-server}/bin/openvscode-server" ]]; then
  "${OPENVSCODE_SERVER_DIR:-/opt/openvscode-server}/bin/openvscode-server" --install-extension "${vsix_path}" --force
else
  echo "Neither 'code' nor openvscode-server was found. Run this installer inside an SDK Code container." >&2
  exit 1
fi

echo "SiMa Neat VS Code extension installed."
echo "Reload the Code window if the SiMa Neat activity bar view is already open."
