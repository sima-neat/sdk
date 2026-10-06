#!/usr/bin/env bash

set -euo pipefail

if [[ "${MINIMAL_IMAGE:-0}" == "1" ]]; then
  echo "Skipping sysroot overlay for minimal image build"
  exit 0
fi

if [[ "${SDK_APT_CHANNEL:-daily}" == daily ]]; then
  # setup-sdk-sysroot.sh already resolved all development dependencies against
  # Agate/Trixie. Do not overwrite them with the Bookworm overlay or UAPI pin.
  /usr/local/bin/install-sysroot-overlay.sh /opt/toolchain/aarch64/modalix --finalize-only
  exit 0
fi

overlay_pkgs=()
for pkg in ${SDK_SYSROOT_PKG_LIST:-}; do
  overlay_pkgs+=("${pkg}:arm64")
done

/usr/local/bin/install-sysroot-overlay.sh /opt/toolchain/aarch64/modalix "${overlay_pkgs[@]}"
chmod -R a+rX /opt/toolchain/aarch64/modalix/usr/include
