#!/usr/bin/env bash
set -euo pipefail

binary="${1:-}"
rootfs="${2:-}"
if [[ -z "${binary}" || -z "${rootfs}" || -z "${SYSROOT:-}" ]]; then
  echo "Usage: $(basename "$0") ARM64_BINARY ROOTFS" >&2
  exit 2
fi

rm -rf "${rootfs}"
install -D -m 755 "${binary}" "${rootfs}/usr/local/bin/sima_neat_hello"

declare -a queue=("${binary}")
declare -A visited=()

resolve_library() {
  local name="$1" candidate match
  for candidate in \
    "${SYSROOT}/lib/aarch64-linux-gnu/${name}" \
    "${SYSROOT}/usr/lib/aarch64-linux-gnu/${name}" \
    "${SYSROOT}/usr/lib/${name}" \
    "${SYSROOT}/lib/${name}"; do
    if [[ -e "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  match="$(find "${SYSROOT}/lib" "${SYSROOT}/usr/lib" \
    \( -type f -o -type l \) -name "${name}" -print -quit)"
  [[ -n "${match}" ]] || return 1
  printf '%s\n' "${match}"
}

copy_sysroot_file() {
  local source="$1" destination
  destination="${rootfs}${source#"${SYSROOT}"}"
  mkdir -p "$(dirname "${destination}")"
  cp -L "${source}" "${destination}"
}

while ((${#queue[@]})); do
  elf="${queue[0]}"
  queue=("${queue[@]:1}")
  canonical="$(readlink -f "${elf}")"
  [[ -z "${visited[${canonical}]:-}" ]] || continue
  visited["${canonical}"]=1

  interpreter="$(aarch64-linux-gnu-readelf -l "${elf}" 2>/dev/null |
    sed -n 's@.*Requesting program interpreter: \([^]]*\)].*@\1@p')"
  if [[ -n "${interpreter}" && ! -e "${rootfs}${interpreter}" ]]; then
    interpreter_source="${SYSROOT}${interpreter}"
    if [[ ! -e "${interpreter_source}" ]]; then
      echo "Unable to resolve ARM64 interpreter ${interpreter}" >&2
      exit 1
    fi
    mkdir -p "$(dirname "${rootfs}${interpreter}")"
    cp -L "${interpreter_source}" "${rootfs}${interpreter}"
    queue+=("${interpreter_source}")
  fi

  while IFS= read -r dependency; do
    [[ -n "${dependency}" ]] || continue
    if ! dependency_source="$(resolve_library "${dependency}")"; then
      echo "Unable to resolve ARM64 runtime library ${dependency}" >&2
      exit 1
    fi
    copy_sysroot_file "${dependency_source}"
    queue+=("${dependency_source}")
  done < <(aarch64-linux-gnu-readelf -d "${elf}" 2>/dev/null |
    awk '$2 == "(NEEDED)" { gsub(/^\[|\]$/, "", $5); print $5 }')
done
