#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${NEAT_SDK_TEST_WORK_DIR:-/tmp/neat-sdk-smoke-work}"
HELLO_SRC="${ROOT_DIR}/hello-neat"
HELLO_WORK="${WORK_DIR}/hello-neat"
STATUS_JSON="${WORK_DIR}/neat-status.json"

setup_sdk_environment() {
  if [[ -f /opt/bin/simaai-init-build-env ]]; then
    # shellcheck source=/dev/null
    source /opt/bin/simaai-init-build-env modalix >/dev/null 2>&1 || true
  fi

  if [[ -f /etc/profile.d/pkg-config-sysroot.sh ]]; then
    # shellcheck source=/dev/null
    source /etc/profile.d/pkg-config-sysroot.sh
  fi

  export SYSROOT="${SYSROOT:-/opt/toolchain/aarch64/modalix}"
}

run_test() {
  local name="$1"
  shift

  printf '\n========== %s ==========\n' "${name}"
  "$@"
}

test_neat_status() {
  echo "::group::Neat status"
  neat --json | tee "${STATUS_JSON}"
  python3 "${ROOT_DIR}/neat-status/validate_neat_status.py" "${STATUS_JSON}"
  echo "::endgroup::"
}

test_modalix_cross_toolchain() {
  local smoke_src="${WORK_DIR}/modalix-cross-smoke.cpp"
  local smoke_bin="${WORK_DIR}/modalix-cross-smoke"
  local compiler="${CXX:-aarch64-linux-gnu-g++}"
  local sysroot_libdir="${SYSROOT}/usr/lib/aarch64-linux-gnu"
  local sysroot_gcc_libdir="${SYSROOT}/usr/lib/gcc/aarch64-linux-gnu/12"

  test "${SYSROOT}" = "/opt/toolchain/aarch64/modalix"
  command -v "${compiler}"
  test -d "${SYSROOT}/usr/include"
  test -d "${sysroot_libdir}"
  test -e "${sysroot_libdir}/libMLArt.so"
  test -e "${sysroot_libdir}/libstdc++.so.6"

  cat > "${smoke_src}" <<'EOF'
#include <iostream>

int main() {
  std::cout << "modalix cross toolchain ok\n";
  return 0;
}
EOF

  "${compiler}" \
    --sysroot="${SYSROOT}" \
    -L"${sysroot_gcc_libdir}" \
    -L"${sysroot_libdir}" \
    -Wl,-rpath-link,"${sysroot_gcc_libdir}" \
    -Wl,-rpath-link,"${sysroot_libdir}" \
    -Wl,-rpath-link,"${SYSROOT}/lib/aarch64-linux-gnu" \
    -o "${smoke_bin}" \
    "${smoke_src}" \
    -Wl,--no-as-needed \
    -lMLArt \
    -Wl,--as-needed
  file "${smoke_bin}"
  file "${smoke_bin}" | grep -Eq 'aarch64|ARM aarch64|ARM64'
}

test_hello_neat_cpp() {
  cd "${HELLO_WORK}"

  echo "::group::Hello Neat C++ configure"
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
  echo "::endgroup::"

  echo "::group::Hello Neat C++ build"
  cmake --build build -j"$(nproc)"
  echo "::endgroup::"

  test -x build/sima_neat_hello
  file build/sima_neat_hello

  if [[ "${NEAT_SDK_SMOKE_RUN_BINARY:-0}" == "1" ]]; then
    ./build/sima_neat_hello
  else
    echo "Skipping C++ binary execution; CI smoke test validates SDK build setup without a paired DevKit."
  fi
}

test_hello_neat_python() {
  echo "Skipping Python runtime example; pyneat is validated on the DevKit side."
}

setup_sdk_environment

rm -rf "${WORK_DIR}"
mkdir -p "${HELLO_WORK}" "$(dirname "${STATUS_JSON}")"
cp -a "${HELLO_SRC}/." "${HELLO_WORK}/"

run_test "SDK status: neat --json" test_neat_status
run_test "Modalix cross toolchain" test_modalix_cross_toolchain
run_test "Hello Neat C++ build" test_hello_neat_cpp
run_test "Hello Neat Python runtime" test_hello_neat_python

printf '\nSDK smoke tests passed.\n'
