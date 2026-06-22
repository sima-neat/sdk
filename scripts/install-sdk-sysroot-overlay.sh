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
broken_opencv_links=()
while IFS= read -r link; do
  broken_opencv_links+=("${link}")
done < <(find "${libdir}" -maxdepth 1 -xtype l -name 'libopencv_*.so' -print | sort)

if [[ "${#broken_opencv_links[@]}" -gt 0 ]]; then
  echo "Broken sysroot OpenCV linker symlinks found:" >&2
  for link in "${broken_opencv_links[@]}"; do
    echo "  ${link} -> $(readlink "${link}")" >&2
  done
  exit 1
fi

chmod -R a+rX /opt/toolchain/aarch64/modalix/usr/include
