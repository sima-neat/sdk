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

cat > "${tmpdir}/platform-release" <<'EOF'
SDK Profile = platform-cross
Platform Version = 2.1.3~pre4460
Neat Core = not bundled
EOF

platform_output="$(
  SDK_RELEASE_FILE="${tmpdir}/platform-release" \
  DEVKIT_NEAT_SYNC_REQUIRED=ON \
  DEVKIT_NEAT_SYNC_CACHE_DIR="${tmpdir}/missing-cache" \
    sync_neat_framework_to_devkit sima 192.0.2.1 22
)" || fail "platform profile should skip Core sync successfully"

grep -Fq 'Neat Core is not bundled in this platform SDK; skipping DevKit Core synchronization.' \
  <<< "${platform_output}" || fail "platform profile did not explain the Core sync skip"

cat > "${tmpdir}/full-release" <<'EOF'
SDK Profile = full
Platform Version = 2.1.2
Neat Core = bundled
EOF

full_output="$(
  SDK_RELEASE_FILE="${tmpdir}/full-release" \
  DEVKIT_NEAT_SYNC=OFF \
    sync_neat_framework_to_devkit sima 192.0.2.1 22
)" || fail "full profile with sync disabled should succeed"

grep -Fq 'Neat framework DevKit sync disabled' <<< "${full_output}" || \
  fail "full profile no longer follows the existing sync switch"

echo "devkit platform profile tests passed"
