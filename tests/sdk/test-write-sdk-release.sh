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
BASE_SDK_VERSION=2.1.3~pre4460 \
SDK_APT_CHANNEL=pre-release \
REQUESTED_PRE_RELEASE_BASE=2.1.3 \
SDK_GIT_BRANCH=develop \
SDK_GIT_HASH=abcdef1 \
  "${WRITER}"

grep -Fxq 'SDK Profile = platform-cross' "${tmpdir}/platform-release" || fail "profile missing"
grep -Fxq 'Platform Version = 2.1.3~pre4460' "${tmpdir}/platform-release" || fail "exact platform version missing"
grep -Fxq 'Platform Base = 2.1.3' "${tmpdir}/platform-release" || fail "platform base missing"
grep -Fxq 'Platform Channel = pre-release' "${tmpdir}/platform-release" || fail "channel missing"
grep -Fxq 'Requested Pre-release Base = 2.1.3' "${tmpdir}/platform-release" || fail "requested selector missing"
grep -Fxq 'Neat Core = not bundled' "${tmpdir}/platform-release" || fail "Core status missing"

SDK_RELEASE_FILE="${tmpdir}/stable-release" \
SDK_RELEASE_REF=v2.1.2 \
BASE_SDK_VERSION=2.1.2 \
SDK_APT_CHANNEL=release \
  "${WRITER}"

grep -Fxq 'Neat Core = bundled' "${tmpdir}/stable-release" || fail "stable Core status changed"
grep -Fxq 'SDK Version = 2.1.2_Palette_SDK_neat_v2.1.2' "${tmpdir}/stable-release" || fail "tag release format changed"

echo "sdk release metadata tests passed"
