#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER="${ROOT_DIR}/scripts/devkit-sync-rsync.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

grep -Fq '/media/nvme/workspace-rsync' "${HELPER}" || fail "rsync helper should use /media/nvme for NVMe workspace storage"
if grep -Fq '/nvme/media/workspace-rsync' "${HELPER}"; then
  fail "rsync helper should not use the old /nvme/media workspace path"
fi

assert_contains() {
  local haystack="$1"
  local needle="$2"
  grep -Fxq "${needle}" <<< "${haystack}" || fail "expected exclude '${needle}'"
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if grep -Fxq "${needle}" <<< "${haystack}"; then
    fail "unexpected exclude '${needle}'"
  fi
}

mapped="$("${HELPER}" map-path --local-root /workspace --remote-root /workspace-rsync --path /workspace/apps/demo.py)"
[[ "${mapped}" == "/workspace-rsync/apps/demo.py" ]] || fail "unexpected mapped path: ${mapped}"

unchanged="$("${HELPER}" map-path --local-root /workspace --remote-root /workspace-rsync --path /tmp/demo.py)"
[[ "${unchanged}" == "/tmp/demo.py" ]] || fail "unexpected unchanged path: ${unchanged}"

scope="$("${HELPER}" scope-for-path --local-root /workspace --path /workspace/apps/examples/demo.py)"
[[ "${scope}" == "/workspace/apps" ]] || fail "unexpected scope: ${scope}"

top_level_scope="$("${HELPER}" scope-for-path --local-root /workspace --path /workspace/apps)"
[[ "${top_level_scope}" == "/workspace/apps" ]] || fail "unexpected top-level scope: ${top_level_scope}"

root_scope="$("${HELPER}" scope-for-path --local-root /workspace --path /workspace)"
[[ "${root_scope}" == "/workspace" ]] || fail "unexpected root scope: ${root_scope}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
mkdir -p "${tmpdir}/workspace"
printf 'project-cache/\n' > "${tmpdir}/workspace/.devkit-rsync-exclude"
printf 'external-cache/\n' > "${tmpdir}/external-excludes"

excludes="$(
  DEVKIT_RSYNC_EXCLUDES_FILE="${tmpdir}/external-excludes" \
  DEVKIT_RSYNC_EXTRA_EXCLUDES=$'scratch/\ntmp-artifacts/' \
    "${HELPER}" print-excludes --local "${tmpdir}/workspace"
)"

assert_contains "${excludes}" ".git/"
assert_contains "${excludes}" "__pycache__/"
assert_contains "${excludes}" "project-cache/"
assert_contains "${excludes}" "external-cache/"
assert_contains "${excludes}" "scratch/"
assert_contains "${excludes}" "tmp-artifacts/"

assert_not_contains "${excludes}" "dist/"
assert_not_contains "${excludes}" "build/"
assert_not_contains "${excludes}" "build-*/"
assert_not_contains "${excludes}" "cmake-build-*/"
assert_not_contains "${excludes}" "CMakeFiles/"
assert_not_contains "${excludes}" "CMakeCache.txt"
assert_not_contains "${excludes}" "*.o"
assert_not_contains "${excludes}" "*.a"
assert_not_contains "${excludes}" "*.so"
assert_not_contains "${excludes}" "*.dylib"

echo "devkit rsync helper tests passed"
