#!/usr/bin/env bash
set -euo pipefail

program_name="$(basename "$0")"
DEFAULT_SYSROOT="/opt/toolchain/aarch64/modalix"
DEFAULT_ARCH="arm64"
INSTALLER="${SYSROOT_INSTALLER:-/usr/local/bin/install-sysroot-overlay.sh}"
PLATFORM_SETUP="${SYSROOT_PLATFORM_SETUP:-/usr/local/bin/setup-sdk-sysroot.sh}"
SDK_RELEASE_FILE="${SDK_RELEASE_FILE:-/etc/sdk-release}"
PRE_RELEASE_REPOSITORY="${SYSROOT_PRE_RELEASE_REPOSITORY:-https://debian.neat.sima.ai/pre-release}"
PRE_RELEASE_ANCHOR_PACKAGE="${PRE_RELEASE_ANCHOR_PACKAGE:-simaai-palette-modalix}"
PLATFORM_PATTERNS_FILE="${PLATFORM_PACKAGE_PATTERNS_FILE:-/usr/local/share/sima-sdk/platform-package-patterns.txt}"
apt_cache_options=()
overlay_apt_workdir=""

usage() {
  cat <<EOF
Usage:
  ${program_name} install [options] package [package ...]
  ${program_name} remove  [options] package [package ...]
  ${program_name} list    [options]
  ${program_name} status  [options]
  ${program_name} update  [options] [X.Y.Z~preN]
  ${program_name} help

Manages Debian package payloads in the SDK sysroot. Install downloads packages
with apt and extracts them into the sysroot. Remove deletes files recorded by
this command's install manifests; it cannot remove packages installed before
manifest tracking existed.

Options:
  --sysroot PATH  Sysroot to operate on (default: \${SYSROOT:-${DEFAULT_SYSROOT}})
  --arch ARCH     Target architecture for unqualified packages (default: ${DEFAULT_ARCH})
  --dry-run       Print actions without changing the sysroot
  --latest        Select the newest pre-release for the SDK Platform Base
  --yes           Confirm a --latest update without an interactive prompt
  -h, --help      Show this help

Examples:
  sudo ${program_name} install libpgm-dev
  sudo ${program_name} install opencv_dnn
  ${program_name} list
  sudo ${program_name} remove libpgm-dev
  sudo ${program_name} update
  sudo ${program_name} update 2.1.3~pre4617
  sudo ${program_name} update --latest --yes
  ${program_name} status
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
  local name
  shift

  if [[ "$(id -u)" -eq 0 ]] || { [[ "${command}" != "update" ]] && has_dry_run_arg "$@"; }; then
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
    for name in \
      SDK_PKG_LIST \
      SDK_RELEASE_FILE \
      SDK_SYSROOT_PYTHON \
      SIMAAI_DOWNLOAD_WORKERS \
      SYSROOT_PLATFORM_SETUP \
      SYSROOT_PRE_RELEASE_REPOSITORY \
      PRE_RELEASE_ANCHOR_PACKAGE \
      PLATFORM_PACKAGE_PATTERNS_FILE \
      PRE_RELEASE_PACKAGES_FILE \
      PRE_RELEASE_RELEASE_URL \
      PRE_RELEASE_PACKAGES_URL \
      PRE_RELEASE_PACKAGES_PATH \
      SYSROOT_UPDATE_APT_SOURCE_FILE \
      SYSROOT_UPDATE_APT_PREFERENCES_FILE \
      SYSROOT_UPDATE_DOWNLOAD_DIR; do
      if declare -p "${name}" >/dev/null 2>&1; then
        sudo_cmd+=("${name}=${!name}")
      fi
    done
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

sysroot_overlay_path() {
  printf '%s/var/lib/sima-sdk/sysroot-overlay\n' "$1"
}

sysroot_inventory_path() {
  printf '%s/var/lib/sima-sdk/sysroot-packages.tsv\n' "$1"
}

summarize_payload_paths() {
  awk '
    function remember(path, parts, count, root) {
      sub(/^\.\//, "", path)
      sub(/^\//, "", path)
      if (path == "" || path ~ /\/$/) return
      count = split(path, parts, "/")
      if (parts[1] == "usr" && parts[2] == "lib" && count >= 3 && parts[3] ~ /linux-gnu$/) {
        root = "/" parts[1] "/" parts[2] "/" parts[3]
      } else if (count >= 2) {
        root = "/" parts[1] "/" parts[2]
      } else {
        root = "/" parts[1]
      }
      roots[root] = 1
    }
    { remember($0) }
    END { for (root in roots) print root }
  ' | sort | paste -sd ',' -
}

package_locations_from_deb() {
  local deb="$1"

  dpkg-deb -c "${deb}" |
    awk '{ path = $6; sub(/ ->.*$/, "", path); print path }' |
    summarize_payload_paths
}

package_locations_from_manifest() {
  local manifest="$1"

  awk 'seen_blank { print } /^$/ { seen_blank = 1 }' "${manifest}" |
    summarize_payload_paths
}

read_release_field() {
  local path="$1"
  local field="$2"

  [[ -r "${path}" ]] || return 1
  awk -F ' = ' -v wanted="${field}" '$1 == wanted { print substr($0, index($0, " = ") + 3); exit }' "${path}"
}

list_pre_release_versions() (
  set -euo pipefail

  local platform_base="$1"
  local workdir packages_file release_file packages_digest packages_url
  local release_url packages_path

  release_url="${PRE_RELEASE_RELEASE_URL:-${PRE_RELEASE_REPOSITORY}/dists/bookworm/Release}"
  packages_url="${PRE_RELEASE_PACKAGES_URL:-}"
  packages_path="${PRE_RELEASE_PACKAGES_PATH:-non-free/binary-arm64/Packages.gz}"
  workdir="$(mktemp -d)"
  trap 'rm -rf "${workdir}"' EXIT
  packages_file="${workdir}/Packages"

  if [[ -n "${PRE_RELEASE_PACKAGES_FILE:-}" ]]; then
    [[ -r "${PRE_RELEASE_PACKAGES_FILE}" ]] || die "Packages fixture is not readable: ${PRE_RELEASE_PACKAGES_FILE}"
    cp "${PRE_RELEASE_PACKAGES_FILE}" "${packages_file}"
  else
    command -v curl >/dev/null 2>&1 || die "curl is required to query the pre-release mirror"
    command -v gzip >/dev/null 2>&1 || die "gzip is required to read the pre-release package index"
    if [[ -z "${packages_url}" ]]; then
      release_file="${workdir}/Release"
      curl -fsSL --retry 4 --retry-all-errors "${release_url}" > "${release_file}"
      packages_digest="$(
        awk -v wanted="${packages_path}" '
          $0 == "SHA256:" { in_sha256 = 1; next }
          in_sha256 && $0 !~ /^ / { in_sha256 = 0 }
          in_sha256 && $3 == wanted { print $1; exit }
        ' "${release_file}"
      )"
      [[ "${packages_digest}" =~ ^[0-9a-fA-F]{64}$ ]] || \
        die "Release does not contain a valid SHA256 for ${packages_path}"
      packages_url="${release_url%/*}/${packages_path%/*}/by-hash/SHA256/${packages_digest}"
    fi
    curl -fsSL --retry 4 --retry-all-errors "${packages_url}" | gzip -dc > "${packages_file}"
  fi

  awk -v package="${PRE_RELEASE_ANCHOR_PACKAGE}" '
    $1 == "Package:" { current_package = $2 }
    $1 == "Version:" && current_package == package { print $2 }
  ' "${packages_file}" |
    awk -v prefix="${platform_base}~pre" 'index($0, prefix) == 1 && substr($0, length(prefix) + 1) ~ /^[0-9]+$/ { print }' |
    sort -Vu -r
)

apt_package_exists() {
  local pkg="$1"
  local arch="$2"

  command -v apt-cache >/dev/null 2>&1 || return 1
  apt-cache "${apt_cache_options[@]}" policy "${pkg}:${arch}" 2>/dev/null | grep -q 'Candidate: [^(]'
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
            apt-cache "${apt_cache_options[@]}" search "^libopencv-${component}[0-9]+$" 2>/dev/null | awk '{print $1}'
            apt-cache "${apt_cache_options[@]}" search "^libopencv-${component}-dev$" 2>/dev/null | awk '{print $1}'
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
  local sysroot_pref=/etc/apt/preferences.d/00-sima-sdk-sysroot-target.pref
  local sdk_apt_origin="repo.sima.ai"
  shift 2

  if [[ "${SDK_APT_CHANNEL:-release}" == "pre-release" ]]; then
    sdk_apt_origin="debian.neat.sima.ai"
  fi

  mkdir -p "${outdir}/archives/partial"
  touch "${outdir}/status"
  chmod 755 "${outdir}" "${outdir}/archives" "${outdir}/archives/partial"
  if id _apt >/dev/null 2>&1; then
    chown _apt "${outdir}/archives" "${outdir}/archives/partial"
  fi

  if [[ -f /etc/apt/sources.list.d/debian-target.list ]]; then
    cat >"${sysroot_pref}" <<EOF
Package: *
Pin: origin "${sdk_apt_origin}"
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
  fi

  apt-get update --allow-releaseinfo-change
  apt-get install -y --download-only --no-install-recommends --reinstall \
    -o APT::Architecture="${arch}" \
    -o Dir::Cache::archives="${outdir}/archives" \
    -o Dir::State::status="${outdir}/status" \
    "$@"
}

record_manifests() {
  local sysroot="$1"
  local arch="$2"
  local debdir="$3"
  local quiet="${4:-0}"
  local root

  root="$(manifest_root "${sysroot}")"
  mkdir -p "${root}"

  find "${debdir}" -maxdepth 1 \( -type f -o -type l \) -name '*.deb' -print0 |
    while IFS= read -r -d '' deb; do
      deb_arch="$(dpkg-deb -f "${deb}" Architecture)"
      if [[ "${deb_arch}" != "all" && "${deb_arch}" != "${arch}" ]]; then
        continue
      fi

      deb_pkg="$(dpkg-deb -f "${deb}" Package)"
      deb_version="$(dpkg-deb -f "${deb}" Version)"
      if [[ "${deb_pkg}" == "linux-libc-dev" && "${deb_arch}" == "arm64" ]]; then
        continue
      fi
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
      if [[ "${quiet}" != "1" ]]; then
        echo "Recorded ${deb_pkg}:${deb_arch} ${deb_version}"
      fi
    done
}

refresh_tracked_manifests() {
  local sysroot="$1"
  local arch="$2"
  local debdir="$3"
  local root workdir manifest package package_arch candidate target matched

  root="$(manifest_root "${sysroot}")"
  # A newly built SDK has no per-package manifests until the user installs a
  # package with `sysroot install`.  That is a successful no-op, not an error.
  [[ -d "${root}" ]] || return 0
  workdir="$(mktemp -d)"
  while IFS= read -r -d '' manifest; do
    package="$(awk -F ': ' '$1 == "Package" { print $2; exit }' "${manifest}")"
    package_arch="$(awk -F ': ' '$1 == "Architecture" { print $2; exit }' "${manifest}")"
    matched=""
    for candidate in \
      "${debdir}/${package}:${package_arch}.deb" \
      "${debdir}/${package}.deb"; do
      if [[ -f "${candidate}" ]] && \
         [[ "$(dpkg-deb -f "${candidate}" Package)" == "${package}" ]] && \
         [[ "$(dpkg-deb -f "${candidate}" Architecture)" == "${package_arch}" ]]; then
        matched="${candidate}"
        break
      fi
    done
    if [[ -z "${matched}" ]]; then
      while IFS= read -r -d '' candidate; do
        if [[ "$(dpkg-deb -f "${candidate}" Package)" == "${package}" ]] && \
           [[ "$(dpkg-deb -f "${candidate}" Architecture)" == "${package_arch}" ]]; then
          matched="${candidate}"
          break
        fi
      done < <(find "${debdir}" -maxdepth 1 -type f -name '*.deb' -print0)
    fi
    if [[ -n "${matched}" ]]; then
      target="${workdir}/${package}:${package_arch}.deb"
      ln "${matched}" "${target}" 2>/dev/null || ln -s "${matched}" "${target}"
    fi
  done < <(find "${root}" -maxdepth 1 -type f -name '*.manifest' -print0)

  if find "${workdir}" -maxdepth 1 \( -type f -o -type l \) -name '*.deb' -print -quit | grep -q .; then
    record_manifests "${sysroot}" "${arch}" "${workdir}" 1
  fi
  rm -rf "${workdir}"
}

write_package_inventory() {
  local sysroot="$1"
  local debdir="$2"
  local inventory tmp_inventory

  inventory="$(sysroot_inventory_path "${sysroot}")"
  mkdir -p "$(dirname "${inventory}")"
  tmp_inventory="${inventory}.tmp"
  find "${debdir}" -maxdepth 1 -type f -name '*.deb' -print0 |
    while IFS= read -r -d '' deb; do
      printf '%s\t%s\t%s\t%s\n' \
        "$(dpkg-deb -f "${deb}" Package)" \
        "$(dpkg-deb -f "${deb}" Architecture)" \
        "$(dpkg-deb -f "${deb}" Version)" \
        "$(package_locations_from_deb "${deb}")"
    done |
    sort -u > "${tmp_inventory}"
  [[ -s "${tmp_inventory}" ]] || die "no package inventory was produced from ${debdir}"
  mv "${tmp_inventory}" "${inventory}"
}

merge_package_inventory() {
  local sysroot="$1"
  local debdir="$2"
  local inventory additions merged

  inventory="$(sysroot_inventory_path "${sysroot}")"
  mkdir -p "$(dirname "${inventory}")"
  additions="${inventory}.additions"
  merged="${inventory}.tmp"
  find "${debdir}" -maxdepth 1 -type f -name '*.deb' -print0 |
    while IFS= read -r -d '' deb; do
      printf '%s\t%s\t%s\t%s\n' \
        "$(dpkg-deb -f "${deb}" Package)" \
        "$(dpkg-deb -f "${deb}" Architecture)" \
        "$(dpkg-deb -f "${deb}" Version)" \
        "$(package_locations_from_deb "${deb}")"
    done > "${additions}"
  [[ -s "${additions}" ]] || die "no package inventory additions were produced from ${debdir}"
  {
    if [[ -r "${inventory}" ]]; then
      cat "${inventory}"
    else
      find "$(manifest_root "${sysroot}")" -maxdepth 1 -type f -name '*.manifest' -print0 2>/dev/null |
        while IFS= read -r -d '' manifest; do
          printf '%s\t%s\t%s\t%s\n' \
            "$(awk -F ': ' '$1 == "Package" { print $2; exit }' "${manifest}")" \
            "$(awk -F ': ' '$1 == "Architecture" { print $2; exit }' "${manifest}")" \
            "$(awk -F ': ' '$1 == "Version" { print $2; exit }' "${manifest}")" \
            "$(package_locations_from_manifest "${manifest}")"
        done
    fi
    cat "${additions}"
  } |
    awk -F '\t' 'NF >= 3 { entry[$1 FS $2] = $0 } END { for (key in entry) print entry[key] }' |
    sort > "${merged}"
  mv "${merged}" "${inventory}"
  rm -f "${additions}"
}

merge_tracked_manifests_into_inventory() {
  local sysroot="$1"
  local inventory root manifest_entries merged manifest

  inventory="$(sysroot_inventory_path "${sysroot}")"
  root="$(manifest_root "${sysroot}")"
  # The image inventory can exist without any user-managed package manifests.
  # Return success so `set -e` does not abort a completed platform update.
  [[ -s "${inventory}" && -d "${root}" ]] || return 0
  manifest_entries="${inventory}.manifests"
  merged="${inventory}.tmp"
  : > "${manifest_entries}"
  while IFS= read -r -d '' manifest; do
    printf '%s\t%s\t%s\t%s\n' \
      "$(awk -F ': ' '$1 == "Package" { print $2; exit }' "${manifest}")" \
      "$(awk -F ': ' '$1 == "Architecture" { print $2; exit }' "${manifest}")" \
      "$(awk -F ': ' '$1 == "Version" { print $2; exit }' "${manifest}")" \
      "$(package_locations_from_manifest "${manifest}")" \
      >> "${manifest_entries}"
  done < <(find "${root}" -maxdepth 1 -type f -name '*.manifest' -print0)

  # Manifest entries are emitted first so a package from the newly resolved
  # platform cohort wins when the same package exists in both sources.
  cat "${manifest_entries}" "${inventory}" |
    awk -F '\t' 'NF >= 3 { entry[$1 FS $2] = $0 } END { for (key in entry) print entry[key] }' |
    sort > "${merged}"
  mv "${merged}" "${inventory}"
  rm -f "${manifest_entries}"
}

remove_package_from_inventory() {
  local sysroot="$1"
  local package="$2"
  local architecture="$3"
  local inventory temporary

  inventory="$(sysroot_inventory_path "${sysroot}")"
  [[ -r "${inventory}" ]] || return 0
  temporary="${inventory}.tmp"
  awk -F '\t' -v package="${package}" -v architecture="${architecture}" \
    'NF < 3 || $1 != package || $2 != architecture' "${inventory}" > "${temporary}"
  mv "${temporary}" "${inventory}"
}

write_overlay_metadata() {
  local sysroot="$1"
  local platform_base="$2"
  local platform_revision="$3"
  local overlay tmp_overlay inventory

  overlay="$(sysroot_overlay_path "${sysroot}")"
  inventory="$(sysroot_inventory_path "${sysroot}")"
  mkdir -p "$(dirname "${overlay}")"
  tmp_overlay="${overlay}.tmp"
  cat > "${tmp_overlay}" <<EOF
Overlay State = active
Platform Base = ${platform_base}
Platform Revision = ${platform_revision}
Platform Channel = pre-release
Platform Repository = ${PRE_RELEASE_REPOSITORY}
Updated At = $(date -u +%Y-%m-%dT%H:%M:%SZ)
Package Inventory = ${inventory}
EOF
  mv "${tmp_overlay}" "${overlay}"
}

write_overlay_transition() {
  local sysroot="$1"
  local platform_base="$2"
  local previous_revision="$3"
  local target_revision="$4"
  local state="$5"
  local overlay tmp_overlay

  overlay="$(sysroot_overlay_path "${sysroot}")"
  mkdir -p "$(dirname "${overlay}")"
  tmp_overlay="${overlay}.tmp"
  cat > "${tmp_overlay}" <<EOF
Overlay State = ${state}
Platform Base = ${platform_base}
Platform Revision = ${target_revision}
Previous Platform Revision = ${previous_revision}
Platform Channel = pre-release
Platform Repository = ${PRE_RELEASE_REPOSITORY}
Updated At = $(date -u +%Y-%m-%dT%H:%M:%SZ)
Package Inventory = $(sysroot_inventory_path "${sysroot}")
EOF
  mv "${tmp_overlay}" "${overlay}"
}

parse_update_options() {
  sysroot="${SYSROOT:-${DEFAULT_SYSROOT}}"
  arch="${SYSROOT_ARCH:-${DEFAULT_ARCH}}"
  dry_run=0
  update_latest=0
  assume_yes=0
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
      --latest)
        update_latest=1
        shift
        ;;
      -y|--yes)
        assume_yes=1
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
        die "unsupported update option: $1"
        ;;
      *)
        args+=("$1")
        shift
        ;;
    esac
  done

  validate_sysroot "${sysroot}"
  validate_arch "${arch}"
  [[ "${arch}" == "arm64" ]] || die "sysroot update supports only the Modalix arm64 sysroot"
  [[ ${#args[@]} -le 1 ]] || die "update accepts at most one pinned platform revision"
  if [[ "${update_latest}" == "1" && ${#args[@]} -ne 0 ]]; then
    die "--latest cannot be combined with an exact platform revision"
  fi
}

configure_update_apt() {
  local platform_revision="$1"
  local source_file preferences_file platform_packages

  source_file="${SYSROOT_UPDATE_APT_SOURCE_FILE:-/etc/apt/sources.list.d/00-sima-sdk-sysroot-pre-release.list}"
  preferences_file="${SYSROOT_UPDATE_APT_PREFERENCES_FILE:-/etc/apt/preferences.d/00-sima-sdk-sysroot-pre-release.pref}"
  update_source_created=0
  update_preferences_created=0

  if [[ "${dry_run:-0}" == "1" ]] || \
    ! grep -RhsF "${PRE_RELEASE_REPOSITORY}" /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | grep -q .; then
    [[ ! -e "${source_file}" ]] || die "temporary APT source already exists: ${source_file}"
    mkdir -p "$(dirname "${source_file}")"
    printf 'deb [arch=arm64 trusted=yes] %s bookworm non-free\n' "${PRE_RELEASE_REPOSITORY}" > "${source_file}"
    update_source_created=1
  fi

  [[ ! -e "${preferences_file}" ]] || die "temporary APT preferences already exist: ${preferences_file}"
  [[ -r "${PLATFORM_PATTERNS_FILE}" ]] || die "platform package patterns are unavailable: ${PLATFORM_PATTERNS_FILE}"
  platform_packages="$(
    sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "${PLATFORM_PATTERNS_FILE}" |
      tr '\n' ' ' |
      sed 's/[[:space:]]*$//'
  )"
  mkdir -p "$(dirname "${preferences_file}")"
  cat > "${preferences_file}" <<EOF
Package: ${platform_packages}
Pin: version ${platform_revision}
Pin-Priority: 1002

Package: *
Pin: origin "debian.neat.sima.ai"
Pin-Priority: 990

Package: *
Pin: origin "repo.sima.ai"
Pin-Priority: 990

Package: *
Pin: origin "mirror.elxr.dev"
Pin-Priority: 990

Package: *
Pin: origin "deb.debian.org"
Pin-Priority: 990

Package: *
Pin: origin "security.debian.org"
Pin-Priority: 990

Package: *
Pin: release o=Ubuntu
Pin-Priority: 100
EOF
  update_preferences_created=1
}

cleanup_update_apt() {
  if [[ "${update_source_created:-0}" == "1" ]]; then
    rm -f "${SYSROOT_UPDATE_APT_SOURCE_FILE:-/etc/apt/sources.list.d/00-sima-sdk-sysroot-pre-release.list}"
  fi
  if [[ "${update_preferences_created:-0}" == "1" ]]; then
    rm -f "${SYSROOT_UPDATE_APT_PREFERENCES_FILE:-/etc/apt/preferences.d/00-sima-sdk-sysroot-pre-release.pref}"
  fi
  if [[ -n "${overlay_apt_workdir:-}" ]]; then
    rm -rf "${overlay_apt_workdir}"
    overlay_apt_workdir=""
  fi
  apt_cache_options=()
}

configure_active_overlay_apt() {
  local overlay state revision repository

  overlay="$(sysroot_overlay_path "${sysroot}")"
  [[ -r "${overlay}" ]] || return 0
  state="$(read_release_field "${overlay}" "Overlay State")"
  [[ "${state}" == "active" ]] || \
    die "sysroot overlay state is ${state:-unknown}; rerun the update or recreate the SDK container before installing packages"
  revision="$(read_release_field "${overlay}" "Platform Revision")"
  repository="$(read_release_field "${overlay}" "Platform Repository")"
  [[ "${revision}" =~ ^[0-9]+\.[0-9]+\.[0-9]+~pre[0-9]+$ ]] || \
    die "active sysroot overlay has an invalid platform revision: ${revision:-<missing>}"
  [[ -n "${repository}" ]] || die "active sysroot overlay repository is missing"

  PRE_RELEASE_REPOSITORY="${repository}"
  export SDK_APT_CHANNEL=pre-release
  trap cleanup_update_apt EXIT
  if [[ "${dry_run}" == "1" ]]; then
    overlay_apt_workdir="$(mktemp -d)"
    SYSROOT_UPDATE_APT_SOURCE_FILE="${overlay_apt_workdir}/sources.list"
    SYSROOT_UPDATE_APT_PREFERENCES_FILE="${overlay_apt_workdir}/preferences"
    apt_cache_options=(
      -o "Dir::Etc::sourcelist=${SYSROOT_UPDATE_APT_SOURCE_FILE}"
      -o "Dir::Etc::preferences=${SYSROOT_UPDATE_APT_PREFERENCES_FILE}"
    )
  fi
  configure_update_apt "${revision}"
  echo "Using active sysroot overlay package selection: ${revision} (${repository})"
}

cleanup_update_transaction() {
  cleanup_update_apt
  if [[ "${update_overlay_pending:-0}" == "1" ]]; then
    write_overlay_transition \
      "${sysroot}" \
      "${update_platform_base}" \
      "${update_previous_revision}" \
      "${update_target_revision}" \
      "incomplete"
  fi
}

cleanup_install_transaction() {
  if [[ -n "${install_workdir:-}" ]]; then
    rm -rf "${install_workdir}"
  fi
  rm -f /etc/apt/preferences.d/00-sima-sdk-sysroot-target.pref
  cleanup_update_apt
}

apply_sysroot_update() {
  local platform_base="$1"
  local platform_revision="$2"
  local previous_revision="$3"
  local download_dir

  [[ -x "${PLATFORM_SETUP}" ]] || die "platform sysroot setup command is unavailable: ${PLATFORM_SETUP}"
  download_dir="${SYSROOT_UPDATE_DOWNLOAD_DIR:-/tmp/modalix-overlay-${platform_revision}}"
  update_platform_base="${platform_base}"
  update_previous_revision="${previous_revision}"
  update_target_revision="${platform_revision}"
  update_overlay_pending=0
  trap cleanup_update_transaction EXIT
  configure_update_apt "${platform_revision}"
  if [[ "${dry_run}" != "1" ]]; then
    write_overlay_transition \
      "${sysroot}" "${platform_base}" "${previous_revision}" "${platform_revision}" "updating"
    update_overlay_pending=1
  fi
  echo "Resolving and validating the complete ${platform_revision} package cohort..."
  if ! SYSROOT="${sysroot}" \
    SYSROOT_UPDATE_DOWNLOAD_DIR="${download_dir}" \
    SDK_APT_CHANNEL=pre-release \
    SIMAAI_PLATFORM_BUILD_REVISION="${platform_revision##*~pre}" \
    SIMAAI_VALIDATE_TARGET_ORIGIN=1 \
    SIMAAI_SETUP_DOWNLOAD_ONLY="${dry_run}" \
    "${PLATFORM_SETUP}" "${platform_revision}" "${SDK_PKG_LIST:-}"; then
    if [[ "${dry_run}" != "1" ]]; then
      echo "${program_name}: update failed while extracting packages; recreate the SDK container to guarantee a clean sysroot." >&2
    fi
    return 1
  fi

  if [[ "${dry_run}" == "1" ]]; then
    echo "Dry run complete: ${platform_revision} resolved and validated; the sysroot was not modified."
    return
  fi

  if [[ ! -s "$(sysroot_inventory_path "${sysroot}")" ]]; then
    write_package_inventory "${sysroot}" "${download_dir}"
  fi
  merge_tracked_manifests_into_inventory "${sysroot}"
  refresh_tracked_manifests "${sysroot}" "${arch}" "${download_dir}"
  write_overlay_metadata "${sysroot}" "${platform_base}" "${platform_revision}"
  update_overlay_pending=0
  echo "Sysroot overlay is active at ${platform_revision}."
  echo "Run '${program_name} status' to inspect it; recreate the SDK container to restore the image-default sysroot."
  echo "Start a new shell to display the overlay revision in the SDK prompt."
}

cmd_status() {
  local platform_base image_revision overlay overlay_state overlay_revision

  parse_common_options "$@"
  [[ ${#args[@]} -eq 0 ]] || die "status does not accept positional arguments"
  [[ -r "${SDK_RELEASE_FILE}" ]] || die "SDK release metadata is unavailable: ${SDK_RELEASE_FILE}"
  platform_base="$(read_release_field "${SDK_RELEASE_FILE}" "Platform Base")"
  image_revision="$(read_release_field "${SDK_RELEASE_FILE}" "Platform Version")"
  [[ -n "${platform_base}" ]] || die "Platform Base is missing from ${SDK_RELEASE_FILE}"
  [[ -n "${image_revision}" ]] || die "Platform Version is missing from ${SDK_RELEASE_FILE}"

  overlay="$(sysroot_overlay_path "${sysroot}")"
  overlay_state="inactive"
  overlay_revision="none"
  if [[ -r "${overlay}" ]]; then
    overlay_state="$(read_release_field "${overlay}" "Overlay State")"
    overlay_revision="$(read_release_field "${overlay}" "Platform Revision")"
  fi

  printf 'SDK image platform:       %s\n' "${image_revision}"
  printf 'Platform Base:            %s\n' "${platform_base}"
  printf 'Sysroot overlay state:    %s\n' "${overlay_state:-active}"
  printf 'Sysroot overlay revision: %s\n' "${overlay_revision:-unknown}"
  if [[ -r "${overlay}" ]]; then
    printf 'Sysroot channel:          %s\n' "$(read_release_field "${overlay}" "Platform Channel")"
    printf 'Sysroot repository:       %s\n' "$(read_release_field "${overlay}" "Platform Repository")"
    printf 'Sysroot updated at:       %s\n' "$(read_release_field "${overlay}" "Updated At")"
    if [[ "${overlay_state}" != "active" ]]; then
      printf 'Previous revision:        %s\n' "$(read_release_field "${overlay}" "Previous Platform Revision")"
      echo "WARNING: The sysroot overlay is not complete; rerun the update or recreate the SDK container."
    fi
  fi
}

cmd_update() {
  local platform_base image_revision current_revision current_state target_revision selection answer
  local explicit_revision=0 candidate_found=0 candidate
  local -a available_versions

  parse_update_options "$@"
  [[ -r "${SDK_RELEASE_FILE}" ]] || die "SDK release metadata is unavailable: ${SDK_RELEASE_FILE}"
  platform_base="$(read_release_field "${SDK_RELEASE_FILE}" "Platform Base")"
  image_revision="$(read_release_field "${SDK_RELEASE_FILE}" "Platform Version")"
  [[ "${platform_base}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || \
    die "invalid or missing Platform Base in ${SDK_RELEASE_FILE}: ${platform_base:-<missing>}"
  [[ -n "${image_revision}" ]] || die "Platform Version is missing from ${SDK_RELEASE_FILE}"

  mapfile -t available_versions < <(list_pre_release_versions "${platform_base}")
  [[ ${#available_versions[@]} -gt 0 ]] || \
    die "no ${platform_base}~preN revisions are available for ${PRE_RELEASE_ANCHOR_PACKAGE}"

  cat <<EOF
WARNING: This operation installs pre-release SiMa.ai platform software into
the SDK sysroot. It is intended only for development and testing.

SDK Platform Base: ${platform_base}
Repository:        ${PRE_RELEASE_REPOSITORY}
Repository trust:  HTTPS transport with APT trusted=yes (unsigned metadata)
EOF

  if [[ ${#args[@]} -eq 1 ]]; then
    target_revision="${args[0]}"
    explicit_revision=1
  elif [[ "${update_latest}" == "1" ]]; then
    target_revision="${available_versions[0]}"
  else
    [[ -t 0 ]] || die "interactive revision selection requires a TTY; pass X.Y.Z~preN or --latest --yes"
    echo
    echo "Available revisions:"
    for selection in "${!available_versions[@]}"; do
      printf '  %d. %s' "$((selection + 1))" "${available_versions[selection]}"
      if [[ "${selection}" -eq 0 ]]; then
        printf ' (latest)'
      fi
      printf '\n'
    done
    printf '  %d. Cancel\n' "$(( ${#available_versions[@]} + 1 ))"
    read -r -p "Select a revision: " selection
    [[ "${selection}" =~ ^[0-9]+$ ]] || die "invalid revision selection: ${selection}"
    if (( selection == ${#available_versions[@]} + 1 )); then
      echo "Cancelled."
      return
    fi
    (( selection >= 1 && selection <= ${#available_versions[@]} )) || die "revision selection is out of range"
    target_revision="${available_versions[selection - 1]}"
  fi

  if [[ ! "${target_revision}" =~ ^([0-9]+\.[0-9]+\.[0-9]+)~pre[0-9]+$ ]]; then
    die "update revision must use X.Y.Z~preN: ${target_revision}"
  fi
  [[ "${BASH_REMATCH[1]}" == "${platform_base}" ]] || \
    die "SDK Platform Base is ${platform_base}; refusing revision ${target_revision}"
  for candidate in "${available_versions[@]}"; do
    if [[ "${candidate}" == "${target_revision}" ]]; then
      candidate_found=1
      break
    fi
  done
  [[ "${candidate_found}" == "1" ]] || \
    die "revision ${target_revision} is not available for ${PRE_RELEASE_ANCHOR_PACKAGE}"

  current_revision="${image_revision}"
  current_state="active"
  if [[ -r "$(sysroot_overlay_path "${sysroot}")" ]]; then
    current_revision="$(read_release_field "$(sysroot_overlay_path "${sysroot}")" "Platform Revision")"
    current_state="$(read_release_field "$(sysroot_overlay_path "${sysroot}")" "Overlay State")"
  fi
  if [[ "${current_state}" == "active" && "${current_revision}" == "${target_revision}" ]]; then
    echo "Sysroot is already at ${target_revision}; no changes are required."
    return
  fi

  echo
  echo "Updating Modalix sysroot: ${current_revision} -> ${target_revision}"
  if [[ "${dry_run}" != "1" && "${explicit_revision}" != "1" && "${assume_yes}" != "1" ]]; then
    [[ -t 0 ]] || die "confirmation requires a TTY; rerun with --latest --yes"
    read -r -p "Continue? [y/N] " answer
    case "${answer}" in
      y|Y|yes|YES) ;;
      *) echo "Cancelled."; return ;;
    esac
  fi

  apply_sysroot_update "${platform_base}" "${target_revision}" "${current_revision}"
}

cmd_install() {
  local -a resolved normalized
  local pkg resolved_pkg workdir i

  parse_common_options "$@"
  if [[ ${#args[@]} -eq 0 ]]; then
    die "install requires at least one package"
  fi
  if [[ "${dry_run}" != "1" && ! -x "${INSTALLER}" ]]; then
    echo "${program_name}: sysroot installer not found or not executable: ${INSTALLER}" >&2
    exit 1
  fi

  # Restore an active overlay's exact APT source and pin before translating
  # component aliases. Alias discovery must see the same package universe as
  # the installer, including during a dry run.
  configure_active_overlay_apt

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
  install_workdir="${workdir}"
  trap cleanup_install_transaction EXIT
  download_for_manifest "${arch}" "${workdir}" "${normalized[@]}"
  record_manifests "${sysroot}" "${arch}" "${workdir}/archives"
  merge_package_inventory "${sysroot}" "${workdir}/archives"
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
  local -a manifests
  local root pkg normalized base pkg_arch manifest all_manifest

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
      remove_package_from_inventory "${sysroot}" "${pkg}" "${pkg_arch}"
    fi
  done
}

cmd_list() {
  local inventory root manifest pkg pkg_arch version
  local -a manifests

  parse_common_options "$@"
  if [[ ${#args[@]} -ne 0 ]]; then
    die "list does not accept package arguments"
  fi

  inventory="$(sysroot_inventory_path "${sysroot}")"
  if [[ -s "${inventory}" ]]; then
    printf '%-38s %-8s %-28s %s\n' \
      "PACKAGE" "ARCH" "VERSION" "LOCATION(S) IN ${sysroot}"
    sort -t $'\t' -k1,1 -k2,2 "${inventory}" |
      while IFS=$'\t' read -r pkg pkg_arch version locations; do
        if [[ -z "${locations:-}" ]]; then
          manifest="$(manifest_path "${sysroot}" "${pkg}" "${pkg_arch}")"
          if [[ -r "${manifest}" ]]; then
            locations="$(package_locations_from_manifest "${manifest}")"
          fi
        fi
        printf '%-38s %-8s %-28s %s\n' \
          "${pkg}" "${pkg_arch}" "${version}" "${locations:-(not recorded)}"
      done
    return
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

  printf '%-38s %-8s %-28s %s\n' \
    "PACKAGE" "ARCH" "VERSION" "LOCATION(S) IN ${sysroot}"
  printf '%s\0' "${manifests[@]}" |
    sort -z |
    while IFS= read -r -d '' manifest; do
      pkg="$(awk -F': ' '$1 == "Package" {print $2; exit}' "${manifest}")"
      pkg_arch="$(awk -F': ' '$1 == "Architecture" {print $2; exit}' "${manifest}")"
      version="$(awk -F': ' '$1 == "Version" {print $2; exit}' "${manifest}")"
      printf '%-38s %-8s %-28s %s\n' \
        "${pkg}" "${pkg_arch}" "${version}" "$(package_locations_from_manifest "${manifest}")"
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
  status)
    shift
    cmd_status "$@"
    ;;
  update)
    shift
    reexec_as_root_if_needed update "$@"
    cmd_update "$@"
    ;;
  *)
    echo "${program_name}: unsupported command: ${command}" >&2
    usage >&2
    exit 2
    ;;
esac
