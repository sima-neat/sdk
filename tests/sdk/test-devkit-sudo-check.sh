#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

DEVKIT_SH_FUNCTIONS_ONLY=1 source "${ROOT_DIR}/scripts/devkit.sh"

mkdir -p "${tmpdir}/bin"
cat > "${tmpdir}/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SSH_LOG:?}"
read -r -a results <<< "${FAKE_SSH_RESULTS:?}"
call="$(wc -l < "${SSH_LOG}")"
result="${results[call - 1]:-0}"
if [[ "${result}" == hang ]]; then
  exec sleep 30
fi
exit "${result}"
EOF
chmod +x "${tmpdir}/bin/ssh"

export PATH="${tmpdir}/bin:${PATH}"
export SSH_LOG="${tmpdir}/ssh.log"
export DEVKIT_SUDO_CHECK_TIMEOUT=1

expect_check() {
  local results="$1"
  local expected_status="$2"
  local expected_calls="$3"
  local status=0
  local calls=""

  : > "${SSH_LOG}"
  export FAKE_SSH_RESULTS="${results}"
  check_remote_passwordless_sudo sima 192.0.2.1 22 2>"${tmpdir}/stderr" || status=$?
  calls="$(wc -l < "${SSH_LOG}")"

  [[ "${status}" == "${expected_status}" ]] || \
    fail "ssh results '${results}' returned ${status}, expected ${expected_status}"
  [[ "${calls}" == "${expected_calls}" ]] || \
    fail "ssh results '${results}' made ${calls} ssh calls, expected ${expected_calls}"
}

expect_check "0" 0 1
grep -Fq -- "-T -n " "${SSH_LOG}" || fail "sudo check should run ssh without a tty and without stdin"
if grep -Fq -- "-tt" "${SSH_LOG}"; then
  fail "sudo check should not force a tty"
fi

expect_check "1" 1 1
expect_check "hang 0" 0 2
expect_check "255 1" 1 2

expect_check "hang hang" 2 2
grep -Fq "timed out after 1s" "${tmpdir}/stderr" || fail "sudo check timeout was not reported"

expect_check "255 255" 2 2
grep -Fq "failed to connect over SSH" "${tmpdir}/stderr" || fail "sudo check SSH failure was not reported"

echo "devkit sudo check tests passed"
