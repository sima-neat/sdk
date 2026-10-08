#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${ROOT_DIR}/scripts/insight-network-test.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
mkdir -p "${tmpdir}/bin"

cat > "${tmpdir}/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

output_file=""
url=""
while (( $# > 0 )); do
  case "$1" in
    -o)
      output_file="$2"
      shift 2
      ;;
    http*)
      url="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ "${url}" == */api/health ]]; then
  printf '{"status":"ok"}\n'
  exit 0
fi

if [[ "${url}" == */api/ingest/stats* ]]; then
  count=4
  [[ ! -f "${MOCK_PROBE_SENT}" ]] || count=5
  printf '{"channels":[{"channel":0,"metadata":{"messages_received":%s}}]}\n' "${count}" > "${output_file}"
  exit 0
fi

exit 1
EOF

cat > "${tmpdir}/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
touch "${MOCK_PROBE_SENT}"
echo 'TCP PASS: DevKit reached Insight at https://192.0.2.1:9900/api/health.'
EOF

chmod +x "${tmpdir}/bin/curl" "${tmpdir}/bin/ssh"

output="$({
  PATH="${tmpdir}/bin:${PATH}" \
  MOCK_PROBE_SENT="${tmpdir}/probe-sent" \
  DEVKIT_SYNC_DEVKIT_IP=192.0.2.2 \
  DEVKIT_SYNC_DEVKIT_USER=sima \
  DEVKIT_SYNC_DEVKIT_PORT=22 \
  CONTAINER_HOST_IP=192.0.2.1 \
    "${SCRIPT}"
} 2>&1)" || fail "expected network test to succeed: ${output}"

grep -Fq 'TCP PASS: DevKit reached Insight at https://192.0.2.1:9900/api/health.' <<< "${output}" || \
  fail "success output did not include the TCP result: ${output}"

grep -Fq 'UDP PASS: Insight received the DevKit probe on port 9100 (4 -> 5 messages).' <<< "${output}" || \
  fail "success output did not include the counter change: ${output}"

if PATH="${tmpdir}/bin:${PATH}" \
  DEVKIT_SYNC_DEVKIT_IP=192.0.2.2 \
  CONTAINER_HOST_IP='' \
    "${SCRIPT}" >"${tmpdir}/missing-env.out" 2>&1; then
  fail "expected missing host address to fail"
fi

grep -Fq 'No paired DevKit network configuration was found.' "${tmpdir}/missing-env.out" || \
  fail "missing configuration failure was not explained"

if DEVKIT_SYNC_DEVKIT_IP=192.0.2.2 CONTAINER_HOST_IP=192.0.2.1 \
  "${SCRIPT}" 80 >"${tmpdir}/bad-channel.out" 2>&1; then
  fail "expected channel 80 to fail validation"
fi

grep -Fq 'Channel must be an integer from 0 through 79.' "${tmpdir}/bad-channel.out" || \
  fail "invalid channel failure was not explained"

cat > "${tmpdir}/bin/insight-network-test" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
touch "${MOCK_STATUS_TEST_RAN}"
echo 'TCP PASS: reverse test ran'
echo 'UDP PASS: reverse test ran'
EOF
chmod +x "${tmpdir}/bin/insight-network-test"

sed -n '/^devkit-status()/,/^}/p' "${ROOT_DIR}/scripts/devkit.sh" > "${tmpdir}/devkit-status.sh"
# shellcheck source=/dev/null
source "${tmpdir}/devkit-status.sh"

status_output="$({
  PATH="${tmpdir}/bin:${PATH}" \
  MOCK_PROBE_SENT="${tmpdir}/status-ssh-ran" \
  MOCK_STATUS_TEST_RAN="${tmpdir}/status-test-ran" \
  DEVKIT_SYNC_DEVKIT_IP=192.0.2.2 \
  DEVKIT_SYNC_DEVKIT_USER=sima \
  DEVKIT_SYNC_DEVKIT_PORT=22 \
  DEVKIT_SYNC_METHOD=none \
    devkit-status
} 2>&1)" || fail "expected dk status function to succeed: ${status_output}"

[[ -f "${tmpdir}/status-test-ran" ]] || fail "dk status did not run the Insight reverse test"
grep -Fq 'TCP PASS: reverse test ran' <<< "${status_output}" || fail "dk status omitted TCP result"
grep -Fq 'UDP PASS: reverse test ran' <<< "${status_output}" || fail "dk status omitted UDP result"

echo "Insight network test script tests passed"
