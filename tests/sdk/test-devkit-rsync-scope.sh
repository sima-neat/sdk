#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEVKIT_SH="${ROOT_DIR}/scripts/devkit.sh"
HELPER="${ROOT_DIR}/scripts/devkit-sync-rsync.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Load only the sourceable scope helper from devkit.sh. Sourcing the full file
# would attempt to configure a live DevKit connection.
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
sed -n '/^devkit-local-sync-scope()/,/^}/p' "${DEVKIT_SH}" > "${tmpdir}/devkit-scope.sh"
# shellcheck source=/dev/null
source "${tmpdir}/devkit-scope.sh"

assert_scope() {
  local path="$1"
  local expected="$2"
  local actual

  actual="$(DEVKIT_SYNC_LOCAL_ROOT=/workspace devkit-local-sync-scope "${path}")"
  [[ "${actual}" == "${expected}" ]] || fail "unexpected devkit.sh scope for ${path}: ${actual}"

  if [[ "${path}" == /workspace* ]]; then
    local helper_actual
    helper_actual="$("${HELPER}" scope-for-path --local-root /workspace --path "${path}")"
    [[ "${helper_actual}" == "${expected}" ]] || fail "unexpected helper scope for ${path}: ${helper_actual}"
  fi
}

assert_scope "/workspace" "/workspace"
assert_scope "/workspace/apps" "/workspace/apps"
assert_scope "/workspace/apps/examples/demo.py" "/workspace/apps"
assert_scope "/workspace/core" "/workspace/core"
assert_scope "/tmp/demo.py" "/tmp/demo.py"

echo "devkit rsync scope tests passed"
