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

# GCC 14 moved compiler executables such as cc1plus and lto1 to libexec.
for directory in /usr/libexec/gcc /usr/libexec/gcc-cross; do
  if [[ -d "${directory}" ]]; then
    mkdir -p /opt/cross-toolchain/usr/libexec
    cp -a "${directory}" /opt/cross-toolchain/usr/libexec/
  fi
done

if [[ -d /usr/aarch64-linux-gnu ]]; then
  cp -a /usr/aarch64-linux-gnu /opt/cross-toolchain/usr/
fi

if [[ "${host_arch}" == "arm64" ]]; then
  mkdir -p /opt/cross-toolchain/usr/include \
           /opt/cross-toolchain/usr/include/aarch64-linux-gnu
  if [[ -d /usr/include/c++ ]]; then
    cp -a /usr/include/c++ /opt/cross-toolchain/usr/include/
  fi
  if [[ -d /usr/include/aarch64-linux-gnu/c++ ]]; then
    cp -a /usr/include/aarch64-linux-gnu/c++ /opt/cross-toolchain/usr/include/aarch64-linux-gnu/
  fi

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

mkdir -p /opt/cross-toolchain/usr/local/share/sima-sdk
aarch64-linux-gnu-gcc -dumpversion > /opt/cross-toolchain/usr/local/share/sima-sdk/cross-toolchain-version

apt-get clean
rm -rf /var/lib/apt/lists/*
