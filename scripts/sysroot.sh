#!/usr/bin/env bash
set -euo pipefail

program_name="$(basename "$0")"
DEFAULT_SYSROOT="/opt/toolchain/aarch64/modalix"
DEFAULT_ARCH="arm64"
INSTALLER="${SYSROOT_INSTALLER:-/usr/local/bin/install-sysroot-overlay.sh}"

usage() {
  cat <<EOF
Usage:
  ${program_name} install [options] package [package ...]
  ${program_name} remove  [options] package [package ...]
  ${program_name} list    [options]
  ${program_name} help

Manages Debian package payloads in the SDK sysroot. Install downloads packages
with apt and extracts them into the sysroot. Remove deletes files recorded by
this command's install manifests; it cannot remove packages installed before
manifest tracking existed.

Options:
  --sysroot PATH  Sysroot to operate on (default: \${SYSROOT:-${DEFAULT_SYSROOT}})
  --arch ARCH     Target architecture for unqualified packages (default: ${DEFAULT_ARCH})
  --dry-run       Print actions without changing the sysroot
  -h, --help      Show this help

Examples:
  sudo ${program_name} install libpgm-dev
  sudo ${program_name} install opencv_dnn
  ${program_name} list
  sudo ${program_name} remove libpgm-dev
EOF
}

die() {
  echo "${program_name}: $*" >&2
  exit 2
}

run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  echo "${program_name}: this operation requires root privileges, and sudo is not available." >&2
  return 1
}

has_dry_run_arg() {
  local arg
  for arg in "$@"; do
    if [[ "${arg}" == "--dry-run" ]]; then
      return 0
    fi
  done
  return 1
}

reexec_as_root_if_needed() {
  local command="$1"
  shift

  if [[ "$(id -u)" -eq 0 ]] || has_dry_run_arg "$@"; then
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo_cmd=(sudo env)
    if [[ -n "${SYSROOT:-}" ]]; then
      sudo_cmd+=("SYSROOT=${SYSROOT}")
    fi
    if [[ -n "${SYSROOT_ARCH:-}" ]]; then
      sudo_cmd+=("SYSROOT_ARCH=${SYSROOT_ARCH}")
    fi
    if [[ -n "${SYSROOT_INSTALLER:-}" ]]; then
      sudo_cmd+=("SYSROOT_INSTALLER=${SYSROOT_INSTALLER}")
    fi
    sudo_cmd+=("${BASH_SOURCE[0]}" "${command}" "$@")
    exec "${sudo_cmd[@]}"
  fi

  echo "${program_name}: ${command} requires root privileges, and sudo is not available." >&2
  exit 1
}

validate_arch() {
  local arch="$1"
  if [[ -z "${arch}" || "${arch}" == *[!A-Za-z0-9._-]* ]]; then
    die "invalid architecture: ${arch}"
  fi
}

validate_sysroot() {
  local sysroot="$1"
  if [[ -z "${sysroot}" || "${sysroot}" != /* ]]; then
    die "sysroot must be an absolute path: ${sysroot}"
  fi
}

normalize_package() {
  local pkg="$1"
  local arch="$2"
  local name version name_part explicit_arch

  if [[ -z "${pkg}" ]]; then
    die "empty package name"
  fi
  if [[ "${pkg}" == -* ]]; then
    die "unsupported package option: ${pkg}"
  fi
  if [[ "${pkg}" == */* ]]; then
    die "package paths are not supported: ${pkg}"
  fi

  name="${pkg}"
  version=""
  if [[ "${name}" == *=* ]]; then
    version="${name#*=}"
    name="${name%%=*}"
    if [[ -z "${version}" ]]; then
      die "missing version after '=' in ${pkg}"
    fi
  fi

  explicit_arch=""
  name_part="${name}"
  if [[ "${name}" == *:* ]]; then
    name_part="${name%%:*}"
    explicit_arch="${name##*:}"
    if [[ -z "${name_part}" || -z "${explicit_arch}" ]]; then
      die "invalid package architecture qualifier: ${pkg}"
    fi
    validate_arch "${explicit_arch}"
  fi

  if [[ -z "${name_part}" || "${name_part}" == *[!A-Za-z0-9.+_-]* ]]; then
    die "invalid package name: ${pkg}"
  fi

  if [[ -z "${explicit_arch}" ]]; then
    name="${name}:${arch}"
  fi

  if [[ -n "${version}" ]]; then
    printf '%s=%s\n' "${name}" "${version}"
  else
    printf '%s\n' "${name}"
  fi
}

