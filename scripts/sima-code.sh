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
  --default-folder "${workspace}"
)

token="${OPENVSCODE_SERVER_TOKEN:-}"
if [[ -z "${token}" && "${OPENVSCODE_SERVER_WITHOUT_TOKEN:-0}" != "1" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  elif command -v openssl >/dev/null 2>&1; then
    token="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
  else
    echo "OPENVSCODE_SERVER_TOKEN is required because no token generator is available." >&2
    exit 1
  fi
  display_host="${host}"
  if [[ "${display_host}" == "0.0.0.0" || "${display_host}" == "::" ]]; then
    display_host="localhost"
  fi
  echo "Generated temporary OpenVSCode Server token for this process." >&2
  echo "Open the Code UI with: http://${display_host}:${port}/?t=${token}" >&2
fi

if [[ -n "${token}" ]]; then
  args+=(--connection-token "${token}")
elif [[ "${OPENVSCODE_SERVER_WITHOUT_TOKEN:-0}" == "1" ]]; then
  args+=(--without-connection-token)
fi

exec "${server_dir}/bin/openvscode-server" "${args[@]}"
