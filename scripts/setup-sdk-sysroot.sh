#!/usr/bin/env bash

set -euo pipefail

base_sdk_version="${1:?Usage: setup-sdk-sysroot.sh BASE_SDK_VERSION SDK_PKG_LIST}"
sdk_pkg_list="${2:-}"
sysroot="${SYSROOT:-/opt/toolchain/aarch64/modalix}"
download_dir="${SYSROOT_UPDATE_DOWNLOAD_DIR:-/tmp/modalix}"
python_command="${SDK_SYSROOT_PYTHON:-/usr/bin/python3}"
sysroot_pref=/etc/apt/preferences.d/00-sima-sdk-sysroot-target.pref
if [[ "${SDK_APT_CHANNEL:-daily}" != "release" ]]; then
  sdk_apt_origin="debian.neat.sima.ai"
else
  sdk_apt_origin="repo.sima.ai"
fi

cleanup_sysroot_pref() {
  rm -f "${sysroot_pref}"
}

if [[ "${MINIMAL_IMAGE:-0}" == "1" ]]; then
  mkdir -p /opt/toolchain/aarch64/modalix/usr/include \
           /opt/toolchain/aarch64/modalix/usr/lib \
           /opt/toolchain/aarch64/modalix/usr/lib/pkgconfig \
           /opt/toolchain/aarch64/modalix/usr/lib/aarch64-linux-gnu \
           /opt/toolchain/aarch64/modalix/usr/lib/aarch64-linux-gnu/pkgconfig \
           /opt/toolchain/aarch64/modalix/usr/share/pkgconfig
  exit 0
fi

if [[ -f /etc/apt/sources.list.d/debian-target.list ]]; then
  cat >"${sysroot_pref}" <<EOF
Package: *
Pin: origin "${sdk_apt_origin}"
Pin-Priority: 990

Package: *
Pin: origin "mirror.elxr.dev"
Pin-Priority: 990

Package: *
Pin: origin "deb.debian.org"
Pin-Priority: 990

Package: *
Pin: release o=Ubuntu
Pin-Priority: 100
EOF
  trap cleanup_sysroot_pref EXIT
fi

if [[ "${SDK_APT_CHANNEL:-daily}" == daily ]]; then
  # Resolve development packages and their Debian 13 runtime dependencies together.
  daily_packages=(
    a65apps-dev appcomplex-dev simaai-gst-plugins-dev simaai-heap-dev
    simaai-mlart-modalix-dev simaai-pcie-ep-dev simaai-socpipeline-dev swsoc-video-codec-modalix-dev
    simaai-memory-lib-dev simaai-log-dev simaai-trace-dev liblttng-ust-dev
    libopencv-dev libjsoncpp-dev cppzmq-dev libarpack2-dev libblas-dev
    libblkid-dev libbsd-dev libcharls-dev libcpp-httplib-dev
    libelf-dev libexpat1-dev libffi-dev libgdal-dev
    libglib2.0-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libgstrtspserver-1.0-dev
    libjpeg62-turbo-dev libjson-glib-dev liblapack-dev liblzma-dev
    libmount-dev libopenblas-pthread-dev libopenjp2-7-dev libpng-dev
    qtbase5-dev libsepol-dev libspdlog-dev libssl-dev
    libsuperlu-dev libtiff-dev liburcu-dev libwebp-dev
    python3-dev zlib1g-dev
  )
  sdk_pkg_list="${sdk_pkg_list},$(IFS=,; printf '%s' "${daily_packages[*]}")"
fi

SIMAAI_SYSROOT="${sysroot}" \
SIMAAI_DOWNLOAD_DIR="${download_dir}" \
"${python_command}" /opt/bin/simaai_setup_sdk.py modalix "${base_sdk_version}" "${SDK_LINUX_LIBC_VERSION:-}" "${sdk_pkg_list}"
validate-sysroot-package-versions.sh "${base_sdk_version}" "${download_dir}" "${sysroot}"
