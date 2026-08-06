#!/usr/bin/env bash

set -euo pipefail

pre_release_base="${PRE_RELEASE_BASE:-}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
manifest_path="${SDK_DEPS_MANIFEST:-${script_dir}/../deps/manifest.json}"
stable_base_sdk_version="${STABLE_BASE_SDK_VERSION:-}"
github_ref_type="${GITHUB_REF_TYPE:-branch}"
github_ref_name="${GITHUB_REF_NAME:-local}"
packages_url="${PRE_RELEASE_PACKAGES_URL:-https://debian.neat.sima.ai/pre-release/dists/bookworm/non-free/binary-arm64/Packages.gz}"
anchor_package="${PRE_RELEASE_ANCHOR_PACKAGE:-simaai-palette-modalix}"
dpkg_command="${DPKG_COMMAND:-dpkg}"

if [[ -z "${stable_base_sdk_version}" ]]; then
  command -v python3 >/dev/null 2>&1 || {
    echo "resolve-platform-config: python3 is required to read ${manifest_path}" >&2
    exit 1
  }
  stable_base_sdk_version="$(
    python3 - "${manifest_path}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as manifest_file:
    value = json.load(manifest_file).get("platform-version", "")
if not value:
    raise SystemExit("deps manifest does not define platform-version")
print(value)
PY
  )"
fi

die() {
  echo "resolve-platform-config: $*" >&2
  exit 1
}

emit() {
  local channel="$1"
  local requested="$2"
  local resolved="$3"

  printf 'sdk_apt_channel=%s\n' "${channel}"
  printf 'requested_pre_release_base=%s\n' "${requested}"
  printf 'base_sdk_version=%s\n' "${resolved}"
}

is_protected_ref() {
  [[ "${github_ref_type}" == "tag" || \
     "${github_ref_name}" == "main" || \
     "${github_ref_name}" == release-* ]]
}

if [[ -z "${pre_release_base}" ]]; then
  emit release "" "${stable_base_sdk_version}"
  exit 0
fi

case "${pre_release_base}" in
  *[!0-9.~a-zA-Z-]*)
    die "invalid PRE_RELEASE_BASE: ${pre_release_base}"
    ;;
esac

if [[ "${pre_release_base}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  selector_type="floating"
  platform_base="${pre_release_base}"
elif [[ "${pre_release_base}" =~ ^([0-9]+\.[0-9]+\.[0-9]+)~pre[0-9]+$ ]]; then
  selector_type="pinned"
  platform_base="${BASH_REMATCH[1]}"
else
  die "PRE_RELEASE_BASE must be X.Y.Z or X.Y.Z~preN: ${pre_release_base}"
fi

if [[ "${selector_type}" == "floating" ]] && is_protected_ref; then
  die "floating PRE_RELEASE_BASE=${pre_release_base} is not allowed for ${github_ref_type} ${github_ref_name}; use the stable channel or pin X.Y.Z~preN"
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
packages_file="${tmpdir}/Packages"

if [[ -n "${PRE_RELEASE_PACKAGES_FILE:-}" ]]; then
  [[ -r "${PRE_RELEASE_PACKAGES_FILE}" ]] || die "Packages fixture is not readable: ${PRE_RELEASE_PACKAGES_FILE}"
  cp "${PRE_RELEASE_PACKAGES_FILE}" "${packages_file}"
else
  command -v curl >/dev/null 2>&1 || die "curl is required to query the pre-release mirror"
  command -v gzip >/dev/null 2>&1 || die "gzip is required to read the pre-release package index"
  curl -fsSL --retry 4 --retry-all-errors "${packages_url}" | gzip -dc > "${packages_file}"
fi

resolved=""
candidate_count=0
use_dpkg=0
if [[ "${selector_type}" == "floating" ]] && command -v "${dpkg_command}" >/dev/null 2>&1; then
  use_dpkg=1
fi
while IFS= read -r candidate; do
  candidate_count=$((candidate_count + 1))
  if [[ "${selector_type}" == "pinned" ]]; then
    if [[ "${candidate}" == "${pre_release_base}" ]]; then
      resolved="${candidate}"
    fi
  else
    [[ "${candidate}" == "${platform_base}"~pre* ]] || continue
    candidate_is_newer=0
    if [[ -z "${resolved}" ]]; then
      candidate_is_newer=1
    elif [[ "${use_dpkg}" == "1" ]]; then
      if "${dpkg_command}" --compare-versions "${candidate}" gt "${resolved}"; then
        candidate_is_newer=1
      fi
    elif (( 10#${candidate##*~pre} > 10#${resolved##*~pre} )); then
      # All accepted floating candidates share X.Y.Z~preN. Numeric N ordering
      # is equivalent to Debian ordering for this deliberately narrow format.
      candidate_is_newer=1
    fi
    if [[ "${candidate_is_newer}" == "1" ]]; then
      resolved="${candidate}"
    fi
  fi
done < <(
  awk -v package="${anchor_package}" '
    $1 == "Package:" { current_package = $2 }
    $1 == "Version:" && current_package == package { print $2 }
  ' "${packages_file}" | awk '!seen[$0]++'
)

[[ "${candidate_count}" -gt 0 ]] || die "no versions found for anchor package ${anchor_package}"

if [[ "${selector_type}" == "pinned" ]]; then
  [[ -n "${resolved}" ]] || die "pinned version ${pre_release_base} is not present for ${anchor_package}"
else
  [[ -n "${resolved}" ]] || die "no ${platform_base}~pre* version found for ${anchor_package}"
fi

emit pre-release "${pre_release_base}" "${resolved}"
