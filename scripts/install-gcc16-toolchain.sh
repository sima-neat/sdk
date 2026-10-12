#!/usr/bin/env bash

set -euo pipefail

readonly GCC_VERSION="16.2.0"
readonly GCC_ARCHIVE="gcc-${GCC_VERSION}.tar.xz"
readonly GCC_URL="https://gcc.gnu.org/pub/gcc/releases/gcc-${GCC_VERSION}/${GCC_ARCHIVE}"
readonly GCC_SHA512="c51c30ca7422d0cbecf504b2e0f33c3aca31e0f90a76b65217f465163fa6fa17b3f5de39e145c47e5bab90ac0ce7fff3b03c8d553ae36e01faaea5a50f8648d1"
readonly TARGET="aarch64-linux-gnu"

prefix="${GCC16_PREFIX:-/opt/toolchain/gcc-${GCC_VERSION}-${TARGET}}"
sysroot="${SYSROOT:-/opt/toolchain/aarch64/modalix}"
cache_dir="${GCC16_BUILD_CACHE:-/var/cache/sima-sdk-gcc16}"
jobs="${GCC16_BUILD_JOBS:-$(nproc)}"
verify_only=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--verify-only] [--prefix PATH] [--sysroot PATH] [--jobs N]

Build and install the pinned GCC ${GCC_VERSION} ${TARGET} toolchain, or verify an
existing installation. The compiler prefix remains separate from the target
platform sysroot.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only)
      verify_only=1
      shift
      ;;
    --prefix)
      prefix="${2:?Missing value for --prefix}"
      shift 2
      ;;
    --sysroot)
      sysroot="${2:?Missing value for --sysroot}"
      shift 2
      ;;
    --jobs)
      jobs="${2:?Missing value for --jobs}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${prefix}" != /* || "${sysroot}" != /* ]]; then
  echo "GCC16 prefix and sysroot must be absolute paths." >&2
  exit 2
fi
if [[ ! "${jobs}" =~ ^[1-9][0-9]*$ ]]; then
  echo "GCC16 build jobs must be a positive integer: ${jobs}" >&2
  exit 2
fi
if [[ ! -d "${sysroot}/usr/include" ]]; then
  echo "Modalix sysroot headers are missing: ${sysroot}/usr/include" >&2
  exit 1
fi

verify_toolchain() {
  local cc="${prefix}/bin/${TARGET}-gcc"
  local cxx="${prefix}/bin/${TARGET}-g++"
  local version target libstdcxx libgcc work

  for driver in "${cc}" "${cxx}"; do
    if [[ ! -x "${driver}" ]]; then
      echo "GCC16 driver is missing: ${driver}" >&2
      return 1
    fi
    version="$("${driver}" -dumpfullversion -dumpversion)"
    target="$("${driver}" -dumpmachine)"
    if [[ ! "${version}" =~ ^16\.([2-9]|[1-9][0-9]+)(\.[0-9]+)?$ ]]; then
      echo "GCC 16.2 or newer is required, found ${version}: ${driver}" >&2
      return 1
    fi
    if [[ ! "${target}" =~ ^aarch64[^-]*-.*linux.*$ ]]; then
      echo "Expected an AArch64 Linux compiler, found ${target}: ${driver}" >&2
      return 1
    fi
  done

  libstdcxx="$("${cxx}" --sysroot="${sysroot}" -print-file-name=libstdc++.so)"
  libgcc="$("${cxx}" --sysroot="${sysroot}" -print-file-name=libgcc_s.so.1)"
  for runtime in "${libstdcxx}" "${libgcc}"; do
    if [[ "${runtime}" != "${prefix}"/* || ! -e "${runtime}" ]]; then
      echo "GCC16 did not select its packaged target runtime: ${runtime}" >&2
      return 1
    fi
    "${TARGET}-readelf" -h "${runtime}" | grep -q 'AArch64'
  done

  work="$(mktemp -d)"
  trap 'rm -rf "${work}"' RETURN
  cat > "${work}/probe.cpp" <<'EOF'
#include <span>
#include <string>
static_assert(_GLIBCXX_RELEASE == 16);
int main(int argc, char **) {
  int value[] = {argc};
  std::span<int> values(value);
  return std::stoi(std::to_string(values.front())) != argc;
}
EOF
  "${cxx}" -std=c++20 --sysroot="${sysroot}" "${work}/probe.cpp" -o "${work}/probe"
  "${TARGET}-readelf" -h "${work}/probe" | grep -q 'AArch64'
  rm -rf "${work}"
  trap - RETURN
}

if [[ "${verify_only}" == 1 ]]; then
  verify_toolchain
  exit 0
fi

required=(gcc g++ make tar bzip2 sha512sum wget curl file "${TARGET}-as" "${TARGET}-ld" "${TARGET}-readelf")
missing=()
for command in "${required[@]}"; do
  command -v "${command}" >/dev/null 2>&1 || missing+=("${command}")
done
if [[ ${#missing[@]} -ne 0 ]]; then
  echo "Missing GCC16 build prerequisites: ${missing[*]}" >&2
  exit 1
fi

mkdir -p "${cache_dir}"
archive="${cache_dir}/${GCC_ARCHIVE}"
if [[ -f "${archive}" ]] && ! echo "${GCC_SHA512}  ${archive}" | sha512sum -c - >/dev/null 2>&1; then
  echo "Discarding corrupt GCC source archive: ${archive}" >&2
  rm -f "${archive}"
fi
if [[ ! -f "${archive}" ]]; then
  partial="${archive}.partial"
  rm -f "${partial}"
  curl -fsSL --retry 3 --retry-delay 2 "${GCC_URL}" -o "${partial}"
  echo "${GCC_SHA512}  ${partial}" | sha512sum -c -
  mv "${partial}" "${archive}"
fi

build_root="$(mktemp -d "${cache_dir}/build-${GCC_VERSION}-XXXXXX")"
trap 'rm -rf "${build_root}"' EXIT
tar -xJf "${archive}" -C "${build_root}"
source_dir="${build_root}/gcc-${GCC_VERSION}"
(
  cd "${source_dir}"
  ./contrib/download_prerequisites --verify --sha512
)

object_dir="${build_root}/objects"
mkdir -p "${object_dir}"
(
  cd "${object_dir}"
  CC="$(command -v gcc)" CXX="$(command -v g++)" \
    "${source_dir}/configure" \
      --prefix="${prefix}" \
      --target="${TARGET}" \
      --with-sysroot="${sysroot}" \
      --with-as="$(command -v "${TARGET}-as")" \
      --with-ld="$(command -v "${TARGET}-ld")" \
      --enable-languages=c,c++ \
      --disable-bootstrap \
      --disable-multilib \
      --disable-nls \
      --disable-libcc1 \
      --disable-libsanitizer \
      --with-system-zlib \
      --enable-default-pie
  make -j"${jobs}"
  staging="${build_root}/stage"
  make install DESTDIR="${staging}"
  installed="${staging}${prefix}"
  if [[ ! -d "${installed}" ]]; then
    echo "GCC16 staged prefix is missing: ${installed}" >&2
    exit 1
  fi
  if [[ -e "${prefix}" ]]; then
    echo "Refusing to replace existing GCC16 prefix: ${prefix}" >&2
    exit 1
  fi
  mkdir -p "$(dirname "${prefix}")"
  mv "${installed}" "${prefix}"
)

verify_toolchain
chmod -R a+rX "${prefix}"
rm -rf "${build_root}"
trap - EXIT
