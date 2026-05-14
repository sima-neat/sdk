#!/usr/bin/env bash

set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") EXPECTED_VERSION DEB_DIR [SYSROOT]" >&2
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 2
fi

expected_version="$1"
deb_dir="$2"
sysroot="${3:-}"
patterns_file="${PLATFORM_PACKAGE_PATTERNS_FILE:-/usr/local/share/sima-sdk/platform-package-patterns.txt}"

if [[ ! -d "${deb_dir}" ]]; then
  echo "Package download directory not found: ${deb_dir}" >&2
  exit 1
fi

platform_package_patterns=(
  simaai-*
  appcomplex
  a65apps
  evtransforms
  inferencetools
  vdpcli
  mpktools
  vdpspy
  vdp-llm-libs
  swsoc-*
  smifb-*
  cvu-sw*
  m4-mla-*
  troot-*
  libsynopsys
  atf-*
  optee-*
  oot-dtbo-*
)

if [[ -f "${patterns_file}" ]]; then
  platform_package_patterns=()
  while IFS= read -r line; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    if [[ -n "${line}" ]]; then
      platform_package_patterns+=("${line}")
    fi
  done < "${patterns_file}"
fi

is_platform_package() {
  local base="${1%%:*}"
  local pattern
  for pattern in "${platform_package_patterns[@]}"; do
    if [[ "${base}" == ${pattern} ]]; then
      return 0
    fi
  done
  return 1
}

errors=0
deb_count=0

while IFS= read -r -d '' deb; do
  deb_count=$((deb_count + 1))
  pkg="$(dpkg-deb -f "${deb}" Package)"
  ver="$(dpkg-deb -f "${deb}" Version)"

  if is_platform_package "${pkg}" && [[ "${ver}" != "${expected_version}" ]]; then
    echo "Unexpected ${pkg} version ${ver}; expected ${expected_version} (${deb})" >&2
    errors=$((errors + 1))
  fi
done < <(find "${deb_dir}" -type f -name '*.deb' -print0 | sort -z)

if [[ "${deb_count}" -eq 0 ]]; then
  echo "No .deb files found in ${deb_dir}" >&2
  errors=$((errors + 1))
fi

if [[ -n "${sysroot}" ]]; then
  dlpack_header="${sysroot}/usr/include/dlpack/dlpack.h"
  if [[ -f "${dlpack_header}" ]]; then
    for symbol in kDLOneAPI kDLWebGPU kDLHexagon; do
      if ! grep -q "${symbol}" "${dlpack_header}"; then
        echo "${dlpack_header} is missing ${symbol}; TVM/DLPack headers are mismatched" >&2
        errors=$((errors + 1))
      fi
    done
  fi
fi

if [[ "${errors}" -ne 0 ]]; then
  exit 1
fi

echo "Validated ${deb_count} downloaded sysroot packages for platform version ${expected_version}"
