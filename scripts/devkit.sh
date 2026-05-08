#!/usr/bin/env bash
# Sourceable helper for configuring DevKit NFS client mount to host workspace.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Use: source devkit.sh [devkit-ip|$DEVKIT_SYNC_DEVKIT_IP] [devkit-user=sima] [devkit-port=22]" >&2
  exit 2
fi

if [[ -z "${1:-}" && -z "${DEVKIT_SYNC_DEVKIT_IP:-}" ]]; then
  echo "Usage: source devkit.sh [devkit-ip|$DEVKIT_SYNC_DEVKIT_IP] [devkit-user=sima] [devkit-port=22]" >&2
  return 2
fi

check_remote_passwordless_sudo() {
  local user="$1"
  local ip="$2"
  local port="$3"
  ssh -tt -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${user}@${ip}" "sudo -n true" >/dev/null 2>&1
}

check_devkit_sdk_version_compatibility() {
  local user="$1"
  local ip="$2"
  local port="$3"
  local sdk_release="/etc/sdk-release"
  local devkit_distro_version=""
  local sdk_expected_version=""
  local c_warn="" c_reset=""

  if [[ -t 2 ]]; then
    c_warn=$'\033[1;31m'
    c_reset=$'\033[0m'
  fi

  echo "Checking DevKit/SDK version compatibility..."

  if [[ ! -r "${sdk_release}" ]]; then
    printf "%bWARNING:%b SDK release file not found or unreadable: %s\n" "${c_warn}" "${c_reset}" "${sdk_release}" >&2
    printf "Please use an SDK image that includes /etc/sdk-release before connecting a DevKit.\n" >&2
    return 0
  fi

  devkit_distro_version="$(
    ssh -T -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${user}@${ip}" sh -s 2>/dev/null <<'EOS'
if [ ! -r /etc/buildinfo ]; then
  exit 2
fi
awk -F= '
  /^[[:space:]]*DISTRO_VERSION[[:space:]]*=/ {
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
    print $2
    exit
  }
' /etc/buildinfo
EOS
  )"

  if [[ -z "${devkit_distro_version}" ]]; then
    printf "%bWARNING:%b Could not read DISTRO_VERSION from DevKit /etc/buildinfo.\n" "${c_warn}" "${c_reset}" >&2
    printf "Please update your DevKit to a build that exposes /etc/buildinfo with DISTRO_VERSION.\n" >&2
    return 0
  fi

  if grep -Fq "${devkit_distro_version}" "${sdk_release}"; then
    echo "DevKit DISTRO_VERSION ${devkit_distro_version} is compatible with this SDK."
    return 0
  fi

  sdk_expected_version="$(
    grep -E '^[[:space:]]*eLXr Version[[:space:]]*=' "${sdk_release}" \
      | grep -Eo '[0-9]+([.][0-9]+){2}' \
      | head -n1 || true
  )"
  if [[ -z "${sdk_expected_version}" ]]; then
    sdk_expected_version="$(
      grep -Eo '[0-9]+([.][0-9]+){2}' "${sdk_release}" \
        | head -n1 || true
    )"
  fi

  {
    printf "%bWARNING: DevKit/SDK version mismatch.\n" "${c_warn}"
    printf "  DevKit DISTRO_VERSION: %s\n" "${devkit_distro_version}"
    printf "  SDK release file     : %s\n" "${sdk_release}"
    sed 's/^/    /' "${sdk_release}"
    if [[ -n "${sdk_expected_version}" ]]; then
      printf "\nPlease update your DevKit to %s, then reconnect.%b\n" "${sdk_expected_version}" "${c_reset}"
    else
      printf "\nPlease update your DevKit to the matching version listed in %s, then reconnect.%b\n" "${sdk_release}" "${c_reset}"
    fi
  } >&2
  return 0
}