package_base() {
  local pkg="${1%%=*}"
  pkg="${pkg%%:*}"
  printf '%s\n' "${pkg}"
}

package_arch() {
  local pkg="${1%%=*}"
  if [[ "${pkg}" == *:* ]]; then
    printf '%s\n' "${pkg##*:}"
  else
    printf '%s\n' "${DEFAULT_ARCH}"
  fi
}

manifest_root() {
  printf '%s/var/lib/sima-sdk/sysroot-packages\n' "$1"
}

manifest_path() {
  local sysroot="$1"
  local pkg="$2"
  local arch="$3"
  printf '%s/%s_%s.manifest\n' "$(manifest_root "${sysroot}")" "${pkg}" "${arch}"
}

apt_package_exists() {
  local pkg="$1"
  local arch="$2"

  command -v apt-cache >/dev/null 2>&1 || return 1
  apt-cache policy "${pkg}:${arch}" 2>/dev/null | grep -q 'Candidate: [^(]'
}

resolve_component_name() {
  local pkg="$1"
  local arch="$2"
  local base version component candidates

  base="${pkg%%=*}"
  version=""
  if [[ "${pkg}" == *=* ]]; then
    version="${pkg#*=}"
  fi

  if [[ "${base}" == *:* ]] || apt_package_exists "${base}" "${arch}"; then
    printf '%s\n' "${pkg}"
    return
  fi

  case "${base}" in
    opencv_*)
      component="${base#opencv_}"
      component="${component//_/-}"
      if command -v apt-cache >/dev/null 2>&1; then
        mapfile -t candidates < <(
          {
            apt-cache search "^libopencv-${component}[0-9]+$" 2>/dev/null | awk '{print $1}'
            apt-cache search "^libopencv-${component}-dev$" 2>/dev/null | awk '{print $1}'
          } | awk '!seen[$0]++'
        )
        if [[ ${#candidates[@]} -eq 1 ]]; then
          if [[ -n "${version}" ]]; then
            printf '%s=%s\n' "${candidates[0]}" "${version}"
          else
            printf '%s\n' "${candidates[0]}"
          fi
          return
        fi
      fi
      ;;
  esac

  printf '%s\n' "${pkg}"
}

parse_common_options() {
  sysroot="${SYSROOT:-${DEFAULT_SYSROOT}}"
  arch="${SYSROOT_ARCH:-${DEFAULT_ARCH}}"
  dry_run=0
  args=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        usage
        exit 0
        ;;
      --sysroot)
        [[ $# -ge 2 ]] || die "--sysroot requires a value"
        sysroot="$2"
        shift 2
        ;;
      --sysroot=*)
        sysroot="${1#*=}"
        shift
        ;;
      --arch)
        [[ $# -ge 2 ]] || die "--arch requires a value"
        arch="$2"
        shift 2
        ;;
      --arch=*)
        arch="${1#*=}"
        shift
        ;;
      --dry-run)
        dry_run=1
        shift
        ;;
      --)
        shift
        while [[ $# -gt 0 ]]; do
          args+=("$1")
          shift
        done
        ;;
      -*)
        die "unsupported option: $1"
        ;;
      *)
        args+=("$1")
        shift
        ;;
    esac
  done

  validate_sysroot "${sysroot}"
  validate_arch "${arch}"
}

download_for_manifest() {
  local arch="$1"
  local outdir="$2"
  shift 2

  mkdir -p "${outdir}/archives/partial"
  chmod 755 "${outdir}" "${outdir}/archives" "${outdir}/archives/partial"
  if id _apt >/dev/null 2>&1; then
    chown _apt "${outdir}/archives" "${outdir}/archives/partial"
  fi

  apt-get update --allow-releaseinfo-change
  apt-get install -y --download-only --no-install-recommends --reinstall \
    -o Dir::Cache::archives="${outdir}/archives" \
    "$@"
}

