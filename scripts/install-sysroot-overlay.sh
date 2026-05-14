#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSROOT="${1:-/opt/toolchain/aarch64/modalix}"
LIBDIR="${SYSROOT}/usr/lib/aarch64-linux-gnu"
LINUX_LIBC_DEV_ARM64_VERSION="${SDK_SYSROOT_LINUX_LIBC_DEV_ARM64_VERSION:-${SDK_SYSROOT_LINUX_LIBC_DEV_VERSION:-}}"

CONFIG_CANDIDATES=()
if [[ -n "${SDK_SYSROOT_OVERLAY_CONFIG:-}" ]]; then
  CONFIG_CANDIDATES+=("${SDK_SYSROOT_OVERLAY_CONFIG}")
fi
CONFIG_CANDIDATES+=(
  "/usr/local/share/sima-sdk/sysroot-overlay.conf"
  "${SCRIPT_DIR}/../config/sysroot-overlay.conf"
)

for config in "${CONFIG_CANDIDATES[@]}"; do
  if [[ ! -f "${config}" ]]; then
    continue
  fi

  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    if [[ "${line}" != *=* ]]; then
      continue
    fi
    key="${line%%=*}"
    value="${line#*=}"
    case "${key}" in
      linux_libc_dev_arm64_version)
        if [[ -z "${LINUX_LIBC_DEV_ARM64_VERSION}" ]]; then
          LINUX_LIBC_DEV_ARM64_VERSION="${value}"
        fi
        ;;
    esac
  done < "${config}"
  break
done

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

if [[ " ${TARGET_ARCHES[*]} " == *" arm64 "* && -z "${LINUX_LIBC_DEV_ARM64_VERSION}" ]]; then
  echo "Missing linux_libc_dev_arm64_version in sysroot overlay config" >&2
  echo "Set SDK_SYSROOT_OVERLAY_CONFIG or SDK_SYSROOT_LINUX_LIBC_DEV_ARM64_VERSION." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

workdir="$(mktemp -d)"
cleanup() {
  rm -rf "${workdir}"
}
trap cleanup EXIT

mkdir -p "${SYSROOT}" "${LIBDIR}" "${workdir}/archives/partial" "${workdir}/linux-libc-dev"

# apt downloads as the sandbox user _apt. mktemp creates a 0700 root-owned
# directory, so make only the download staging paths accessible to avoid
# "Download is performed unsandboxed as root" warnings during Docker builds.
chmod 755 "${workdir}" "${workdir}/archives" "${workdir}/archives/partial" "${workdir}/linux-libc-dev"
if id _apt >/dev/null 2>&1; then
  chown _apt "${workdir}/archives" "${workdir}/archives/partial" "${workdir}/linux-libc-dev"
fi

echo "Downloading sysroot overlay packages into ${SYSROOT}"
printf '  %s\n' "${PACKAGES[@]}"

# In cross builds, apt treats some packages as Multi-Arch: same and requires
# the host and target architecture versions to match. Download the target
# linux-libc-dev version that matches the installed host package here, then
# replace the sysroot headers with the SDK-pinned version below.
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
  --reinstall \
  -o Dir::Cache::archives="${workdir}/archives" \
  "${PACKAGES[@]}"

find "${workdir}/archives" -maxdepth 1 -type f -name '*.deb' -print0 \
  | while IFS= read -r -d '' deb; do
      deb_arch="$(dpkg-deb -f "${deb}" Architecture)"
      # Apt may download host-arch helper packages while solving target deps.
      # Only target-arch and arch-independent payloads belong in this sysroot.
      if [[ "${deb_arch}" != "all" && " ${TARGET_ARCHES[*]} " != *" ${deb_arch} "* ]]; then
        echo "Skipping $(basename "${deb}") for architecture ${deb_arch}"
        continue
      fi
      echo "Extracting $(basename "${deb}")"
      dpkg-deb -x "${deb}" "${SYSROOT}"
    done

# The official Modalix 2.0 SDK sysroot uses SiMa's 6.1.22 arm64 UAPI headers.
# Download this .deb directly so apt's multiarch resolver cannot reject it for
# differing from the native amd64 linux-libc-dev package installed in the image.
for arch in "${TARGET_ARCHES[@]}"; do
  if [[ "${arch}" != "arm64" ]]; then
    continue
  fi

  echo "Downloading linux-libc-dev:${arch}=${LINUX_LIBC_DEV_ARM64_VERSION} for final sysroot headers"
  (
    cd "${workdir}/linux-libc-dev"
    apt-get download "linux-libc-dev:${arch}=${LINUX_LIBC_DEV_ARM64_VERSION}"
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

find "${SYSROOT}" -type l -print0 \
  | while IFS= read -r -d '' link; do
      target="$(readlink "${link}")"
      case "${target}" in
        /usr/*|/lib/*)
          sysroot_target="${SYSROOT}${target}"
          if [[ -e "${sysroot_target}" ]]; then
            rel_target="$(realpath --relative-to="$(dirname "${link}")" "${sysroot_target}")"
            ln -sfn "${rel_target}" "${link}"
          fi
          ;;
      esac
    done

if [[ -d "${SYSROOT}/usr/include" ]]; then
  chmod -R a+rX "${SYSROOT}/usr/include"
fi

echo "Sysroot overlay complete"
