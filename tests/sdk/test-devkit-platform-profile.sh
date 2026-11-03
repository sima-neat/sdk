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

unset DEVKIT_HOST_NFS_AVAILABLE
devkit_host_nfs_available || fail "host NFS should default to available for older sima-cli versions"

if DEVKIT_HOST_NFS_AVAILABLE=0 devkit_host_nfs_available; then
  fail "host NFS marker 0 should skip NFS setup"
fi

if DEVKIT_HOST_NFS_AVAILABLE=false devkit_host_nfs_available; then
  fail "host NFS marker false should skip NFS setup"
fi

DEVKIT_HOST_NFS_AVAILABLE=1 devkit_host_nfs_available || \
  fail "host NFS marker 1 should allow NFS setup"

if DEVKIT_HOST_NFS_AVAILABLE=1 devkit_host_export_info_ready "" ""; then
  fail "available host NFS should still require host export details"
fi

DEVKIT_HOST_NFS_AVAILABLE=0 devkit_host_export_info_ready "" "" || \
  fail "rsync-only setup should not require host NFS export details"

grep -Fq '__devkit_persist_export DEVKIT_HOST_NFS_AVAILABLE' "${ROOT_DIR}/scripts/devkit.sh" || \
  fail "host NFS availability marker should persist into future container shells"

cat > "${tmpdir}/platform-release" <<'EOF'
SDK Profile = platform-cross
Platform Version = 3.0.0~pre4460
Platform Base = 3.0.0
Neat Core = not bundled
EOF

[[ "$(sdk_platform_version_from_release_file "${tmpdir}/platform-release")" == "3.0.0" ]] || \
  fail "platform-cross profile did not use Platform Base for DevKit compatibility"

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
Platform Version = 3.0.0~pre2372
Platform Base = 3.0.0
Neat Core = bundled
EOF

[[ "$(sdk_platform_version_from_release_file "${tmpdir}/full-release")" == "3.0.0" ]] || \
  fail "full pre-release profile did not use Platform Base for DevKit compatibility"

cat > "${tmpdir}/full-official-release" <<'EOF'
SDK Profile = full
Platform Version = 3.0.0
Platform Base = 3.0.0
Neat Core = bundled
EOF
[[ "$(sdk_platform_version_from_release_file "${tmpdir}/full-official-release")" == "3.0.0" ]] || \
  fail "full official release did not use Platform Base for DevKit compatibility"

cat > "${tmpdir}/full-daily-release" <<'EOF'
SDK Profile = full
Platform Version = 3.0.0~git202610270000.abcdef0-2413
Platform Base = 3.0.0
Neat Core = bundled
EOF
[[ "$(sdk_platform_version_from_release_file "${tmpdir}/full-daily-release")" == "3.0.0" ]] || \
  fail "full daily profile did not use Platform Base for DevKit compatibility"

# Older images without Platform Base retain their existing fallback behavior.
cat > "${tmpdir}/legacy-full-release" <<'EOF'
SDK Profile = full
Platform Version = 2.1.2
Neat Core = bundled
EOF
[[ "$(sdk_platform_version_from_release_file "${tmpdir}/legacy-full-release")" == "2.1.2" ]] || \
  fail "legacy full profile did not fall back to Platform Version"

cat > "${tmpdir}/legacy-elxr-release" <<'EOF'
eLXr Version = 2.1.2_release_neat_main_abcdef0
EOF
[[ "$(sdk_platform_version_from_release_file "${tmpdir}/legacy-elxr-release")" == "2.1.2" ]] || \
  fail "legacy profile did not retain its eLXr Version fallback"

full_output="$(
  SDK_RELEASE_FILE="${tmpdir}/full-release" \
  DEVKIT_NEAT_SYNC=OFF \
    sync_neat_framework_to_devkit sima 192.0.2.1 22
)" || fail "full profile with sync disabled should succeed"

grep -Fq 'Neat framework DevKit sync disabled' <<< "${full_output}" || \
  fail "full profile no longer follows the existing sync switch"

echo "devkit platform profile tests passed"
