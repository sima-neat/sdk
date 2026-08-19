#!/usr/bin/env bash

set -euo pipefail

output="${SDK_RELEASE_FILE:-/etc/sdk-release}"
sdk_release_ref="${SDK_RELEASE_REF:-unknown-nogit}"
platform_version="${BASE_SDK_VERSION:-2.1.3}"
platform_base="${platform_version%%~pre*}"
platform_channel="${SDK_APT_CHANNEL:-release}"
requested_pre_release_base="${REQUESTED_PRE_RELEASE_BASE:-none}"
sdk_git_branch="${SDK_GIT_BRANCH:-unknown}"
sdk_git_hash="${SDK_GIT_HASH:-nogit}"

if [[ -z "${requested_pre_release_base}" ]]; then
  requested_pre_release_base="none"
fi

case "${platform_channel}" in
  release)
    sdk_profile="full"
    platform_repository="https://repo.sima.ai/elxr/deb/release"
    core_status="bundled"
    ;;
  pre-release)
    sdk_profile="platform-cross"
    platform_repository="https://debian.neat.sima.ai/pre-release"
    core_status="not bundled"
    ;;
  *)
    echo "Unsupported SDK_APT_CHANNEL: ${platform_channel}" >&2
    exit 1
    ;;
esac

if [[ "${sdk_release_ref}" =~ ^v[0-9]+[.][0-9]+[.][0-9]+ ]]; then
  sdk_version="${platform_version}_Palette_SDK_neat_${sdk_release_ref}"
  elxr_version="${platform_version}_release_neat_${sdk_release_ref}"
else
  sdk_version="${platform_version}_Palette_SDK_neat_${sdk_git_branch}_${sdk_git_hash}"
  elxr_version="${platform_version}_release_neat_${sdk_git_branch}_${sdk_git_hash}"
fi

cat > "${output}" <<EOF
SDK Release = ${sdk_release_ref}
SDK Profile = ${sdk_profile}
Platform Version = ${platform_version}
Platform Base = ${platform_base}
Platform Channel = ${platform_channel}
Platform Repository = ${platform_repository}
Requested Pre-release Base = ${requested_pre_release_base}
Neat Core = ${core_status}
SDK Version = ${sdk_version}
eLXr Version = ${elxr_version}
EOF
