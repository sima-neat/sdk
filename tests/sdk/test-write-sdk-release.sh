#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRITER="${ROOT_DIR}/scripts/write-sdk-release.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

SDK_RELEASE_FILE="${tmpdir}/platform-release" \
SDK_RELEASE_REF=develop-abcdef1 \
BASE_SDK_VERSION=3.0.0~pre4460 \
SDK_APT_CHANNEL=pre-release \
REQUESTED_PRE_RELEASE_BASE=3.0.0 \
SDK_GIT_BRANCH=develop \
SDK_GIT_HASH=abcdef1 \
  "${WRITER}"

grep -Fxq 'SDK Profile = platform-cross' "${tmpdir}/platform-release" || fail "profile missing"
grep -Fxq 'Platform Version = 3.0.0~pre4460' "${tmpdir}/platform-release" || fail "exact platform version missing"
grep -Fxq 'Platform Base = 3.0.0' "${tmpdir}/platform-release" || fail "platform base missing"
grep -Fxq 'Platform Channel = pre-release' "${tmpdir}/platform-release" || fail "channel missing"
grep -Fxq 'Requested Pre-release Base = 3.0.0' "${tmpdir}/platform-release" || fail "requested selector missing"
grep -Fxq 'Neat Core = not bundled' "${tmpdir}/platform-release" || fail "Core status missing"

SDK_RELEASE_FILE="${tmpdir}/stable-release" \
SDK_RELEASE_REF=v3.0.0 \
BASE_SDK_VERSION=3.0.0 \
SDK_APT_CHANNEL=release \
  "${WRITER}"

grep -Fxq 'Neat Core = bundled' "${tmpdir}/stable-release" || fail "stable Core status changed"
grep -Fxq 'SDK Version = 3.0.0_Palette_SDK_neat_v3.0.0' "${tmpdir}/stable-release" || fail "tag release format changed"

cat > "${tmpdir}/core-status" <<'EOF'
Neat Core = not bundled
Neat Core Requested = core@v0.4.0
Neat Core Reason = requested Core artifact is not published yet
EOF

SDK_RELEASE_FILE="${tmpdir}/stable-without-core-release" \
NEAT_CORE_STATUS_FILE="${tmpdir}/core-status" \
SDK_RELEASE_REF=develop-abcdef1 \
BASE_SDK_VERSION=3.0.0 \
SDK_APT_CHANNEL=release \
  "${WRITER}"

grep -Fxq 'SDK Profile = platform-cross' "${tmpdir}/stable-without-core-release" || fail "Core-less stable SDK profile was incorrect"
grep -Fxq 'Platform Channel = release' "${tmpdir}/stable-without-core-release" || fail "Core-less stable SDK lost its release channel"
grep -Fxq 'Neat Core = not bundled' "${tmpdir}/stable-without-core-release" || fail "Core-less stable SDK status was incorrect"
grep -Fxq 'Neat Core Requested = core@v0.4.0' "${tmpdir}/stable-without-core-release" || fail "requested Core target missing"
grep -Fxq 'Neat Core Reason = requested Core artifact is not published yet' "${tmpdir}/stable-without-core-release" || fail "Core skip reason missing"

SDK_RELEASE_FILE="${tmpdir}/daily-release" \
NEAT_CORE_STATUS_FILE="${tmpdir}/missing" \
SDK_APT_CHANNEL=daily \
BASE_SDK_VERSION=3.0.0~git202609090513.9e68a68-1218 \
  "${WRITER}"
grep -Fxq 'Platform Base = 3.0.0' "${tmpdir}/daily-release" || fail "daily base missing"
grep -Fxq 'Platform Repository = https://debian.neat.sima.ai/daily' "${tmpdir}/daily-release" || fail "daily repository missing"
grep -Fxq 'SDK Profile = platform-cross' "${tmpdir}/daily-release" || fail "daily profile incorrect"
grep -Fxq 'Neat Core = not bundled' "${tmpdir}/daily-release" || fail "daily unexpectedly bundles Core"

echo "sdk release metadata tests passed"

SDK_RELEASE_FILE="${tmpdir}/defaults" NEAT_CORE_STATUS_FILE="${tmpdir}/missing" \
  env -u BASE_SDK_VERSION -u SDK_APT_CHANNEL "${WRITER}"
grep -Fxq 'Platform Base = 3.0.0' "${tmpdir}/defaults"
grep -Fxq 'Platform Channel = daily' "${tmpdir}/defaults"
grep -Fxq 'Neat Core = not bundled' "${tmpdir}/defaults"
