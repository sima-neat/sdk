#!/usr/bin/env bash
set -euo pipefail

host="${OPENVSCODE_SERVER_HOST:-0.0.0.0}"
port="${OPENVSCODE_SERVER_PORT:-9999}"
workspace="${1:-${OPENVSCODE_WORKSPACE:-/workspace}}"
server_dir="${OPENVSCODE_SERVER_DIR:-/opt/openvscode-server}"
extensions_dir="${OPENVSCODE_SERVER_EXTENSIONS_DIR:-/opt/openvscode-server/extensions}"

if [[ ! -x "${server_dir}/bin/openvscode-server" ]]; then
  echo "openvscode-server not found at ${server_dir}/bin/openvscode-server" >&2
  exit 1
fi

args=(
  --host "${host}"
  --port "${port}"
  --extensions-dir "${extensions_dir}"
  --accept-server-license-terms
)

if [[ -n "${OPENVSCODE_SERVER_TOKEN:-}" ]]; then
  args+=(--connection-token "${OPENVSCODE_SERVER_TOKEN}")
elif [[ "${OPENVSCODE_SERVER_WITHOUT_TOKEN:-1}" == "1" ]]; then
  args+=(--without-connection-token)
fi

exec "${server_dir}/bin/openvscode-server" "${args[@]}" "${workspace}"
