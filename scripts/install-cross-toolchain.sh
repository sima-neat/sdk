#!/usr/bin/env bash

set -euo pipefail

apt-get update --allow-releaseinfo-change

host_arch="$(dpkg --print-architecture)"
case "${host_arch}" in
  amd64)
    toolchain_packages=(gcc-aarch64-linux-gnu g++-aarch64-linux-gnu)
    multiarch=x86_64-linux-gnu
    ;;
  arm64)
    toolchain_packages=(gcc g++ binutils)
    multiarch=aarch64-linux-gnu
    ;;
  *)
    echo "Unsupported SDK host architecture for aarch64 toolchain: ${host_arch}" >&2
    exit 1
    ;;
esac

apt-get install -y --no-install-recommends "${toolchain_packages[@]}"

mkdir -p /opt/cross-toolchain/usr/bin \
         /opt/cross-toolchain/usr/lib \
         "/opt/cross-toolchain/usr/lib/${multiarch}"

cp -a /usr/bin/aarch64-linux-gnu-* /opt/cross-toolchain/usr/bin/

if [[ -d /usr/lib/gcc-cross/aarch64-linux-gnu ]]; then
  mkdir -p /opt/cross-toolchain/usr/lib/gcc-cross
  cp -a /usr/lib/gcc-cross/aarch64-linux-gnu /opt/cross-toolchain/usr/lib/gcc-cross/
fi

if [[ -d /usr/lib/gcc/aarch64-linux-gnu ]]; then
  mkdir -p /opt/cross-toolchain/usr/lib/gcc
  cp -a /usr/lib/gcc/aarch64-linux-gnu /opt/cross-toolchain/usr/lib/gcc/
fi

if [[ -d /usr/aarch64-linux-gnu ]]; then
  cp -a /usr/aarch64-linux-gnu /opt/cross-toolchain/usr/
fi

if [[ "${host_arch}" == "arm64" ]]; then
  cp -a /usr/bin/gcc /usr/bin/gcc-* \
        /usr/bin/g++ /usr/bin/g++-* \
        /usr/bin/cpp /usr/bin/cpp-* \
        /opt/cross-toolchain/usr/bin/
  ln -sf gcc /opt/cross-toolchain/usr/bin/aarch64-linux-gnu-gcc
  ln -sf g++ /opt/cross-toolchain/usr/bin/aarch64-linux-gnu-g++
  ln -sf cpp /opt/cross-toolchain/usr/bin/aarch64-linux-gnu-cpp
  ln -sf aarch64-linux-gnu-as /opt/cross-toolchain/usr/bin/as
  ln -sf aarch64-linux-gnu-ld /opt/cross-toolchain/usr/bin/ld
fi

for lib in \
  "/usr/lib/${multiarch}"/libbfd*.so* \
  "/usr/lib/${multiarch}"/libctf*.so* \
  "/usr/lib/${multiarch}"/libopcodes*.so* \
  "/usr/lib/${multiarch}"/libsframe*.so*; do
  if [[ -e "${lib}" ]]; then
    cp -a "${lib}" "/opt/cross-toolchain/usr/lib/${multiarch}/"
  fi
done

apt-get clean
rm -rf /var/lib/apt/lists/*
