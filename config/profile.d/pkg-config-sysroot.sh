#!/usr/bin/env bash
export SYSROOT="${SYSROOT:-/opt/toolchain/aarch64/modalix}"
if [[ -z "${PKG_CONFIG:-}" || ! -x "${PKG_CONFIG}" ]]; then
  export PKG_CONFIG="/usr/bin/pkg-config"
fi
if [[ -z "${PKG_CONFIG_EXECUTABLE:-}" || ! -x "${PKG_CONFIG_EXECUTABLE}" ]]; then
  export PKG_CONFIG_EXECUTABLE="${PKG_CONFIG}"
fi
export PKG_CONFIG_SYSROOT_DIR="${PKG_CONFIG_SYSROOT_DIR:-$SYSROOT}"
export PKG_CONFIG_LIBDIR="${PKG_CONFIG_LIBDIR:-$SYSROOT/usr/lib/aarch64-linux-gnu/pkgconfig:$SYSROOT/usr/lib/pkgconfig:$SYSROOT/usr/share/pkgconfig}"
unset PKG_CONFIG_PATH || true
export LDFLAGS="--sysroot=$SYSROOT -L$SYSROOT/usr/lib/aarch64-linux-gnu -L$SYSROOT/lib/aarch64-linux-gnu ${LDFLAGS:-}"
