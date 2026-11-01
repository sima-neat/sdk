#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
launcher="${repo_root}/scripts/sima-code.sh"
supervised_launcher="${repo_root}/scripts/code-server-supervised.sh"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

fake_dir="${tmpdir}/code-server"
mkdir -p "${fake_dir}/bin"

cat >"${fake_dir}/bin/code-server" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >"${CAPTURE_ARGS}"
printf '%s' "${PASSWORD:-}" >"${CAPTURE_PASSWORD}"
EOF
chmod +x "${fake_dir}/bin/code-server"

capture_args="${tmpdir}/args"
capture_password="${tmpdir}/password"
data_dir="${tmpdir}/data"
extensions_dir="${tmpdir}/extensions"

CODE_SERVER_DIR="${fake_dir}" \
CODE_SERVER_PASSWORD="test-password" \
CODE_SERVER_HOST="127.0.0.1" \
CODE_SERVER_PORT="19099" \
CODE_SERVER_USER_DATA_DIR="${data_dir}" \
CODE_SERVER_EXTENSIONS_DIR="${extensions_dir}" \
CAPTURE_ARGS="${capture_args}" \
CAPTURE_PASSWORD="${capture_password}" \
  "${launcher}" /workspace

grep -Fx -- '--bind-addr' "${capture_args}"
grep -Fx -- '--config' "${capture_args}"
grep -Fx -- '/dev/null' "${capture_args}"
grep -Fx -- '127.0.0.1:19099' "${capture_args}"
grep -Fx -- '--extensions-dir' "${capture_args}"
grep -Fx -- "${extensions_dir}" "${capture_args}"
grep -Fx -- '--user-data-dir' "${capture_args}"
grep -Fx -- "${data_dir}" "${capture_args}"
grep -Fx -- '--disable-telemetry' "${capture_args}"
grep -Fx -- '--disable-update-check' "${capture_args}"
grep -Fx -- '--auth' "${capture_args}"
grep -Fx -- 'password' "${capture_args}"
grep -Fx -- '/workspace' "${capture_args}"
test "$(cat "${capture_password}")" = "test-password"

OPENVSCODE_SERVER_TOKEN="legacy-password" \
OPENVSCODE_SERVER_HOST="127.0.0.2" \
OPENVSCODE_SERVER_PORT="19100" \
CODE_SERVER_DIR="${fake_dir}" \
CODE_SERVER_USER_DATA_DIR="${data_dir}" \
CAPTURE_ARGS="${capture_args}" \
CAPTURE_PASSWORD="${capture_password}" \
  "${launcher}" /legacy-workspace
grep -Fx -- '127.0.0.2:19100' "${capture_args}"
grep -Fx -- '/legacy-workspace' "${capture_args}"
test "$(cat "${capture_password}")" = "legacy-password"

CODE_SERVER_PASSWORD="ipv6-password" \
CODE_SERVER_HOST="::1" \
CODE_SERVER_DIR="${fake_dir}" \
CODE_SERVER_USER_DATA_DIR="${data_dir}" \
CAPTURE_ARGS="${capture_args}" \
CAPTURE_PASSWORD="${capture_password}" \
  "${launcher}" /workspace
grep -Fx -- '[::1]:9999' "${capture_args}"

CODE_SERVER_WITHOUT_PASSWORD=1 \
CODE_SERVER_PASSWORD="ignored-by-explicit-no-password-mode" \
CODE_SERVER_DIR="${fake_dir}" \
CODE_SERVER_USER_DATA_DIR="${data_dir}" \
CAPTURE_ARGS="${capture_args}" \
CAPTURE_PASSWORD="${capture_password}" \
  "${launcher}" /workspace
grep -Fx -- 'none' "${capture_args}"
if grep -Fx -- 'password' "${capture_args}"; then
  echo "Explicit no-password mode must override an injected password" >&2
  exit 1
fi
test ! -s "${capture_password}"

if CODE_SERVER_DIR="${fake_dir}" \
  CODE_SERVER_PASSWORD=test \
  CODE_SERVER_CERT="${tmpdir}/missing.pem" \
  CODE_SERVER_USER_DATA_DIR="${data_dir}" \
  CAPTURE_ARGS="${capture_args}" \
  CAPTURE_PASSWORD="${capture_password}" \
  "${launcher}" /workspace >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  echo "Expected a missing TLS certificate to fail" >&2
  exit 1
fi
grep -F "code-server HTTPS cert/key not found" "${tmpdir}/err"

CODE_SERVER_SUPERVISED=0 "${supervised_launcher}" >"${tmpdir}/supervised-out"
grep -F "code-server supervision disabled" "${tmpdir}/supervised-out"
OPENVSCODE_SERVER_SUPERVISED=0 "${supervised_launcher}" >"${tmpdir}/legacy-supervised-out"
grep -F "code-server supervision disabled" "${tmpdir}/legacy-supervised-out"

grep -F 'component_pins="$(python3 /usr/local/bin/sdk-component-pins.py' "${repo_root}/Dockerfile"
grep -F 'sha256sum -c -' "${repo_root}/Dockerfile"
grep -F 'com.sima.sdk.code-ui="code-server-v1"' "${repo_root}/Dockerfile"
if grep -Eq '^ENV CODE_SERVER_(PORT|HTTPS_PORT|SUPERVISED)=' "${repo_root}/Dockerfile"; then
  echo "Dockerfile defaults mask legacy OpenVSCode overrides" >&2
  exit 1
fi
if rg -n '/opt/openvscode-server|gitpod-io/openvscode-server' "${repo_root}/Dockerfile"; then
  echo "Dockerfile still references OpenVSCode" >&2
  exit 1
fi

echo "code-server launcher tests passed"
