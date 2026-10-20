#!/usr/bin/env bash
set -euo pipefail

host="${CODE_SERVER_HOST:-${OPENVSCODE_SERVER_HOST:-0.0.0.0}}"
port="${CODE_SERVER_PORT:-${OPENVSCODE_SERVER_PORT:-9999}}"
https_port="${CODE_SERVER_HTTPS_PORT:-${OPENVSCODE_SERVER_HTTPS_PORT:-10000}}"
workspace="${1:-${CODE_SERVER_WORKSPACE:-${OPENVSCODE_WORKSPACE:-/workspace}}}"
server_dir="${CODE_SERVER_DIR:-/opt/code-server}"
cert_file="${CODE_SERVER_CERT:-${OPENVSCODE_SERVER_CERT:-}}"
cert_key_file="${CODE_SERVER_CERT_KEY:-${OPENVSCODE_SERVER_CERT_KEY:-}}"
tls_enabled=0
generated_password=0

format_host_port() {
  local address="$1"
  local address_port="$2"

  if [[ "${address}" == \[*\] ]]; then
    printf '%s:%s' "${address}" "${address_port}"
  elif [[ "${address}" == *:* ]]; then
    printf '[%s]:%s' "${address}" "${address_port}"
  else
    printf '%s:%s' "${address}" "${address_port}"
  fi
}

if user_entry="$(getent passwd "$(id -u)" 2>/dev/null)"; then
  current_user="$(printf '%s' "${user_entry}" | cut -d: -f1)"
  current_home="$(printf '%s' "${user_entry}" | cut -d: -f6)"
  current_shell="$(printf '%s' "${user_entry}" | cut -d: -f7)"
  export USER="${current_user}"
  export LOGNAME="${current_user}"
  export HOME="${current_home}"
  export SHELL="${current_shell:-/bin/bash}"
fi

data_dir="${CODE_SERVER_USER_DATA_DIR:-${HOME:-/root}/.local/share/code-server}"
extensions_dir="${CODE_SERVER_EXTENSIONS_DIR:-${OPENVSCODE_SERVER_EXTENSIONS_DIR:-${data_dir}/extensions}}"
server_bin="${server_dir}/bin/code-server"

if [[ ! -x "${server_bin}" ]]; then
  echo "code-server not found at ${server_bin}" >&2
  exit 1
fi

mkdir -p "${data_dir}" "${extensions_dir}"

server_args=(
  --config /dev/null
  --bind-addr "$(format_host_port "${host}" "${port}")"
  --extensions-dir "${extensions_dir}"
  --user-data-dir "${data_dir}"
  --disable-telemetry
  --disable-update-check
)

password="${CODE_SERVER_PASSWORD:-${OPENVSCODE_SERVER_TOKEN:-}}"
without_password="${CODE_SERVER_WITHOUT_PASSWORD:-${OPENVSCODE_SERVER_WITHOUT_TOKEN:-0}}"
if [[ "${without_password}" == "1" ]]; then
  # An upstream-authenticated gateway such as Arthas may still use launch tooling
  # that injects a password. The explicit no-password mode must take precedence.
  unset PASSWORD
  server_args+=(--auth none)
elif [[ -z "${password}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  elif command -v openssl >/dev/null 2>&1; then
    password="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
  else
    echo "CODE_SERVER_PASSWORD is required because no password generator is available." >&2
    exit 1
  fi
  generated_password=1
  export PASSWORD="${password}"
  server_args+=(--auth password)
else
  export PASSWORD="${password}"
  server_args+=(--auth password)
fi

if [[ -n "${cert_file}" || -n "${cert_key_file}" ]]; then
  if [[ -f "${cert_file}" && -f "${cert_key_file}" ]]; then
    tls_enabled=1
  else
    echo "code-server HTTPS cert/key not found; expected '${cert_file}' and '${cert_key_file}'." >&2
    exit 1
  fi
elif [[ -f /sdk-cert/neat-sdk.pem && -f /sdk-cert/neat-sdk-key.pem ]]; then
  cert_file=/sdk-cert/neat-sdk.pem
  cert_key_file=/sdk-cert/neat-sdk-key.pem
  tls_enabled=1
fi

if [[ "${generated_password}" == "1" ]]; then
  display_host="${host}"
  display_port="${port}"
  display_scheme="http"
  if [[ "${tls_enabled}" == "1" ]]; then
    display_port="${https_port}"
    display_scheme="https"
  fi
  if [[ "${display_host}" == "0.0.0.0" || "${display_host}" == "::" ]]; then
    display_host="localhost"
  elif [[ "${display_host}" == *:* && "${display_host}" != \[*\] ]]; then
    display_host="[${display_host}]"
  fi
  echo "Generated a temporary code-server password for this process." >&2
  echo "Open the Code UI at: ${display_scheme}://${display_host}:${display_port}/?folder=/workspace" >&2
  echo "Password: ${password}" >&2
fi

if [[ "${tls_enabled}" != "1" ]]; then
  exec "${server_bin}" "${server_args[@]}" "${workspace}"
fi

backend_host="${CODE_SERVER_HTTPS_BACKEND_HOST:-${OPENVSCODE_SERVER_HTTPS_BACKEND_HOST:-127.0.0.1}}"
backend_port="${CODE_SERVER_HTTPS_BACKEND_PORT:-${OPENVSCODE_SERVER_HTTPS_BACKEND_PORT:-${port}}}"
https_host="${CODE_SERVER_HTTPS_HOST:-${OPENVSCODE_SERVER_HTTPS_HOST:-${host}}}"

"${server_bin}" "${server_args[@]}" "${workspace}" &
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

if wait -n "${server_pid}" "${proxy_pid}"; then
  status=0
else
  status=$?
fi
kill "${server_pid}" "${proxy_pid}" 2>/dev/null || true
wait "${server_pid}" "${proxy_pid}" 2>/dev/null || true
exit "${status}"