sync_neat_framework_to_devkit() {
  local user="$1"
  local ip="$2"
  local port="$3"
  local sync_enabled="${DEVKIT_NEAT_SYNC:-ON}"
  local sync_required="${DEVKIT_NEAT_SYNC_REQUIRED:-OFF}"
  local sysroot="${SYSROOT:-/opt/toolchain/aarch64/modalix}"
  local cache_dir="${DEVKIT_NEAT_SYNC_CACHE_DIR:-${sysroot}/neat-install-packages}"
  local c_yellow="" c_green="" c_reset=""

  if [[ -t 2 ]]; then
    c_yellow=$'\033[1;33m'
    c_reset=$'\033[0m'
  fi
  if [[ -t 1 ]]; then
    c_green=$'\033[1;32m'
    c_reset=$'\033[0m'
  fi

  neat_sync_warn() {
    printf "%b%s%b\n" "${c_yellow}" "$*" "${c_reset}" >&2
  }

  neat_sync_fail_or_continue() {
    local msg="$1"
    neat_sync_warn "${msg}"
    if [[ "${sync_required}" == "ON" ]]; then
      return 1
    fi
    return 0
  }

  case "${sync_enabled}" in
    OFF|off|0|false|FALSE|no|NO)
      echo "Neat framework DevKit sync disabled by DEVKIT_NEAT_SYNC=${sync_enabled}."
      return 0
      ;;
  esac

  echo "Checking Neat framework versions between SDK and DevKit..."

  if [[ ! -d "${cache_dir}" ]]; then
    neat_sync_fail_or_continue "WARNING: Neat framework SDK cache not found: ${cache_dir}"
    return $?
  fi
  if [[ ! -f "${cache_dir}/install_neat_framework.sh" ]]; then
    neat_sync_fail_or_continue "WARNING: Neat framework installer missing from SDK cache: ${cache_dir}/install_neat_framework.sh"
    return $?
  fi
  if ! command -v dpkg-deb >/dev/null 2>&1; then
    neat_sync_fail_or_continue "WARNING: dpkg-deb is required to inspect SDK Neat framework package versions."
    return $?
  fi
  if ! command -v scp >/dev/null 2>&1; then
    neat_sync_fail_or_continue "WARNING: scp is required to copy Neat framework install artifacts to the DevKit."
    return $?
  fi

  local -a deb_files=()
  local -a wheel_files=()
  mapfile -t deb_files < <(find "${cache_dir}" -maxdepth 1 -type f \( -name 'sima-neat-*-Linux-core.deb' -o -name 'neat-*.deb' \) | sort)
  mapfile -t wheel_files < <(find "${cache_dir}" -maxdepth 1 -type f -name '*.whl' | sort)

  if [[ "${#deb_files[@]}" -lt 1 ]]; then
    neat_sync_fail_or_continue "WARNING: No Neat framework deb packages found in SDK cache: ${cache_dir}"
    return $?
  fi
  if [[ "${#wheel_files[@]}" -lt 1 ]]; then
    neat_sync_fail_or_continue "WARNING: No Neat framework Python wheel found in SDK cache: ${cache_dir}"
    return $?
  fi
  if [[ "${#wheel_files[@]}" -gt 1 ]]; then
    neat_sync_warn "WARNING: Multiple wheels found in SDK cache; using $(basename "${wheel_files[0]}")."
  fi

  local -a expected_entries=()
  local -a expected_deb_names=()
  local deb pkg version wheel_file wheel_base wheel_name wheel_version
  for deb in "${deb_files[@]}"; do
    pkg="$(dpkg-deb -f "${deb}" Package 2>/dev/null || true)"
    version="$(dpkg-deb -f "${deb}" Version 2>/dev/null || true)"
    if [[ -z "${pkg}" || -z "${version}" ]]; then
      neat_sync_fail_or_continue "WARNING: Could not read package metadata from $(basename "${deb}")."
      return $?
    fi
    expected_entries+=("deb|${pkg}|${version}|$(basename "${deb}")")
    expected_deb_names+=("${pkg}")
  done

  wheel_file="${wheel_files[0]}"
  wheel_base="$(basename "${wheel_file}")"
  wheel_base="${wheel_base%.whl}"
  wheel_name="${wheel_base%%-*}"
  wheel_version="${wheel_base#*-}"
  wheel_version="${wheel_version%%-*}"
  if [[ -z "${wheel_name}" || -z "${wheel_version}" || "${wheel_name}" == "${wheel_base}" ]]; then
    neat_sync_fail_or_continue "WARNING: Could not parse Python wheel name/version from $(basename "${wheel_file}")."
    return $?
  fi
  expected_entries+=("wheel|${wheel_name}|${wheel_version}|$(basename "${wheel_file}")")

  query_devkit_neat_versions() {
    ssh -T -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${user}@${ip}" bash -s -- "${wheel_name}" "${expected_deb_names[@]}" <<'EOS'
set -euo pipefail
wheel_name="$1"
shift || true

for pkg in "$@"; do
  if version="$(dpkg-query -W -f='${Version}' "${pkg}" 2>/dev/null)"; then
    printf 'deb|%s|%s\n' "${pkg}" "${version}"
  else
    printf 'deb|%s|missing\n' "${pkg}"
  fi
done

wheel_version="missing"
py="${HOME}/pyneat/bin/python"
if [[ -x "${py}" ]]; then
  if version="$("${py}" - "${wheel_name}" 2>/dev/null <<'PY'
import importlib.metadata
import sys

try:
    print(importlib.metadata.version(sys.argv[1]))
except importlib.metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
)"; then
    if [[ -n "${version}" ]]; then
      wheel_version="${version}"
    fi
  fi

  if [[ "${wheel_version}" == "missing" ]]; then
    if version="$("${py}" -m pip show "${wheel_name}" 2>/dev/null | awk -F': ' '/^Version:/ { print $2; exit }' || true)"; then
      if [[ -n "${version}" ]]; then
        wheel_version="${version}"
      fi
    fi
  fi
fi

printf 'wheel|%s|%s\n' "${wheel_name}" "${wheel_version}"
EOS
  }

  local -a actual_entries=()
  local actual_output=""
  if ! actual_output="$(query_devkit_neat_versions)"; then
    neat_sync_warn "WARNING: Could not query NEAT framework versions from DevKit; treating DevKit as out of sync."
    actual_entries=()
  elif [[ -n "${actual_output}" ]]; then
    mapfile -t actual_entries <<< "${actual_output}"
  fi

  compare_neat_versions() {
    local -n _actual_entries_ref="$1"
    local -n _mismatch_lines_ref="$2"
    local -n _match_lines_ref="$3"
    local -A actual_versions=()
    local entry type name expected file actual

    for entry in "${_actual_entries_ref[@]}"; do
      IFS='|' read -r type name actual <<< "${entry}"
      [[ -n "${type}" && -n "${name}" ]] || continue
      actual_versions["${type}|${name}"]="${actual:-missing}"
    done

    for entry in "${expected_entries[@]}"; do
      IFS='|' read -r type name expected file <<< "${entry}"
      actual="${actual_versions["${type}|${name}"]:-missing}"
      if [[ "${actual}" == "${expected}" ]]; then
        _match_lines_ref+=("  ${type} ${name}: ${expected}")
      else
        _mismatch_lines_ref+=("  ${type} ${name}: SDK=${expected}, DevKit=${actual}")
      fi
    done
  }

  local -a mismatch_lines=()
  local -a match_lines=()
  compare_neat_versions actual_entries mismatch_lines match_lines

  print_neat_sync_success() {
    {
      printf "%bNEAT framework versions are in sync between SDK and DevKit.\n" "${c_green}"
      printf '%s\n' "${match_lines[@]}"
      printf "%b" "${c_reset}"
    }
  }

  if [[ "${#mismatch_lines[@]}" -eq 0 ]]; then
    print_neat_sync_success
    return 0
  fi

  {
    printf "%bNeat framework is out of sync between SDK and DevKit.\n" "${c_yellow}"
    printf '%s\n' "${mismatch_lines[@]}"
    if [[ "${#match_lines[@]}" -gt 0 ]]; then
      printf "\nAlready in sync:\n"
      printf '%s\n' "${match_lines[@]}"
    fi
    printf "\nInstalling SDK Neat framework packages on the DevKit...%b\n" "${c_reset}"
  } >&2

  local remote_dir="/tmp/sima-neat-install-$(date +%Y%m%d-%H%M%S)"
  local -a deploy_files=("${deb_files[@]}" "${wheel_file}" "${cache_dir}/install_neat_framework.sh")

  if ! ssh -T -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${user}@${ip}" "mkdir -p '${remote_dir}'"; then
    neat_sync_fail_or_continue "WARNING: Failed to create Neat framework install directory on DevKit: ${remote_dir}"
    return $?
  fi

  if ! scp -P "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${deploy_files[@]}" "${user}@${ip}:${remote_dir}/"; then
    ssh -T -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${user}@${ip}" "rm -rf '${remote_dir}'" >/dev/null 2>&1 || true
    neat_sync_fail_or_continue "WARNING: Failed to copy Neat framework install artifacts to DevKit."
    return $?
  fi

  local remote_install_cmd
  remote_install_cmd="set -euo pipefail
