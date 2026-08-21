#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALLER="${ROOT_DIR}/scripts/install-neat-resources.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

create_source_repo() {
  local repository="$1"
  mkdir -p "${repository}"
  git init --quiet "${repository}"
  git -C "${repository}" config user.name test
  git -C "${repository}" config user.email test@example.com
  printf 'source\n' > "${repository}/README"
  git -C "${repository}" add README
  git -C "${repository}" commit --quiet -m source
  git -C "${repository}" rev-parse HEAD
}

core_repository="${tmpdir}/core-repository"
apps_repository="${tmpdir}/apps-repository"
core_source_ref="$(create_source_repo "${core_repository}")"
apps_source_ref="$(create_source_repo "${apps_repository}")"

cat > "${tmpdir}/sima-cli" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

case "${CORE_TEST_MODE:?}" in
  bundled)
    printf 'installed\n' > installed.txt
    printf 'archive\n' > downloaded.deb
    ;;
  incompatible)
    echo 'Palette SDK version 2.1.3 is not compatible. Required: 2.1.2' >&2
    exit 1
    ;;
  unavailable)
    echo 'Error: GET https://artifacts.neat.sima.ai/core/v0.4.0/latest.tag failed: 403 Client Error' >&2
    exit 1
    ;;
  fatal)
    echo 'Downloaded Core artifact checksum mismatch' >&2
    exit 42
    ;;
  *)
    echo "Unsupported CORE_TEST_MODE: ${CORE_TEST_MODE}" >&2
    exit 2
    ;;
esac
EOF
chmod +x "${tmpdir}/sima-cli"

run_installer() {
  local mode="$1"
  local resources_root="${tmpdir}/resources-${mode}"
  local status_file="${tmpdir}/status-${mode}"
  local log_file="${tmpdir}/log-${mode}"

  CORE_TEST_MODE="${mode}" \
  NEAT_CORE_TARGET=core@v0.4.0 \
  NEAT_CORE_SOURCE_REF="${core_source_ref}" \
  NEAT_APPS_SOURCE_REF="${apps_source_ref}" \
  NEAT_CORE_REPOSITORY="${core_repository}" \
  NEAT_APPS_REPOSITORY="${apps_repository}" \
  NEAT_RESOURCES_ROOT="${resources_root}" \
  NEAT_RESOURCES_OWNER="$(id -u):$(id -g)" \
  NEAT_CORE_STATUS_FILE="${status_file}" \
  SIMA_CLI_COMMAND="${tmpdir}/sima-cli" \
    "${INSTALLER}" > "${log_file}" 2>&1
}

run_installer bundled
grep -Fxq 'Neat Core = bundled' "${tmpdir}/status-bundled" || fail "bundled status missing"
grep -Fxq 'Neat Core: bundled' "${tmpdir}/log-bundled" || fail "bundled result was not logged"
test -f "${tmpdir}/resources-bundled/core-extra/installed.txt" || fail "Core artifact was not installed"
test ! -e "${tmpdir}/resources-bundled/core-extra/downloaded.deb" || fail "downloaded package was not cleaned"
test -f "${tmpdir}/resources-bundled/core-src/README" || fail "Core source was not installed"
test -f "${tmpdir}/resources-bundled/apps-src/README" || fail "Apps source was not installed"

run_installer incompatible
grep -Fxq 'Neat Core = not bundled' "${tmpdir}/status-incompatible" || fail "incompatible Core was not skipped"
grep -Fxq 'Neat Core Reason = requested Core artifact is incompatible with this SDK platform' "${tmpdir}/status-incompatible" || fail "incompatible reason missing"
grep -Fxq 'Neat Core: not bundled' "${tmpdir}/log-incompatible" || fail "incompatible result was not logged"
test ! -e "${tmpdir}/resources-incompatible/core-extra" || fail "partial incompatible resources remain"

run_installer unavailable
grep -Fxq 'Neat Core = not bundled' "${tmpdir}/status-unavailable" || fail "unavailable Core was not skipped"
grep -Fxq 'Neat Core Reason = requested Core artifact is not published yet' "${tmpdir}/status-unavailable" || fail "unavailable reason missing"
grep -Fxq 'Neat Core: not bundled' "${tmpdir}/log-unavailable" || fail "unavailable result was not logged"
test ! -e "${tmpdir}/resources-unavailable/core-extra" || fail "partial unavailable resources remain"

source_missing_root="${tmpdir}/resources-source-missing"
source_missing_status="${tmpdir}/status-source-missing"
source_missing_log="${tmpdir}/log-source-missing"
NEAT_CORE_TARGET=core@v0.4.0 \
NEAT_CORE_SOURCE_REASON='requested Core source ref v0.4.0 does not exist yet' \
NEAT_RESOURCES_ROOT="${source_missing_root}" \
NEAT_CORE_STATUS_FILE="${source_missing_status}" \
SIMA_CLI_COMMAND="${tmpdir}/sima-cli" \
  "${INSTALLER}" > "${source_missing_log}" 2>&1
grep -Fxq 'Neat Core = not bundled' "${source_missing_status}" || fail "missing source was not skipped"
grep -Fxq 'Neat Core Reason = requested Core source ref v0.4.0 does not exist yet' "${source_missing_status}" || fail "missing source reason missing"
grep -Fxq 'Neat Core: not bundled' "${source_missing_log}" || fail "missing source result was not logged"

skip_status="${tmpdir}/status-explicit-skip"
skip_log="${tmpdir}/log-explicit-skip"
NEAT_CORE_TARGET=core@v0.4.0 \
NEAT_CORE_STATUS_FILE="${skip_status}" \
  "${INSTALLER}" --skip 'pre-release platform SDK does not bundle Core' > "${skip_log}" 2>&1
grep -Fxq 'Neat Core Reason = pre-release platform SDK does not bundle Core' "${skip_status}" || fail "explicit skip reason missing"

set +e
run_installer fatal
fatal_status=$?
set -e
[[ "${fatal_status}" == "42" ]] || fail "unexpected Core failure did not remain fatal"
grep -Fq 'refusing to produce a partial SDK' "${tmpdir}/log-fatal" || fail "fatal failure message missing"

echo "Neat resource installation tests passed"
