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
chmod -R a+rX /opt/toolchain/aarch64/modalix/usr/include
