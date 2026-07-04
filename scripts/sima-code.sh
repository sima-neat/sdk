#!/usr/bin/env bash
set -euo pipefail

host="${OPENVSCODE_SERVER_HOST:-0.0.0.0}"
port="${OPENVSCODE_SERVER_PORT:-9999}"
https_port="${OPENVSCODE_SERVER_HTTPS_PORT:-10000}"
workspace="${1:-${OPENVSCODE_WORKSPACE:-/workspace}}"
server_dir="${OPENVSCODE_SERVER_DIR:-/opt/openvscode-server}"
extensions_dir="${OPENVSCODE_SERVER_EXTENSIONS_DIR:-${HOME:-/root}/.openvscode-server/extensions}"
cert_file="${OPENVSCODE_SERVER_CERT:-}"
cert_key_file="${OPENVSCODE_SERVER_CERT_KEY:-}"
tls_enabled=0
generated_token=0

if user_entry="$(getent passwd "$(id -u)" 2>/dev/null)"; then
  current_user="$(printf '%s' "${user_entry}" | cut -d: -f1)"
  current_home="$(printf '%s' "${user_entry}" | cut -d: -f6)"
  current_shell="$(printf '%s' "${user_entry}" | cut -d: -f7)"
  export USER="${current_user}"
  export LOGNAME="${current_user}"
  export HOME="${current_home}"
  export SHELL="${current_shell:-/bin/bash}"
fi

if [[ ! -x "${server_dir}/bin/openvscode-server" ]]; then
  echo "openvscode-server not found at ${server_dir}/bin/openvscode-server" >&2
  exit 1
fi

mkdir -p "${extensions_dir}"

server_args=(
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
  generated_token=1
fi

if [[ -n "${token}" ]]; then
  server_args+=(--connection-token "${token}")
elif [[ "${OPENVSCODE_SERVER_WITHOUT_TOKEN:-0}" == "1" ]]; then
  server_args+=(--without-connection-token)
fi

if [[ -n "${cert_file}" || -n "${cert_key_file}" ]]; then
  if [[ -f "${cert_file}" && -f "${cert_key_file}" ]]; then
    tls_enabled=1
  else
    echo "OpenVSCode HTTPS cert/key not found; expected '${cert_file}' and '${cert_key_file}'." >&2
    exit 1
  fi
elif [[ -f /sdk-cert/neat-sdk.pem && -f /sdk-cert/neat-sdk-key.pem ]]; then
  cert_file=/sdk-cert/neat-sdk.pem
  cert_key_file=/sdk-cert/neat-sdk-key.pem
  tls_enabled=1
fi

if [[ "${generated_token}" == "1" ]]; then
  display_host="${host}"
  display_port="${port}"
  display_scheme="http"
  if [[ "${tls_enabled}" == "1" ]]; then
    display_port="${https_port}"
    display_scheme="https"
  fi
  if [[ "${display_host}" == "0.0.0.0" || "${display_host}" == "::" ]]; then
    display_host="localhost"
  fi
  echo "Generated temporary OpenVSCode Server token for this process." >&2
  echo "Open the Code UI with: ${display_scheme}://${display_host}:${display_port}/?tkn=${token}" >&2
fi

if [[ "${tls_enabled}" != "1" ]]; then
  exec "${server_dir}/bin/openvscode-server" "${server_args[@]}"
fi

backend_host="${OPENVSCODE_SERVER_HTTPS_BACKEND_HOST:-127.0.0.1}"
backend_port="${OPENVSCODE_SERVER_HTTPS_BACKEND_PORT:-${port}}"
https_host="${OPENVSCODE_SERVER_HTTPS_HOST:-${host}}"

"${server_dir}/bin/openvscode-server" "${server_args[@]}" &
server_pid=$!

cleanup() {
  kill "${server_pid}" 2>/dev/null || true
  if [[ -n "${proxy_pid:-}" ]]; then
    kill "${proxy_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

python3 - "${cert_file}" "${cert_key_file}" "${backend_host}" "${backend_port}" "${https_host}" "${https_port}" <<'PY' &
import asyncio
import ssl
import sys

cert_file, key_file, backend_host, backend_port, listen_host, listen_port = sys.argv[1:]
backend_port = int(backend_port)
listen_port = int(listen_port)

async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

async def handle(client_reader, client_writer):
    try:
        server_reader, server_writer = await asyncio.open_connection(backend_host, backend_port)
    except Exception:
        client_writer.close()
        return
    await asyncio.gather(
        pipe(client_reader, server_writer),
        pipe(server_reader, client_writer),
        return_exceptions=True,
    )

async def main():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    server = await asyncio.start_server(handle, listen_host, listen_port, ssl=context)
    async with server:
        await server.serve_forever()

asyncio.run(main())
PY
proxy_pid=$!

wait -n "${server_pid}" "${proxy_pid}"
status=$?
kill "${server_pid}" "${proxy_pid}" 2>/dev/null || true
exit "${status}"
