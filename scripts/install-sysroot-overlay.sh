#!/usr/bin/env bash

set -euo pipefail

SYSROOT="${1:-/opt/toolchain/aarch64/modalix}"
LIBDIR="${SYSROOT}/usr/lib/aarch64-linux-gnu"
LINUX_LIBC_DEV_VERSION="${SDK_SYSROOT_LINUX_LIBC_DEV_VERSION:-6.1.22-modalix-827}"

if [[ $# -lt 2 ]]; then
  echo "Usage: $(basename "$0") SYSROOT package[:arch] [package[:arch] ...]" >&2
  exit 1
fi

shift
PACKAGES=("$@")
TARGET_ARCHES=()

for pkg in "${PACKAGES[@]}"; do
  if [[ "${pkg}" == *:* ]]; then
    arch="${pkg##*:}"
    arch="${arch%%=*}"
    if [[ " ${TARGET_ARCHES[*]} " != *" ${arch} "* ]]; then
      TARGET_ARCHES+=("${arch}")
    fi
  fi
done

if [[ ${#TARGET_ARCHES[@]} -eq 0 ]]; then
  TARGET_ARCHES=("$(dpkg --print-architecture)")
fi

export DEBIAN_FRONTEND=noninteractive

workdir="$(mktemp -d)"
cleanup() {
  rm -rf "${workdir}"
}
trap cleanup EXIT

mkdir -p "${SYSROOT}" "${LIBDIR}" "${workdir}/archives" "${workdir}/linux-libc-dev"

echo "Downloading sysroot overlay packages into ${SYSROOT}"
printf '  %s\n' "${PACKAGES[@]}"

native_arch="$(dpkg --print-architecture)"
if [[ " ${TARGET_ARCHES[*]} " != *" ${native_arch} "* ]] &&
   dpkg-query -W -f='${Status}' linux-libc-dev 2>/dev/null | grep -q "install ok installed"; then
  native_linux_libc_version="$(dpkg-query -W -f='${Version}' linux-libc-dev)"
  for arch in "${TARGET_ARCHES[@]}"; do
    PACKAGES+=("linux-libc-dev:${arch}=${native_linux_libc_version}")
  done
fi

apt-get update --allow-releaseinfo-change
apt-get install -y --download-only --no-install-recommends \
  -o Dir::Cache::archives="${workdir}/archives" \
  "${PACKAGES[@]}"

find "${workdir}/archives" -maxdepth 1 -type f -name '*.deb' -print0 \
  | while IFS= read -r -d '' deb; do
      deb_arch="$(dpkg-deb -f "${deb}" Architecture)"
      if [[ "${deb_arch}" != "all" && " ${TARGET_ARCHES[*]} " != *" ${deb_arch} "* ]]; then
        echo "Skipping $(basename "${deb}") for architecture ${deb_arch}"
        continue
      fi
      echo "Extracting $(basename "${deb}")"
      dpkg-deb -x "${deb}" "${SYSROOT}"
    done

for arch in "${TARGET_ARCHES[@]}"; do
  if [[ "${arch}" != "arm64" ]]; then
    continue
  fi

  echo "Downloading linux-libc-dev:${arch}=${LINUX_LIBC_DEV_VERSION} for final sysroot headers"
  (
    cd "${workdir}/linux-libc-dev"
    apt-get download "linux-libc-dev:${arch}=${LINUX_LIBC_DEV_VERSION}"
  )
done

find "${workdir}/linux-libc-dev" -maxdepth 1 -type f -name '*.deb' -print0 \
  | while IFS= read -r -d '' deb; do
      echo "Extracting final sysroot headers from $(basename "${deb}")"
      dpkg-deb -x "${deb}" "${SYSROOT}"
    done

# dpkg-deb -x does not run maintainer scripts or update-alternatives, so
# recreate the linker-facing BLAS/LAPACK/OpenBLAS links in the sysroot.
if [[ -f "${LIBDIR}/openblas-pthread/libblas.so.3" ]]; then
  ln -sfn openblas-pthread/libblas.so.3 "${LIBDIR}/libblas.so.3"
fi
if [[ -f "${LIBDIR}/openblas-pthread/liblapack.so.3" ]]; then
  ln -sfn openblas-pthread/liblapack.so.3 "${LIBDIR}/liblapack.so.3"
fi
if [[ -e "${LIBDIR}/libblas.so.3" ]]; then
  ln -sfn libblas.so.3 "${LIBDIR}/libblas.so"
fi
if [[ -e "${LIBDIR}/liblapack.so.3" ]]; then
  ln -sfn liblapack.so.3 "${LIBDIR}/liblapack.so"
fi

if [[ ! -e "${LIBDIR}/libopenblas.so.0" ]]; then
  candidate="$(find "${LIBDIR}" -maxdepth 2 -type f -name 'libopenblas*.so*' | sort | head -n1 || true)"
  if [[ -n "${candidate}" ]]; then
    rel_target="$(realpath --relative-to="${LIBDIR}" "${candidate}")"
    ln -sfn "${rel_target}" "${LIBDIR}/libopenblas.so.0"
  fi
fi
if [[ -e "${LIBDIR}/libopenblas.so.0" && ! -e "${LIBDIR}/libopenblas.so" ]]; then
  ln -sfn libopenblas.so.0 "${LIBDIR}/libopenblas.so"
fi

echo "Sysroot overlay complete"
