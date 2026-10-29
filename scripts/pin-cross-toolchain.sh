#!/usr/bin/env bash

set -euo pipefail

toolchain_version="$(cat /usr/local/share/sima-sdk/cross-toolchain-version)"
if [[ ! "${toolchain_version}" =~ ^[0-9]+$ ]]; then
  echo "Invalid cross compiler major version: ${toolchain_version}" >&2
  exit 1
fi
if [[ "${SDK_APT_CHANNEL:-daily}" == daily && "${toolchain_version}" -lt 14 ]]; then
  echo "The daily SDK requires GCC 14 or newer; use SDK_CROSS_TOOLCHAIN_IMAGE=debian:trixie." >&2
  exit 1
fi

pin_tool() {
  local tool="$1"
  local versioned="/usr/bin/${tool}-${toolchain_version}"
  local generic="/usr/bin/${tool}"

  if [[ ! -x "${versioned}" ]]; then
    echo "Expected GCC ${toolchain_version} cross tool is missing: ${versioned}" >&2
    return 1
  fi

  if ! dpkg-divert --list "${generic}" | grep -q .; then
    dpkg-divert --local --rename --add "${generic}"
  fi

  ln -sfn "$(basename "${versioned}")" "${generic}"
}

pin_tool aarch64-linux-gnu-gcc
pin_tool aarch64-linux-gnu-g++

for tool in aarch64-linux-gnu-gcc-ar aarch64-linux-gnu-gcc-nm aarch64-linux-gnu-gcc-ranlib; do
  if [[ -x "/usr/bin/${tool}-${toolchain_version}" ]]; then
    pin_tool "${tool}"
  fi
done

aarch64-linux-gnu-gcc --version | head -n 1
aarch64-linux-gnu-g++ --version | head -n 1
