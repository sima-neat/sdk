#!/usr/bin/env bash

set -euo pipefail

if [[ "${MINIMAL_IMAGE:-0}" == "1" ]]; then
  echo "Skipping sysroot overlay for minimal image build"
  exit 0
fi

overlay_pkgs=()
for pkg in ${SDK_SYSROOT_PKG_LIST:-}; do
  overlay_pkgs+=("${pkg}:arm64")
done

/usr/local/bin/install-sysroot-overlay.sh /opt/toolchain/aarch64/modalix "${overlay_pkgs[@]}"

libdir=/opt/toolchain/aarch64/modalix/usr/lib/aarch64-linux-gnu
for lib in \
  libopencv_dnn.so.406 \
  libopencv_features2d.so.406 \
  libopencv_flann.so.406 \
  libopencv_objdetect.so.406 \
  libopencv_video.so.406; do
  if [[ ! -e "${libdir}/${lib}" ]]; then
    echo "Missing required sysroot OpenCV runtime library: ${libdir}/${lib}" >&2
    exit 1
  fi
done

chmod -R a+rX /opt/toolchain/aarch64/modalix/usr/include
