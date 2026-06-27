#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALLER="${ROOT_DIR}/tools/install_sdk_stub.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

write_fake_sima_cli() {
  local path="$1"
  local log="$2"

  mkdir -p "$(dirname "${path}")"
  cat > "${path}" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "${log}"
EOF
  chmod +x "${path}"
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

home_dir="${tmpdir}/home"
log_path="${tmpdir}/sima-cli.log"
mkdir -p "${home_dir}"

write_fake_sima_cli "${home_dir}/.sima-cli/.venv/bin/sima-cli" "${log_path}"

printf 'n\n' | HOME="${home_dir}" PATH="/usr/bin:/bin" "${INSTALLER}" >/dev/null
grep -Fxq "sdk setup" "${log_path}" || fail "installer did not use the user sima-cli install when PATH omitted it"

: > "${log_path}"
override_cli="${tmpdir}/override/sima-cli"
write_fake_sima_cli "${override_cli}" "${log_path}"

printf 'y\n10.0.0.244\n' | HOME="${home_dir}" PATH="/usr/bin:/bin" SIMA_CLI="${override_cli}" "${INSTALLER}" >/dev/null
grep -Fxq "sdk setup --devkit 10.0.0.244" "${log_path}" || fail "installer did not honor SIMA_CLI override"

if printf 'n\n' | HOME="${home_dir}" PATH="/usr/bin:/bin" SIMA_CLI="${tmpdir}/missing/sima-cli" "${INSTALLER}" >/dev/null 2>"${tmpdir}/stderr"; then
  fail "installer should fail when SIMA_CLI points to a missing executable"
fi
grep -Fq "SIMA_CLI is set but is not executable" "${tmpdir}/stderr" || fail "missing SIMA_CLI error was not clear"

echo "install sdk stub tests passed"