record_manifests() {
  local sysroot="$1"
  local arch="$2"
  local debdir="$3"
  local root

  root="$(manifest_root "${sysroot}")"
  mkdir -p "${root}"

  find "${debdir}" -maxdepth 1 -type f -name '*.deb' -print0 |
    while IFS= read -r -d '' deb; do
      deb_arch="$(dpkg-deb -f "${deb}" Architecture)"
      if [[ "${deb_arch}" != "all" && "${deb_arch}" != "${arch}" ]]; then
        continue
      fi

      deb_pkg="$(dpkg-deb -f "${deb}" Package)"
      deb_version="$(dpkg-deb -f "${deb}" Version)"
      manifest="$(manifest_path "${sysroot}" "${deb_pkg}" "${deb_arch}")"
      tmp_manifest="${manifest}.tmp"

      {
        printf 'Package: %s\n' "${deb_pkg}"
        printf 'Architecture: %s\n' "${deb_arch}"
        printf 'Version: %s\n' "${deb_version}"
        printf '\n'
        dpkg-deb -c "${deb}" |
          awk '
            {
              path = $6
              sub(/^\.\//, "", path)
              if (path != "" && path !~ /\/$/) {
                print path
              }
            }
          ' | sort -u
      } > "${tmp_manifest}"

      mv "${tmp_manifest}" "${manifest}"
      echo "Recorded ${deb_pkg}:${deb_arch} ${deb_version}"
    done
}

cmd_install() {
  parse_common_options "$@"
  if [[ ${#args[@]} -eq 0 ]]; then
    die "install requires at least one package"
  fi
  if [[ "${dry_run}" != "1" && ! -x "${INSTALLER}" ]]; then
    echo "${program_name}: sysroot installer not found or not executable: ${INSTALLER}" >&2
    exit 1
  fi

  resolved=()
  normalized=()
  for pkg in "${args[@]}"; do
    resolved_pkg="$(resolve_component_name "${pkg}" "${arch}")"
    resolved+=("${resolved_pkg}")
    normalized+=("$(normalize_package "${resolved_pkg}" "${arch}")")
  done

  echo "Installing into sysroot: ${sysroot}"
  printf '  %s\n' "${normalized[@]}"
  for i in "${!args[@]}"; do
    if [[ "${args[$i]}" != "${resolved[$i]}" ]]; then
      echo "Resolved ${args[$i]} -> ${resolved[$i]}"
    fi
  done

  if [[ "${dry_run}" == "1" ]]; then
    printf 'Dry run install:'
    printf ' %q' "${INSTALLER}" "${sysroot}" "${normalized[@]}"
    printf '\n'
    exit 0
  fi

  run_as_root "${INSTALLER}" "${sysroot}" "${normalized[@]}"

  workdir="$(mktemp -d)"
  trap 'rm -rf "${workdir}"' EXIT
  download_for_manifest "${arch}" "${workdir}" "${normalized[@]}"
  record_manifests "${sysroot}" "${arch}" "${workdir}/archives"
}

file_owned_elsewhere() {
  local root="$1"
  local current_manifest="$2"
  local rel="$3"
  local other

  while IFS= read -r -d '' other; do
    if [[ "${other}" == "${current_manifest}" ]]; then
      continue
    fi
    if awk -v needle="${rel}" 'BEGIN{found=1} $0 == needle {found=0; exit} END{exit found}' "${other}"; then
      return 0
    fi
  done < <(find "${root}" -type f -name '*.manifest' -print0 2>/dev/null)

  return 1
}

remove_empty_parents() {
  local sysroot="$1"
  local rel="$2"
  local dir

  dir="$(dirname "${sysroot}/${rel}")"
  while [[ "${dir}" != "${sysroot}" && "${dir}" == "${sysroot}"/* ]]; do
    rmdir "${dir}" 2>/dev/null || break
    dir="$(dirname "${dir}")"
  done
}

cmd_remove() {
  parse_common_options "$@"
  if [[ ${#args[@]} -eq 0 ]]; then
    die "remove requires at least one package"
  fi

  root="$(manifest_root "${sysroot}")"
  if [[ ! -d "${root}" ]]; then
    echo "No sysroot package manifests found in ${root}" >&2
    exit 1
  fi

  manifests=()
  for pkg in "${args[@]}"; do
    normalized="$(normalize_package "${pkg}" "${arch}")"
    base="$(package_base "${normalized}")"
    pkg_arch="$(package_arch "${normalized}")"
    manifest="$(manifest_path "${sysroot}" "${base}" "${pkg_arch}")"
    if [[ ! -f "${manifest}" && "${pkg_arch}" != "all" ]]; then
      all_manifest="$(manifest_path "${sysroot}" "${base}" "all")"
      if [[ -f "${all_manifest}" ]]; then
        manifest="${all_manifest}"
      fi
    fi
    if [[ ! -f "${manifest}" ]]; then
      echo "${program_name}: ${base}:${pkg_arch} is not tracked in ${root}" >&2
      exit 1
    fi
    manifests+=("${manifest}")
  done

  for manifest in "${manifests[@]}"; do
    pkg="$(awk -F': ' '$1 == "Package" {print $2; exit}' "${manifest}")"
    pkg_arch="$(awk -F': ' '$1 == "Architecture" {print $2; exit}' "${manifest}")"
    echo "Removing ${pkg}:${pkg_arch} from ${sysroot}"

    awk 'seen_blank {print} /^$/ {seen_blank=1}' "${manifest}" | sort -r |
      while IFS= read -r rel; do
        [[ -n "${rel}" ]] || continue
        target="${sysroot}/${rel}"
        if file_owned_elsewhere "${root}" "${manifest}" "${rel}"; then
          continue
        fi
        if [[ "${dry_run}" == "1" ]]; then
          if [[ -e "${target}" || -L "${target}" ]]; then
            echo "Would remove ${target}"
          fi
          continue
        fi
        if [[ -e "${target}" || -L "${target}" ]]; then
          rm -f "${target}"
          remove_empty_parents "${sysroot}" "${rel}"
        fi
      done

    if [[ "${dry_run}" == "1" ]]; then
      echo "Would remove manifest ${manifest}"
    else
      rm -f "${manifest}"
    fi
  done
}

cmd_list() {
  parse_common_options "$@"
  if [[ ${#args[@]} -ne 0 ]]; then
    die "list does not accept package arguments"
  fi

  root="$(manifest_root "${sysroot}")"
  if [[ ! -d "${root}" ]]; then
    echo "No tracked sysroot packages."
    return
  fi

  shopt -s nullglob
  manifests=("${root}"/*.manifest)
  shopt -u nullglob
  if [[ ${#manifests[@]} -eq 0 ]]; then
    echo "No tracked sysroot packages."
    return
  fi

  printf '%s\0' "${manifests[@]}" |
    sort -z |
    while IFS= read -r -d '' manifest; do
      pkg="$(awk -F': ' '$1 == "Package" {print $2; exit}' "${manifest}")"
      pkg_arch="$(awk -F': ' '$1 == "Architecture" {print $2; exit}' "${manifest}")"
      version="$(awk -F': ' '$1 == "Version" {print $2; exit}' "${manifest}")"
      printf '%s:%s %s\n' "${pkg}" "${pkg_arch}" "${version}"
    done
}

command="${1:-}"
case "${command}" in
  ""|-h|--help|help)
    usage
    ;;
  install)
    shift
    reexec_as_root_if_needed install "$@"
    cmd_install "$@"
    ;;
  remove)
    shift
    reexec_as_root_if_needed remove "$@"
    cmd_remove "$@"
    ;;
  list)
    shift
    cmd_list "$@"
    ;;
  *)
    echo "${program_name}: unsupported command: ${command}" >&2
    usage >&2
    exit 2
    ;;
esac