remote_dir=$(printf '%q' "${remote_dir}")
cleanup_remote_artifacts() {
  rm -rf \"\${remote_dir}\"
}
trap cleanup_remote_artifacts EXIT
chmod +x \"\${remote_dir}/install_neat_framework.sh\"
cd \"\${remote_dir}\"
NEAT_INSTALLER_SKIP_DEVKIT_SYNC=ON bash ./install_neat_framework.sh --local"

  local -a ssh_install_args=(ssh -p "${port}" -o BatchMode=yes -o ConnectTimeout=8)
  if [[ -t 0 && -t 1 ]]; then
    ssh_install_args+=(-t)
  else
    ssh_install_args+=(-T)
  fi
  ssh_install_args+=("${user}@${ip}" "bash -lc $(printf '%q' "${remote_install_cmd}")")

  if ! "${ssh_install_args[@]}"; then
    ssh -T -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${user}@${ip}" "rm -rf '${remote_dir}'" >/dev/null 2>&1 || true
    neat_sync_fail_or_continue "WARNING: Failed to install SDK NEAT framework packages on DevKit."
    return $?
  fi

  actual_entries=()
  actual_output=""
  if ! actual_output="$(query_devkit_neat_versions)"; then
    neat_sync_fail_or_continue "WARNING: Could not verify NEAT framework versions after DevKit install."
    return $?
  elif [[ -n "${actual_output}" ]]; then
    mapfile -t actual_entries <<< "${actual_output}"
  fi

  mismatch_lines=()
  match_lines=()
  compare_neat_versions actual_entries mismatch_lines match_lines
  if [[ "${#mismatch_lines[@]}" -eq 0 ]]; then
    print_neat_sync_success
    return 0
  fi

  {
    printf "%bWARNING: NEAT framework versions are still out of sync after DevKit install.\n" "${c_yellow}"
    printf '%s\n' "${mismatch_lines[@]}"
    printf "%b" "${c_reset}"
  } >&2
  if [[ "${sync_required}" == "ON" ]]; then
    return 1
  fi
  return 0
}

copy_insight_port_map_to_devkit() {
  local user="$1"
  local ip="$2"
  local port="$3"
  local local_port_map="${HOME}/.insight-config/neat-port-map.json"
  local remote_config_dir=".insight-config"
  local remote_port_map="${remote_config_dir}/neat-port-map.json"
  local c_yellow="" c_green="" c_reset=""

  if [[ ! -f "${local_port_map}" ]]; then
    return 0
  fi

  if [[ -t 2 ]]; then
    c_yellow=$'\033[1;33m'
    c_reset=$'\033[0m'
  fi
  if [[ -t 1 ]]; then
    c_green=$'\033[1;32m'
    c_reset=$'\033[0m'
  fi

  if ! command -v scp >/dev/null 2>&1; then
    printf "%bWARNING:%b scp is required to copy Insight port map to DevKit.\n" "${c_yellow}" "${c_reset}" >&2
    return 0
  fi

  echo "Copying Insight port map to DevKit ${user}@${ip}:${remote_port_map}"
  if ! ssh -T -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${user}@${ip}" "mkdir -p '${remote_config_dir}'"; then
    printf "%bWARNING:%b Failed to create DevKit Insight config directory: ~/%s\n" "${c_yellow}" "${c_reset}" "${remote_config_dir}" >&2
    return 0
  fi

  if ! scp -P "${port}" -o BatchMode=yes -o ConnectTimeout=8 "${local_port_map}" "${user}@${ip}:${remote_port_map}"; then
    printf "%bWARNING:%b Failed to copy Insight port map to DevKit: ~/%s\n" "${c_yellow}" "${c_reset}" "${remote_port_map}" >&2
    return 0
  fi

  printf "%bInsight port map copied to DevKit: ~/%s%b\n" "${c_green}" "${remote_port_map}" "${c_reset}"
  return 0
}

_DEVKIT_IP="${1:-${DEVKIT_SYNC_DEVKIT_IP:-}}"
_DEVKIT_USER="${2:-sima}"
_DEVKIT_PORT="${3:-22}"
_HOST_IP="${NFS_SERVER_HOST_IP:-}"
_HOST_EXPORT_PATH="${DEVKIT_HOST_EXPORT_PATH:-}"
_HOST_PLATFORM="${DEVKIT_HOST_PLATFORM:-linux}"
_DEFAULT_MOUNT_PATH="${DEVKIT_SYNC_MOUNT_PATH:-/workspace}"

if [[ -z "${_HOST_IP}" || -z "${_HOST_EXPORT_PATH}" ]]; then
  echo "Missing host export info in environment." >&2
  echo "Expected NFS_SERVER_HOST_IP and DEVKIT_HOST_EXPORT_PATH (set by run.py)." >&2
  return 1
fi

if [[ ! "${_DEVKIT_PORT}" =~ ^[0-9]+$ ]] || (( _DEVKIT_PORT < 1 || _DEVKIT_PORT > 65535 )); then
  echo "Invalid port: ${_DEVKIT_PORT}" >&2
  return 2
fi

_c_info="" _c_reset=""
if [[ -t 1 ]]; then
  _c_info=$'\033[1;34m'
  _c_reset=$'\033[0m'
fi
cat <<EOF
${_c_info}
============================================================
  Setting Up DevKit Connection
  eLxr SDK container  ->  DevKit
============================================================
${_c_reset}
EOF

printf "\nDevKit NFS client setup\n"
printf "DevKit: %s@%s:%s\n" "${_DEVKIT_USER}" "${_DEVKIT_IP}" "${_DEVKIT_PORT}"
printf "Host export: %s:%s\n" "${_HOST_IP}" "${_HOST_EXPORT_PATH}"
printf "Reminder: NFS workspace is shared bi-directionally.\n\n"

