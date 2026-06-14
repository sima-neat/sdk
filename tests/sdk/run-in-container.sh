#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${NEAT_SDK_TEST_WORK_DIR:-/tmp/neat-sdk-smoke-work}"
HELLO_SRC="${ROOT_DIR}/hello-neat"
HELLO_WORK="${WORK_DIR}/hello-neat"
REPRESENTATIVE_SRC="${ROOT_DIR}/representative-builds"
REPRESENTATIVE_WORK="${WORK_DIR}/representative-builds"
STATUS_JSON="${WORK_DIR}/neat-status.json"
INSIGHT_WAIT_SECONDS="${NEAT_SDK_INSIGHT_WAIT_SECONDS:-30}"
SDK_DEPS_MANIFEST="${SDK_DEPS_MANIFEST:-/usr/local/share/sima-sdk/deps/manifest.json}"

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
  local deadline
  local insight_state

  echo "::group::Neat status"
  deadline=$((SECONDS + INSIGHT_WAIT_SECONDS))
  while true; do
    neat --json | tee "${STATUS_JSON}"
    insight_state="$(
      python3 - "${STATUS_JSON}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print((data.get("components", {}).get("insight", {}) or {}).get("serviceState", ""))
PY
    )"

    if [[ "${insight_state}" == "Running" ]] || (( SECONDS >= deadline )); then
      break
    fi
    sleep 2
  done

  if [[ "${insight_state}" != "Running" ]] && command -v insight-admin >/dev/null 2>&1; then
    echo "Insight did not report Running within ${INSIGHT_WAIT_SECONDS}s; collecting supervisor diagnostics."
    insight-admin status || true
    insight-admin logs 120 || true
  fi

  if [[ "${insight_state}" != "Running" ]]; then
    echo "Unexpected Insight service state after ${INSIGHT_WAIT_SECONDS}s: ${insight_state:-unknown}" >&2
    return 1
  fi

  python3 "${ROOT_DIR}/neat-status/validate_neat_status.py" "${STATUS_JSON}" "${SDK_DEPS_MANIFEST}"
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

test_sysroot_overlay_representative() {
  local overlay_script="/usr/local/bin/install-sysroot-overlay.sh"
  local overlay_sysroot="${WORK_DIR}/overlay-sysroot"

  test -x "${overlay_script}"
  rm -rf "${overlay_sysroot}"

  echo "::group::Representative sysroot overlay install"
  "${overlay_script}" "${overlay_sysroot}" \
    libfmt9:arm64 \
    libspdlog1.10:arm64 \
    libcpp-httplib0.11:arm64 \
    libpgm-dev:arm64
  echo "::endgroup::"

  test -e "${overlay_sysroot}/usr/lib/aarch64-linux-gnu/libfmt.so.9.1.0"
  test -e "${overlay_sysroot}/usr/lib/aarch64-linux-gnu/libspdlog.so.1.10.0"
  test -e "${overlay_sysroot}/usr/lib/aarch64-linux-gnu/libcpp-httplib.so.0.11"
  test -e "${overlay_sysroot}/usr/include/asm-generic/errno.h"
}

test_internals_representative() {
  local work="${REPRESENTATIVE_WORK}/internals"

  cd "${work}"

  echo "::group::Representative internals configure"
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
  echo "::endgroup::"

  echo "::group::Representative internals build"
  cmake --build build -j"$(nproc)"
  echo "::endgroup::"

  test -x build/representative_internals
  file build/representative_internals
  file build/representative_internals | grep -Eq 'aarch64|ARM aarch64|ARM64'
}

test_core_api_representative() {
  local work="${REPRESENTATIVE_WORK}/core-api"

  cd "${work}"

  echo "::group::Representative core API configure"
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
  echo "::endgroup::"

  echo "::group::Representative core API build"
  cmake --build build -j"$(nproc)"
  echo "::endgroup::"

  test -x build/representative_core_api
  file build/representative_core_api
  file build/representative_core_api | grep -Eq 'aarch64|ARM aarch64|ARM64'
}

target_python_minor() {
  local include_dir
  include_dir="$(find "${SYSROOT}/usr/include" -maxdepth 1 -type d -name 'python3.*' | sort | head -n 1)"
  if [[ -z "${include_dir}" ]]; then
    echo "No target Python include directory found in ${SYSROOT}/usr/include." >&2
    return 1
  fi
  basename "${include_dir}" | sed 's/^python//'
}

host_python() {
  local candidate

  for candidate in python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1 && "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
      command -v "${candidate}"
      return 0
    fi
  done

  echo "No host-runnable Python 3.8+ found for representative Python extension build." >&2
  return 1
}

test_llima_python_extension_representative() {
  local work="${REPRESENTATIVE_WORK}/llima-python-extension"
  local target_minor
  local host_python
  local python_include
  local python_library

  target_minor="$(target_python_minor)"
  host_python="$(host_python)"
  python_include="${SYSROOT}/usr/include/python${target_minor}"
  python_library="${SYSROOT}/usr/lib/aarch64-linux-gnu/libpython${target_minor}.so"

  test -x "${host_python}"
  test -f "${python_include}/Python.h"
  test -e "${python_library}"

  cd "${work}"

  echo "::group::Representative llima Python extension configure"
  cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DPYTHON_TARGET_VERSION="${target_minor}" \
    -DPython_EXECUTABLE="${host_python}" \
    -DPython_INCLUDE_DIR="${python_include}" \
    -DPython_LIBRARY="${python_library}"
  echo "::endgroup::"

  echo "::group::Representative llima Python extension build"
  cmake --build build -j"$(nproc)"
  echo "::endgroup::"

  test -e build/representative_llima_python.so
  file build/representative_llima_python.so
  file build/representative_llima_python.so | grep -Eq 'aarch64|ARM aarch64|ARM64'
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
mkdir -p "${HELLO_WORK}" "${REPRESENTATIVE_WORK}" "$(dirname "${STATUS_JSON}")"
cp -a "${HELLO_SRC}/." "${HELLO_WORK}/"
cp -a "${REPRESENTATIVE_SRC}/." "${REPRESENTATIVE_WORK}/"

run_test "SDK status: neat --json" test_neat_status
run_test "Modalix cross toolchain" test_modalix_cross_toolchain
run_test "Representative sysroot overlay install" test_sysroot_overlay_representative
run_test "Representative internals build" test_internals_representative
run_test "Representative core API build" test_core_api_representative
run_test "Representative llima Python extension build" test_llima_python_extension_representative
run_test "Hello Neat C++ build" test_hello_neat_cpp
run_test "Hello Neat Python runtime" test_hello_neat_python

printf '\nSDK smoke tests passed.\n'
