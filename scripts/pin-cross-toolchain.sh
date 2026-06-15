#!/usr/bin/env bash

set -euo pipefail

pin_tool() {
  local tool="$1"
  local versioned="/usr/bin/${tool}-12"
  local generic="/usr/bin/${tool}"

  if [[ ! -x "${versioned}" ]]; then
    echo "Expected GCC 12 cross tool is missing: ${versioned}" >&2
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
  if [[ -x "/usr/bin/${tool}-12" ]]; then
    pin_tool "${tool}"
  fi
done

aarch64-linux-gnu-gcc --version | head -n 1
aarch64-linux-gnu-g++ --version | head -n 1