read -r -p "Destination mount path on DevKit [${_DEFAULT_MOUNT_PATH}]: " _MOUNT_POINT
_MOUNT_POINT="${_MOUNT_POINT:-${_DEFAULT_MOUNT_PATH}}"
if [[ "${_MOUNT_POINT}" != /* ]]; then
  echo "Please provide an absolute path (must start with '/')." >&2
  return 2
fi
if [[ "${_HOST_PLATFORM}" == "darwin" ]]; then
  _NFS_OPTS="vers=3,proto=tcp,mountproto=tcp,nolock,soft,timeo=50,retrans=1,_netdev,nofail,x-systemd.automount"
else
  _NFS_OPTS="vers=4,proto=tcp,soft,timeo=50,retrans=1,_netdev,nofail,x-systemd.automount"
fi

mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"
if [[ ! -f "${HOME}/.ssh/id_ed25519" ]]; then
  ssh-keygen -t ed25519 -N "" -f "${HOME}/.ssh/id_ed25519" -C "devkit-sync@$(hostname)" >/dev/null
fi
ssh-keyscan -H -p "${_DEVKIT_PORT}" "${_DEVKIT_IP}" >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true
chmod 600 "${HOME}/.ssh/known_hosts"

echo "Installing/refreshing SSH key for ${_DEVKIT_USER}@${_DEVKIT_IP}"
if ! timeout --foreground 120 ssh-copy-id -i "${HOME}/.ssh/id_ed25519.pub" -p "${_DEVKIT_PORT}" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "${_DEVKIT_USER}@${_DEVKIT_IP}"; then
  echo "Failed to install SSH key for ${_DEVKIT_USER}@${_DEVKIT_IP}:${_DEVKIT_PORT}." >&2
  echo "Hint: verify the DevKit IP/port, that SSH is running, and that the user is reachable before retrying." >&2
  return 1
fi

check_devkit_sdk_version_compatibility "${_DEVKIT_USER}" "${_DEVKIT_IP}" "${_DEVKIT_PORT}"

if [[ "${_DEVKIT_USER}" != "root" ]]; then
  if ! check_remote_passwordless_sudo "${_DEVKIT_USER}" "${_DEVKIT_IP}" "${_DEVKIT_PORT}"; then
    echo ""
    echo "DevKit user '${_DEVKIT_USER}' does not have passwordless sudo."
    echo "This script can apply a one-time sudoers change:"
    echo "  ${_DEVKIT_USER} ALL=(ALL) NOPASSWD:ALL"
    read -r -p "Apply this change on ${_DEVKIT_IP}? [y/N]: " _ALLOW_NOPASSWD
    case "${_ALLOW_NOPASSWD,,}" in
      y|yes)
        echo "Applying passwordless sudo setup for ${_DEVKIT_USER}@${_DEVKIT_IP}."
        _REMOTE_SUDO_PASSWORD=""
        read -r -s -p "Enter sudo password for ${_DEVKIT_USER}@${_DEVKIT_IP}: " _REMOTE_SUDO_PASSWORD
        echo ""
        if [[ -z "${_REMOTE_SUDO_PASSWORD}" ]]; then
          echo "Remote sudo password is required." >&2
          return 1
        fi
        if ! timeout --foreground 120 ssh -T -p "${_DEVKIT_PORT}" -o ConnectTimeout=8 "${_DEVKIT_USER}@${_DEVKIT_IP}" bash -s -- "${_DEVKIT_USER}" "${_REMOTE_SUDO_PASSWORD}" <<'EOS'
set -euo pipefail
u="$1"
pw="$2"
sudoers_line="${u} ALL=(ALL) NOPASSWD:ALL"
tmp_sudoers="$(mktemp)"
run_sudo() {
  printf '%s\n' "${pw}" | sudo -S -p '' "$@"
}
echo "[devkit] validating sudo access for ${u}..."
run_sudo -v
run_sudo mkdir -p /etc/sudoers.d
printf '%s\n' "${sudoers_line}" > "${tmp_sudoers}"
run_sudo install -m 0440 "${tmp_sudoers}" "/etc/sudoers.d/90-${u}-nopasswd"
run_sudo visudo -cf "/etc/sudoers.d/90-${u}-nopasswd"
run_sudo grep -qxF "${sudoers_line}" "/etc/sudoers.d/90-${u}-nopasswd"
sudo -n true
rm -f "${tmp_sudoers}"
EOS
        then
          echo "Failed to configure passwordless sudo for ${_DEVKIT_USER}@${_DEVKIT_IP}." >&2
          echo "Hint: confirm the remote sudo password is correct and retry, or rerun as root user." >&2
          return 1
        fi
        echo "Passwordless sudo configured successfully for ${_DEVKIT_USER}@${_DEVKIT_IP}."
        ;;
      *)
        echo "Passwordless sudo setup skipped by user." >&2
        echo "Hint: rerun as root user: source devkit.sh ${_DEVKIT_IP} root ${_DEVKIT_PORT}" >&2
        return 1
        ;;
    esac
  fi
fi

if ! sync_neat_framework_to_devkit "${_DEVKIT_USER}" "${_DEVKIT_IP}" "${_DEVKIT_PORT}"; then
  return 1
fi

echo "Configuring remote NFS mount..."
if ! ssh -T -p "${_DEVKIT_PORT}" -o BatchMode=yes -o ConnectTimeout=8 "${_DEVKIT_USER}@${_DEVKIT_IP}" bash -s -- "${_HOST_IP}" "${_HOST_EXPORT_PATH}" "${_MOUNT_POINT}" "${_NFS_OPTS}" "${_DEVKIT_USER}" <<'EOS'
set -euo pipefail
host_ip="$1"
host_export="$2"
mount_point="$3"
mount_opts="$4"
remote_user="$5"

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
elif sudo -n true >/dev/null 2>&1; then
  SUDO="sudo"
else
  echo "ERROR: remote user requires sudo password but non-interactive SSH was requested." >&2
  echo "Use passwordless sudo for this user, or rerun with root user." >&2
  exit 10
fi

as_root() {
  if [[ -n "${SUDO}" ]]; then
    sudo "$@"
  else
    "$@"
  fi
}

if ! dpkg -s nfs-common >/dev/null 2>&1; then
  as_root apt-get update --allow-releaseinfo-change
  as_root apt-get install -y --no-install-recommends nfs-common
fi

as_root mkdir -p "$mount_point"

# Always clear stale mounts from this host first (avoids blocked hard mounts).
if command -v findmnt >/dev/null 2>&1; then
  while read -r tgt; do
    [[ -n "${tgt}" ]] || continue
    echo "[devkit] unmounting stale NFS mount ${tgt} from ${host_ip}:*"
    as_root umount -lf "$tgt" || true
  done < <(findmnt -rn -t nfs,nfs4 -o TARGET,SOURCE | awk -v h="${host_ip}:" '$2 ~ ("^" h) {print $1}')
fi

# Ensure requested target mountpoint is detached as well.
if mountpoint -q "$mount_point"; then
  as_root umount -lf "$mount_point" || true
fi

src="${host_ip}:${host_export}"
as_root mount -t nfs -o "$mount_opts" "$src" "$mount_point"

# Persist fstab entry.
tmpf="$(mktemp)"
# Drop any stale entries for this source or mountpoint (any fs type/options).
awk -v s="${src}" -v m="${mount_point}" '
  /^[[:space:]]*#/ || NF==0 { print; next }
  ($1 == s) || ($2 == m) { next }
  { print }
' /etc/fstab > "$tmpf"
echo "${src} ${mount_point} nfs ${mount_opts} 0 0" >> "$tmpf"
as_root cp "$tmpf" /etc/fstab
rm -f "$tmpf"

# Ensure systemd sees the new fstab before future reconnect/reboot cycles.
as_root systemctl daemon-reload >/dev/null 2>&1 || true

# Install a lightweight watchdog to recover stale mounts automatically.
watchdog_script="/usr/local/sbin/devkit-nfs-watchdog.sh"
as_root install -d -m 0755 /usr/local/sbin
as_root tee "$watchdog_script" >/dev/null <<EOF
#!/usr/bin/env bash
set -euo pipefail
mp="${mount_point}"
src="${src}"
opts="${mount_opts}"
timeout 5 stat "\${mp}/." >/dev/null 2>&1 && exit 0
umount -lf "\${mp}" >/dev/null 2>&1 || true
mount -t nfs -o "\${opts}" "\${src}" "\${mp}"
EOF
as_root chmod 0755 "$watchdog_script"

as_root tee /etc/systemd/system/devkit-nfs-watchdog.service >/dev/null <<'EOF'
[Unit]
Description=DevKit NFS watchdog remount
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/devkit-nfs-watchdog.sh
EOF

as_root tee /etc/systemd/system/devkit-nfs-watchdog.timer >/dev/null <<'EOF'
[Unit]
Description=Run DevKit NFS watchdog every minute

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
Unit=devkit-nfs-watchdog.service
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF

as_root systemctl daemon-reload >/dev/null 2>&1 || true
as_root systemctl enable --now devkit-nfs-watchdog.timer >/dev/null 2>&1 || true

# Validate effective runtime mount options.
if command -v findmnt >/dev/null 2>&1; then
  eff_opts="$(findmnt -rn -o OPTIONS --target "$mount_point" || true)"
  echo "[devkit] effective mount opts: ${eff_opts}"
  if [[ "${eff_opts}" != *"soft"* ]]; then
    echo "[devkit] WARNING: effective mount does not include 'soft' (old mount options may still be active)" >&2
  fi
fi
echo "[devkit] watchdog: devkit-nfs-watchdog.timer enabled (60s interval)"

# Git safety: mark NFS workspace safe for the target user to avoid dubious ownership errors.
if command -v git >/dev/null 2>&1; then
  if [[ -n "${SUDO}" ]]; then
    sudo -u "${remote_user}" git config --global --add safe.directory "${mount_point}" || true
    sudo -u "${remote_user}" git config --global --add safe.directory "${mount_point}/*" || true
  else
    git config --global --add safe.directory "${mount_point}" || true
    git config --global --add safe.directory "${mount_point}/*" || true
  fi
  echo "[devkit] git safe.directory configured for ${remote_user}: ${mount_point} and ${mount_point}/*"
fi
EOS
then
  echo "Failed to configure NFS mount on ${_DEVKIT_USER}@${_DEVKIT_IP}." >&2
  echo "Hint: ensure ${_DEVKIT_USER} has passwordless sudo, or rerun as root: source devkit.sh ${_DEVKIT_IP} root ${_DEVKIT_PORT}" >&2
  return 1
fi

export DEVKIT_SYNC_TARGET="${_DEVKIT_IP}:${_MOUNT_POINT}"
export DEVKIT_SYNC_DEVKIT_IP="${_DEVKIT_IP}"
if [[ -z "${DEVKIT_SYNC_ORIG_PS1:-}" ]]; then
  export DEVKIT_SYNC_ORIG_PS1="${PS1:-\u@\h:\w\$ }"
fi
_PS1_PREFIX="\[\e[1;32m\][DevKit ${DEVKIT_SYNC_TARGET}]\[\e[0m\] "
export DEVKIT_PROMPT_DIRTRIM="${DEVKIT_PROMPT_DIRTRIM:-3}"
export PROMPT_DIRTRIM="${DEVKIT_PROMPT_DIRTRIM}"
export PS1="${_PS1_PREFIX}${DEVKIT_SYNC_ORIG_PS1}"
export DEVKIT_SYNC_MOUNT_POINT="${_MOUNT_POINT}"
export DEVKIT_SYNC_DEVKIT_USER="${_DEVKIT_USER}"
export DEVKIT_SYNC_DEVKIT_PORT="${_DEVKIT_PORT}"
export SDK_IMAGE_TAG="${SDK_IMAGE_TAG:-version}"
export SDK_PROMPT_HOSTNAME="${SDK_PROMPT_HOSTNAME:-neat-sdk-${SDK_IMAGE_TAG}}"

__devkit_rewrite_prompt_hostname() {
  local prompt="${1-}"
  prompt="${prompt//\\h/${SDK_PROMPT_HOSTNAME}}"
  prompt="${prompt//\\H/${SDK_PROMPT_HOSTNAME}}"
  printf '%s' "${prompt}"
}

if [[ -z "${DEVKIT_SYNC_ORIG_PS1:-}" ]]; then
  export DEVKIT_SYNC_ORIG_PS1="$(__devkit_rewrite_prompt_hostname "${PS1:-\u@\h:\w\$ }")"
else
  export DEVKIT_SYNC_ORIG_PS1="$(__devkit_rewrite_prompt_hostname "${DEVKIT_SYNC_ORIG_PS1}")"
fi

export PS1="$(__devkit_rewrite_prompt_hostname "${PS1:-${DEVKIT_SYNC_ORIG_PS1}}")"

echo ""
echo "NFS client mount configured."
echo "Target: ${DEVKIT_SYNC_TARGET}"

# Run a local /workspace binary or Python script on the paired DevKit.
devkit-run() {
  if [[ $# -lt 1 ]]; then
    echo "Usage: devkit-run <local-executable-path|shell> [args...]" >&2
    return 2
  fi

  local local_path="$1"
  shift

  if [[ "${local_path}" == "shell" ]]; then
    local -a ssh_args=(
      ssh
      -p "${DEVKIT_SYNC_DEVKIT_PORT}"
      -o BatchMode=yes -o ConnectTimeout=8 \
    )
    if [[ $# -eq 0 && -t 0 && -t 1 ]]; then
      ssh_args+=(-t)
    fi
    ssh_args+=("${DEVKIT_SYNC_DEVKIT_USER:-sima}@${DEVKIT_SYNC_DEVKIT_IP}")
    ssh_args+=("$@")
    "${ssh_args[@]}"
    return $?
  fi

  if [[ "${local_path}" != /* ]]; then
    local_path="$(pwd)/${local_path}"
  fi

  if [[ ! -f "${local_path}" ]]; then
    echo "Not found: ${local_path}" >&2
    return 2
  fi

  local is_python="0"
  if [[ "${local_path}" == *.py ]]; then
    is_python="1"
  fi

  if [[ "${is_python}" != "1" ]]; then
    local ftype
    ftype="$(file -b "${local_path}" 2>/dev/null || true)"
    if [[ "${ftype}" != *"aarch64"* && "${ftype}" != *"ARM aarch64"* && "${ftype}" != *"ARM64"* ]]; then
      echo "Refusing to run non-ARM64 binary: ${local_path}" >&2
      echo "Detected type: ${ftype}" >&2
      return 2
    fi
  fi

  case "${local_path}" in
    /workspace/*) ;;
    *)
      echo "Path must be inside /workspace so DevKit can access it via NFS." >&2
      return 2
      ;;
  esac

  local rel remote_path pyneat_activate
  rel="${local_path#/workspace/}"
  remote_path="${DEVKIT_SYNC_MOUNT_POINT}/${rel}"
  pyneat_activate="${DEVKIT_PYNEAT_ACTIVATE:-__NONE__}"
  local host_pwd remote_args arg
  host_pwd="$(pwd)"
  remote_args=("${remote_path}" "${pyneat_activate}")

  normalize_devkit_host_path() {
    local input="$1"
    local part
    local -a parts=()
    local -a normalized_parts=()

    if [[ "${input}" != /* ]]; then
      input="${host_pwd}/${input}"
    fi

    IFS='/' read -r -a parts <<< "${input#/}"
    for part in "${parts[@]}"; do
      case "${part}" in
        ""|".")
          continue
          ;;
        "..")
          if (( ${#normalized_parts[@]} > 0 )); then
            unset 'normalized_parts[${#normalized_parts[@]}-1]'
          fi
          ;;
        *)
          normalized_parts+=("${part}")
          ;;
      esac
    done

    if (( ${#normalized_parts[@]} == 0 )); then
      printf '/\n'
      return 0
    fi

    local joined
    printf -v joined '%s/' "${normalized_parts[@]}"
    printf '/%s\n' "${joined%/}"
  }

  map_devkit_arg_path() {
    local raw="$1"
    local prefix=""
    local value="${raw}"
    local candidate=""
    local normalized=""
    local looks_like_path="0"

    case "${raw}" in
      --*=*)
        prefix="${raw%%=*}="
        value="${raw#*=}"
        ;;
    esac

    case "${value}" in
      ""|"-"|--*|http://*|https://*|rtsp://*|rtmp://*|udp://*|tcp://*|file://*)
        printf '%s\n' "${raw}"
        return 0
        ;;
    esac

    case "${value}" in
      /*|./*|../*|*/*)
        looks_like_path="1"
        ;;
    esac

    if [[ "${looks_like_path}" == "1" ]]; then
      normalized="$(normalize_devkit_host_path "${value}")"
    elif [[ -e "${host_pwd}/${value}" ]]; then
      normalized="$(normalize_devkit_host_path "${value}")"
    else
      printf '%s\n' "${raw}"
      return 0
    fi

    if [[ -n "${DEVKIT_RUN_DEBUG:-}" ]]; then
      printf "%b[DevKit][debug]%b host_pwd=%q raw=%q normalized=%q\n" \
        "${c_out:-}" "${c_reset:-}" "${host_pwd}" "${raw}" "${normalized}" >&2
    fi

    case "${normalized}" in
      /workspace/*)
        printf '%s%s\n' "${prefix}" "${DEVKIT_SYNC_MOUNT_POINT}/${normalized#/workspace/}"
        ;;
      *)
        printf '%s\n' "${raw}"
        ;;
    esac
  }

  for arg in "$@"; do
    remote_args+=("$(map_devkit_arg_path "${arg}")")
  done

  local c_out="" c_stderr="" c_reset=""
  if [[ -t 1 ]]; then
    c_out=$'\033[1;36m'
    c_stderr=$'\033[1;33m'
    c_reset=$'\033[0m'
  fi

  printf "%b[DevKit]%b executing remotely on %s@%s:%s -> %s\n" \
    "${c_out}" "${c_reset}" "${DEVKIT_SYNC_DEVKIT_USER}" "${DEVKIT_SYNC_DEVKIT_IP}" "${DEVKIT_SYNC_DEVKIT_PORT}" "${remote_path}"
  printf "%b[DevKit]%b argv:" "${c_out}" "${c_reset}"
  for arg in "${remote_args[@]}"; do
    printf " %q" "${arg}"
  done
  printf "\n"

  cleanup_remote_target() {
    ssh -p "${DEVKIT_SYNC_DEVKIT_PORT}" \
      -o BatchMode=yes -o ConnectTimeout=5 \
      "${DEVKIT_SYNC_DEVKIT_USER}@${DEVKIT_SYNC_DEVKIT_IP}" \
      bash --noprofile --norc -s -- "${remote_path}" >/dev/null 2>&1 <<'EOS_KILL'
set -euo pipefail
target="$1"
base="$(basename "${target}")"
pkill -TERM -f "${target}" >/dev/null 2>&1 || true
pkill -TERM -f "python3 ${target}" >/dev/null 2>&1 || true
pkill -TERM -f "${base}" >/dev/null 2>&1 || true
sleep 1
pkill -KILL -f "${target}" >/dev/null 2>&1 || true
pkill -KILL -f "python3 ${target}" >/dev/null 2>&1 || true
pkill -KILL -f "${base}" >/dev/null 2>&1 || true
EOS_KILL
  }
  __devkit_interrupted=0
  __devkit_on_interrupt() {
    __devkit_interrupted=1
    cleanup_remote_target
  }
  trap __devkit_on_interrupt INT TERM

  ssh -T -p "${DEVKIT_SYNC_DEVKIT_PORT}" \
    -o BatchMode=yes -o ConnectTimeout=8 \
    "${DEVKIT_SYNC_DEVKIT_USER}@${DEVKIT_SYNC_DEVKIT_IP}" \
    bash --noprofile --norc -s -- "${remote_args[@]}" \
    > >(while IFS= read -r line; do printf "%b[DEVKIT][STDOUT]%b %s\n" "${c_out}" "${c_reset}" "${line}"; done) \
    2> >(while IFS= read -r line; do printf "%b[DEVKIT][STDERR]%b %s\n" "${c_stderr}" "${c_reset}" "${line}" >&2; done) <<'EOS'
# Keep TTY for reliable Ctrl+C forwarding, but suppress verbose/xtrace shell echo.
set +x +v
set -euo pipefail
unset PROMPT_COMMAND
PS1=
__tty_echo_disabled=0
if [[ -t 0 ]]; then
  stty -echo >/dev/null 2>&1 || true
  __tty_echo_disabled=1
fi
__restore_tty() {
  if [[ "${__tty_echo_disabled}" -eq 1 ]]; then
    stty echo >/dev/null 2>&1 || true
  fi
}
trap __restore_tty EXIT INT TERM HUP
target="${1:?missing target path}"
pyneat_activate="${2-}"
if [[ "${pyneat_activate}" == "__NONE__" ]]; then
  pyneat_activate=""
fi
if [[ $# -ge 2 ]]; then
  shift 2
else
  shift 1
fi

ensure_target_ready() {
  local p="$1"
  [[ -e "${p}" ]] && return 0

  local mount_root seg
  seg="$(printf "%s" "${p#/}" | cut -d/ -f1)"
  mount_root="/${seg}"

  # Best effort: ask watchdog to recover stale NFS mount.
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo systemctl start devkit-nfs-watchdog.service >/dev/null 2>&1 || true
  fi
  sleep 1
  [[ -e "${p}" ]] && return 0

  echo "ERROR: target not accessible on DevKit: ${p}" >&2
  mount | grep " ${mount_root} " >&2 || true
  return 1
}

ensure_target_ready "${target}"

prepare_command() {
  if [[ "${target}" == *.py ]]; then
    script_args=("$@")
    activated="0"
    if [[ -n "${pyneat_activate}" && -f "${pyneat_activate}" ]]; then
      # shellcheck source=/dev/null
      source "${pyneat_activate}"
      activated="1"
    else
      for candidate in \
        "/media/nvme/pyneat/bin/activate" \
        "${HOME}/pyneat/bin/activate" \
        "${HOME}/.pyneat/bin/activate" \
        "/opt/pyneat/bin/activate" \
        "/opt/sima/pyneat/bin/activate" \
        "/opt/sima.ai/pyneat/bin/activate"; do
        if [[ -f "${candidate}" ]]; then
          # shellcheck source=/dev/null
          source "${candidate}"
          activated="1"
          break
        fi
      done
    fi
    if [[ "${activated}" != "1" ]]; then
      echo "WARNING: pyneat activate script not found; running python3 without pyneat env" >&2
    fi
    # Some activation scripts consume/shift positional parameters; restore them.
    set -- "${script_args[@]}"
    CMD=(python3 "${target}" "$@")
    return 0
  fi

  chmod +x "${target}"
  CMD=("${target}" "$@")
}

CMD=()
prepare_command "$@"
# Run in foreground so Ctrl+C/SIGINT from SSH is delivered to the actual target.
exec "${CMD[@]}"
EOS
  rc=$?
  if [[ "${__devkit_interrupted}" -eq 1 || "${rc}" -eq 130 || "${rc}" -eq 143 || "${rc}" -eq 255 ]]; then
    cleanup_remote_target
  fi
  trap - INT TERM
  return "${rc}"
}

# Short-hand for remote execution: dk <path> [args...]
unalias dk >/dev/null 2>&1 || true
dk() {
  if [[ $# -lt 1 ]]; then
    echo "Usage: dk <local-executable-path|shell> [args...]" >&2
    return 0
  fi
  devkit-run "$@"
}

# Persist session helpers for future container shells.
_persist_file="${HOME}/.devkit-sync.rc"
{
  echo "export DEVKIT_SYNC_TARGET='${DEVKIT_SYNC_TARGET}'"
  echo "export DEVKIT_SYNC_DEVKIT_IP='${DEVKIT_SYNC_DEVKIT_IP}'"
  echo "export DEVKIT_SYNC_MOUNT_POINT='${DEVKIT_SYNC_MOUNT_POINT}'"
  echo "export DEVKIT_SYNC_DEVKIT_USER='${DEVKIT_SYNC_DEVKIT_USER}'"
  echo "export DEVKIT_SYNC_DEVKIT_PORT='${DEVKIT_SYNC_DEVKIT_PORT}'"
  echo "export SDK_IMAGE_TAG='${SDK_IMAGE_TAG}'"
  echo "export SDK_PROMPT_HOSTNAME='${SDK_PROMPT_HOSTNAME}'"
  echo "export DEVKIT_PROMPT_DIRTRIM='${DEVKIT_PROMPT_DIRTRIM}'"
  echo 'export PROMPT_DIRTRIM="${DEVKIT_PROMPT_DIRTRIM}"'
  echo 'export DEVKIT_SYNC_PROMPT_PREFIX="\[\e[1;32m\][DevKit ${DEVKIT_SYNC_TARGET}]\[\e[0m\] "'
  echo '__devkit_rewrite_prompt_hostname() {'
  echo '  local prompt="${1-}"'
  echo '  prompt="${prompt//\\h/${SDK_PROMPT_HOSTNAME}}"'
  echo '  prompt="${prompt//\\H/${SDK_PROMPT_HOSTNAME}}"'
  echo '  printf "%s" "${prompt}"'
  echo '}'
  echo '__devkit_apply_prompt() {'
  echo '  local marker="[DevKit ${DEVKIT_SYNC_TARGET}]"'
  echo '  if [[ -z "${DEVKIT_SYNC_ORIG_PS1:-}" ]]; then'
  echo '    if [[ "${PS1:-}" == *"${marker}"* ]]; then'
  echo '      DEVKIT_SYNC_ORIG_PS1="$(__devkit_rewrite_prompt_hostname "${PS1#*] }")"'
  echo '    else'
  echo '      DEVKIT_SYNC_ORIG_PS1="$(__devkit_rewrite_prompt_hostname "${PS1:-\u@\h:\w\$ }")"'
  echo '    fi'
  echo '    export DEVKIT_SYNC_ORIG_PS1'
  echo '  else'
  echo '    DEVKIT_SYNC_ORIG_PS1="$(__devkit_rewrite_prompt_hostname "${DEVKIT_SYNC_ORIG_PS1}")"'
  echo '    export DEVKIT_SYNC_ORIG_PS1'
  echo '  fi'
  echo '  if [[ "${PS1:-}" != "${DEVKIT_SYNC_PROMPT_PREFIX}"* ]]; then'
  echo '    export PS1="${DEVKIT_SYNC_PROMPT_PREFIX}${DEVKIT_SYNC_ORIG_PS1}"'
  echo '  fi'
  echo '}'
  echo '__devkit_apply_prompt'
  declare -f devkit-run
  echo 'unalias dk >/dev/null 2>&1 || true'
  declare -f dk
} > "${_persist_file}"

if ! grep -qF 'source ~/.devkit-sync.rc' "${HOME}/.bashrc"; then
  if [[ -f "${HOME}/.bashrc" && ! -f "${HOME}/.bashrc.pre-devkit-sync.bak" ]]; then
    cp -p "${HOME}/.bashrc" "${HOME}/.bashrc.pre-devkit-sync.bak"
  fi
  cat >> "${HOME}/.bashrc" <<'EOF'
if [ -f ~/.devkit-sync.rc ]; then
  source ~/.devkit-sync.rc
fi
EOF
fi

if [[ ! -f "${HOME}/.bash_profile" ]]; then
  touch "${HOME}/.bash_profile"
fi

if [[ -f "${HOME}/.bash_profile" && ! -f "${HOME}/.bash_profile.pre-devkit-sync.bak" ]]; then
  cp -p "${HOME}/.bash_profile" "${HOME}/.bash_profile.pre-devkit-sync.bak"
fi

if ! grep -qF '# >>> devkit-sync profile >>>' "${HOME}/.bash_profile"; then
  cat >> "${HOME}/.bash_profile" <<'EOF'
# >>> devkit-sync profile >>>
if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi
# <<< devkit-sync profile <<<
EOF
fi

if [[ "$(id -u)" -eq 0 ]]; then
  while IFS=: read -r _user _passwd _uid _gid _gecos _home _shell; do
    [[ "${_uid}" != "0" ]] || continue
    [[ "${_home}" == /home/* && -d "${_home}" ]] || continue
    [[ "${_shell}" == */bash || "${_shell}" == */sh ]] || continue

    install -o "${_uid}" -g "${_gid}" -m 0644 "${_persist_file}" "${_home}/.devkit-sync.rc"
    install -o "${_uid}" -g "${_gid}" -m 0700 -d "${_home}/.ssh"
    if [[ -f "${HOME}/.ssh/id_ed25519" ]]; then
      install -o "${_uid}" -g "${_gid}" -m 0600 "${HOME}/.ssh/id_ed25519" "${_home}/.ssh/id_ed25519"
    fi
    if [[ -f "${HOME}/.ssh/id_ed25519.pub" ]]; then
      install -o "${_uid}" -g "${_gid}" -m 0644 "${HOME}/.ssh/id_ed25519.pub" "${_home}/.ssh/id_ed25519.pub"
    fi
    if [[ -f "${HOME}/.ssh/known_hosts" ]]; then
      install -o "${_uid}" -g "${_gid}" -m 0600 "${HOME}/.ssh/known_hosts" "${_home}/.ssh/known_hosts"
    fi

    touch "${_home}/.bashrc"
    chown "${_uid}:${_gid}" "${_home}/.bashrc"
    if ! grep -qF 'source ~/.devkit-sync.rc' "${_home}/.bashrc"; then
      cat >> "${_home}/.bashrc" <<'EOF'
