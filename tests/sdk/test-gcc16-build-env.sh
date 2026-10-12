#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2030,SC2031

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_SCRIPT="${ROOT_DIR}/scripts/simaai-init-build-env"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

gcc16_root="${tmpdir}/gcc-16.2.0-aarch64-linux-gnu"
mkdir -p "${gcc16_root}/bin"
for driver in aarch64-linux-gnu-gcc aarch64-linux-gnu-g++; do
  printf '#!/bin/sh\nexit 0\n' > "${gcc16_root}/bin/${driver}"
  chmod 755 "${gcc16_root}/bin/${driver}"
done

(
  export SIMA_GCC16_ROOT="${gcc16_root}"
  # shellcheck source=/dev/null
  source "${ENV_SCRIPT}" modalix gcc16 >/dev/null
  test "${SYSROOT}" = /opt/toolchain/aarch64/modalix
  test "${CC}" = "${gcc16_root}/bin/aarch64-linux-gnu-gcc"
  test "${CXX}" = "${gcc16_root}/bin/aarch64-linux-gnu-g++"
  test "${CROSS_COMPILE}" = aarch64-linux-gnu-
  test "${PATH%%:*}" = "${gcc16_root}/bin"
  case " ${CXXFLAGS} " in
    *" -I${SYSROOT}/usr/include "*) exit 1 ;;
  esac

  # Re-sourcing the default environment must remove the alternate compiler
  # prefix instead of leaving GCC16 selected through PATH.
  source "${ENV_SCRIPT}" modalix >/dev/null
  test "${CC}" = aarch64-linux-gnu-gcc
  test "${CXX}" = aarch64-linux-gnu-g++
  test -z "${SIMA_GCC16_ROOT:-}"
  case ":${PATH}:" in
    *":${gcc16_root}/bin:"*) exit 1 ;;
  esac
)

(
  # shellcheck source=/dev/null
  source "${ENV_SCRIPT}" modalix >/dev/null
  test "${CC}" = aarch64-linux-gnu-gcc
  test "${CXX}" = aarch64-linux-gnu-g++
  test -z "${SIMA_GCC16_ROOT:-}"
  case " ${CXXFLAGS} " in
    *" -I${SYSROOT}/usr/include "*) ;;
    *) exit 1 ;;
  esac
)

if (source "${ENV_SCRIPT}" davinci gcc16 >/dev/null 2>&1); then
  echo "Davinci unexpectedly accepted the unqualified GCC16 environment." >&2
  exit 1
fi
if (source "${ENV_SCRIPT}" modalix unknown >/dev/null 2>&1); then
  echo "Unknown toolchain selector unexpectedly succeeded." >&2
  exit 1
fi

bash -n "${ROOT_DIR}/scripts/install-gcc16-toolchain.sh"
"${ROOT_DIR}/scripts/install-gcc16-toolchain.sh" --help >/dev/null

echo "GCC16 build environment tests passed."
