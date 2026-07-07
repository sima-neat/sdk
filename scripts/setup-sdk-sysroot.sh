#!/usr/bin/env bash

set -euo pipefail

base_sdk_version="${1:?Usage: setup-sdk-sysroot.sh BASE_SDK_VERSION SDK_PKG_LIST}"
sdk_pkg_list="${2:-}"
sysroot_pref=/etc/apt/preferences.d/00-sima-sdk-sysroot-target.pref

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
  cat >"${sysroot_pref}" <<'EOF'
Package: *
Pin: origin "repo.sima.ai/elxr"
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

python3 /opt/bin/simaai_setup_sdk.py modalix "${base_sdk_version}" "${sdk_pkg_list}"
validate-sysroot-package-versions.sh "${base_sdk_version}" /tmp/modalix /opt/toolchain/aarch64/modalix