if [ -f ~/.devkit-sync.rc ]; then
  source ~/.devkit-sync.rc
fi
EOF
      chown "${_uid}:${_gid}" "${_home}/.bashrc"
    fi

    touch "${_home}/.bash_profile"
    chown "${_uid}:${_gid}" "${_home}/.bash_profile"
    if ! grep -qF '# >>> devkit-sync profile >>>' "${_home}/.bash_profile"; then
      cat >> "${_home}/.bash_profile" <<'EOF'
# >>> devkit-sync profile >>>
if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi
# <<< devkit-sync profile <<<
EOF
      chown "${_uid}:${_gid}" "${_home}/.bash_profile"
    fi
  done < /etc/passwd
fi

copy_insight_port_map_to_devkit "${DEVKIT_SYNC_DEVKIT_USER}" "${DEVKIT_SYNC_DEVKIT_IP}" "${DEVKIT_SYNC_DEVKIT_PORT}"

echo "Persisted DevKit shell helpers to ${_persist_file} (auto-loaded by ~/.bashrc and ~/.bash_profile)."

_c_ok="" _c_rst=""
if [[ -t 1 ]]; then
  _c_ok=$'\033[1;32m'
  _c_rst=$'\033[0m'
fi
cat <<EOF
${_c_ok}
============================================================
  DevKit Connected
============================================================
  DevKit target : ${DEVKIT_SYNC_DEVKIT_USER}@${DEVKIT_SYNC_DEVKIT_IP}:${DEVKIT_SYNC_DEVKIT_PORT}
  Mounted path  : ${DEVKIT_SYNC_MOUNT_POINT}
  Host export   : ${_HOST_IP}:${_HOST_EXPORT_PATH}

  You can now run DevKit binaries from this SDK shell:
    dk /workspace/<path-to-arm64-binary> [args...]
  Or connect to a DevKit shell directly:
    dk shell
============================================================
${_c_rst}
EOF
