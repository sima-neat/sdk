#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
DEVKIT_SH_FUNCTIONS_ONLY=1 source "${ROOT_DIR}/scripts/devkit.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
sdk_bundles_neat_core() { return 0; }
dpkg-deb() {
  case "${*: -1}" in
    Package) echo "${TEST_PACKAGE}" ;;
    Version) echo 0.6.0 ;;
    *) return 1 ;;
  esac
}
scp() {
  local file
  touch "${TMP_DIR}/copied"
  for file in "$@"; do
    [[ ! -f "${file}" ]] || cp "${file}" "${TMP_DIR}/remote/"
  done
}
ssh() {
  case "$*" in
    *"bash -s --"*)
      cat >/dev/null
      if [[ -f "${TMP_DIR}/installed" ]]; then
        printf 'deb|%s|0.6.0\nwheel|pyneat|0.6.0\n' "${TEST_PACKAGE}"
      fi
      ;;
    *install_neat_framework.sh*)
      if [[ "${TEST_PACKAGE}" == simaai-scheduler ]]; then
        local file
        for file in scheduler_platform_admission.py install_sentinel.sh neat-install-manifest.txt resolved-deps-manifest.json; do
          [[ -f "${TMP_DIR}/remote/${file}" ]] || return 1
        done
      fi
      touch "${TMP_DIR}/installed"
      ;;
  esac
}

export DEVKIT_NEAT_SYNC_CACHE_DIR="${TMP_DIR}/cache"
export DEVKIT_NEAT_SYNC_REQUIRED=ON
TEST_PACKAGE=simaai-scheduler
mkdir -p "${TMP_DIR}/cache" "${TMP_DIR}/remote"
for file in scheduler.deb pyneat-0.6.0-py3-none-any.whl manifest.json install_neat_framework.sh \
    scheduler_platform_admission.py install_sentinel.sh neat-install-manifest.txt resolved-deps-manifest.json; do
  echo fixture > "${TMP_DIR}/cache/${file}"
done
sync_neat_framework_to_devkit sima 192.0.2.1 22 || fail "complete Scheduler bundle did not sync"
[[ -f "${TMP_DIR}/installed" ]] || fail "remote install was not executed"

rm -f "${TMP_DIR}/installed" "${TMP_DIR}/copied" "${TMP_DIR}/cache/scheduler_platform_admission.py"
if sync_neat_framework_to_devkit sima 192.0.2.1 22 >"${TMP_DIR}/missing.log" 2>&1; then
  fail "missing Scheduler delegate was accepted"
fi
grep -Fq 'Scheduler Platform admission delegate missing from SDK cache' "${TMP_DIR}/missing.log" || \
  fail "missing delegate did not produce a useful diagnostic"
[[ ! -f "${TMP_DIR}/copied" ]] || fail "incomplete bundle was copied to the board"

# Pre-Scheduler SDK caches retain their existing install path.
TEST_PACKAGE=sima-neat
rm -f "${TMP_DIR}/cache/install_sentinel.sh" "${TMP_DIR}/cache/neat-install-manifest.txt" \
  "${TMP_DIR}/cache/resolved-deps-manifest.json"
sync_neat_framework_to_devkit sima 192.0.2.1 22 || fail "legacy bundle no longer syncs"
echo "devkit Neat bundle sync tests passed"
