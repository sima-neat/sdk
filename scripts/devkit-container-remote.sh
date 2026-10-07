#!/usr/bin/env bash
set -euo pipefail

action="${1:?missing container action}"
shift

configure_container_registry() {
  local registry="${1:-}"
  local changed=""
  if [[ -z "${registry}" ]]; then
    return 0
  fi
  if ! command -v sudo >/dev/null 2>&1 || ! sudo -n true >/dev/null 2>&1; then
    echo "Container registry setup requires passwordless sudo on the DevKit." >&2
    return 2
  fi
  changed="$(sudo -n python3 - "${registry}" <<'PY'
import json
import os
import shutil
import sys
from pathlib import Path

path = Path("/etc/docker/daemon.json")
state_path = Path("/etc/docker/sima-sdk-registry-address")
legacy_state_path = Path("/etc/docker/sima-cli-registry-address")
applied_state_path = Path("/etc/docker/sima-sdk-registry-applied")
registry = sys.argv[1]
data = {}
if path.exists():
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
registries = data.get("insecure-registries", [])
if not isinstance(registries, list):
    raise RuntimeError("Docker insecure-registries must be a list")
if state_path.exists():
    previous = state_path.read_text(encoding="utf-8").strip()
elif legacy_state_path.exists():
    previous = legacy_state_path.read_text(encoding="utf-8").strip()
else:
    previous = ""
updated = [value for value in registries if not previous or value != previous or value == registry]
if registry not in updated:
    updated.append(registry)
changed = sorted(set(updated)) != sorted(set(registries))
applied = applied_state_path.read_text(encoding="utf-8").strip() if applied_state_path.exists() else ""
backup = Path(str(path) + ".sima-sdk.bak")
if path.exists() and not backup.exists():
    shutil.copy2(str(path), str(backup))
data["insecure-registries"] = sorted(set(updated))
path.parent.mkdir(parents=True, exist_ok=True)
if changed:
    temporary = Path(str(path) + ".sima-sdk.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(str(temporary), str(path))
state_temporary = Path(str(state_path) + ".tmp")
state_temporary.write_text(registry + "\n", encoding="utf-8")
os.replace(str(state_temporary), str(state_path))
legacy_state_path.unlink(missing_ok=True)
print("restart" if changed or applied != registry else "unchanged")
PY
  )"
  if [[ "${changed}" == restart ]] || ! sudo -n systemctl is-active --quiet docker; then
    echo "Docker registry settings changed. Restarting Docker on the DevKit."
    sudo -n systemctl restart docker
  fi
  sudo -n docker info >/dev/null
  if [[ "${changed}" == restart ]]; then
    printf '%s\n' "${registry}" | sudo -n tee /etc/docker/sima-sdk-registry-applied.tmp >/dev/null
    sudo -n mv /etc/docker/sima-sdk-registry-applied.tmp /etc/docker/sima-sdk-registry-applied
  fi
  echo "The DevKit can now download images from ${registry}."
}

configure_docker_access() {
  local target_user
  target_user="$(id -un)"
  if ! command -v sudo >/dev/null 2>&1 || ! sudo -n true >/dev/null 2>&1; then
    echo "Docker setup requires passwordless sudo for ${target_user} on the DevKit." >&2
    return 2
  fi
  sudo -n usermod -aG docker "${target_user}"
  sudo -n systemctl enable --now containerd docker
  sudo -n docker info >/dev/null
  echo "Docker is ready on the DevKit. User ${target_user} was added to the docker group."
}

install_docker() (
  local architecture=""
  local mirror=/etc/apt/sources.list.d/0000mirror.list
  local disabled_mirror=/root/apt-disabled/0000mirror.list
  local install_marker=/etc/docker/.sima-sdk-install-in-progress
  local mirror_moved=0
  local resume_install=0
  local services_stopped=0
  local target_user=""
  local entry=""
  local entry_name=""
  local destination=""
  local migration_marker=""
  local migration_marker_dir=/etc/docker/.sima-sdk-containerd-migrated
  local migration_staging_root=/data/.sima-sdk-containerd-migration
  local marker_entry=""
  local marker_name=""
  local staging=""
  local -a containerd_entries=()
  local -a migration_markers=()

  target_user="$(id -un)"
  if ! command -v sudo >/dev/null 2>&1 || ! sudo -n true >/dev/null 2>&1; then
    echo "Docker installation requires passwordless sudo for ${target_user} on the DevKit." >&2
    return 2
  fi
  architecture="$(dpkg --print-architecture 2>/dev/null || true)"
  if [[ "${architecture}" != arm64 ]]; then
    echo "Docker installation is supported only on an ARM64 Modalix DevKit; found ${architecture:-unknown}." >&2
    return 2
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Docker installation requires Python 3 on the DevKit." >&2
    return 2
  fi

  restore_elxr_mirror() {
    if [[ "${mirror_moved}" == 1 ]] && sudo -n test -e "${disabled_mirror}" && \
       ! sudo -n test -e "${mirror}"; then
      sudo -n mkdir -p "$(dirname "${mirror}")"
      sudo -n mv "${disabled_mirror}" "${mirror}"
    fi
  }
  cleanup_install() {
    restore_elxr_mirror
    if [[ "${services_stopped}" == 1 ]]; then
      if mountpoint -q /var/lib/containerd && \
         [[ "$(findmnt -n -o SOURCE --target /var/lib/containerd)" == /data/containerd ]]; then
        sudo -n systemctl start containerd docker >/dev/null 2>&1 || true
      else
        echo "Docker services remain stopped until containerd storage setup is completed." >&2
      fi
    fi
    if sudo -n test -e "${install_marker}"; then
      echo "Docker installation did not complete. Run 'dk container setup' to retry safely." >&2
    fi
  }
  trap cleanup_install EXIT

  echo "Installing Docker CE for ARM64 on the Modalix DevKit."
  sudo -n mkdir -p /etc/docker
  if sudo -n test -e "${install_marker}"; then
    resume_install=1
    echo "Resuming an interrupted Docker installation."
  else
    sudo -n touch "${install_marker}"
  fi
  if sudo -n test -e "${disabled_mirror}" && ! sudo -n test -e "${mirror}"; then
    mirror_moved=1
    echo "Resuming with the eLxr package mirror temporarily disabled."
  elif sudo -n test -e "${mirror}"; then
    sudo -n mkdir -p "$(dirname "${disabled_mirror}")"
    if sudo -n test -e "${disabled_mirror}"; then
      echo "Cannot disable ${mirror}: ${disabled_mirror} already exists." >&2
      return 2
    fi
    sudo -n mv "${mirror}" "${disabled_mirror}"
    mirror_moved=1
  fi

  sudo -n mkdir -p /data/docker
  sudo -n python3 <<'PY'
import json
import os
import shutil
from pathlib import Path

path = Path("/etc/docker/daemon.json")
backup = Path(str(path) + ".sima-sdk.bak")
data = {}
if path.exists():
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not backup.exists():
        shutil.copy2(str(path), str(backup))
data["firewall-backend"] = "nftables"
data["data-root"] = "/data/docker"
temporary = Path(str(path) + ".sima-sdk.tmp")
with temporary.open("w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.chmod(str(temporary), 0o644)
os.replace(str(temporary), str(path))
PY
  printf 'net.ipv4.ip_forward=1\nnet.ipv6.conf.all.forwarding=1\n' \
    | sudo -n tee /etc/sysctl.d/99-docker-forward.conf >/dev/null
  sudo -n sysctl --system >/dev/null

  sudo -n install -m 0755 -d /etc/apt/keyrings
  if command -v curl >/dev/null 2>&1; then
    sudo -n curl -fsSL https://download.docker.com/linux/debian/gpg \
      -o /etc/apt/keyrings/docker.asc
  else
    python3 - <<'PY' | sudo -n tee /etc/apt/keyrings/docker.asc >/dev/null
import sys
import urllib.request

with urllib.request.urlopen("https://download.docker.com/linux/debian/gpg", timeout=30) as response:
    sys.stdout.buffer.write(response.read())
PY
  fi
  sudo -n chmod a+r /etc/apt/keyrings/docker.asc
  printf '%s\n' \
    'deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian trixie stable' \
    | sudo -n tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo -n apt-get update
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce docker-ce-cli containerd.io

  sudo -n systemctl stop docker.socket docker containerd
  services_stopped=1
  sudo -n mkdir -p /data/containerd /var/lib/containerd
  if mountpoint -q /var/lib/containerd; then
    if [[ "$(findmnt -n -o SOURCE --target /var/lib/containerd)" != /data/containerd ]]; then
      echo "/var/lib/containerd is already mounted from an unexpected source; refusing to replace it." >&2
      return 2
    fi
  else
    if [[ "${resume_install}" == 0 ]] && \
       sudo -n sh -c 'test -n "$(find /data/containerd -mindepth 1 -print -quit)"' && \
       sudo -n sh -c 'test -n "$(find /var/lib/containerd -mindepth 1 -print -quit)"'; then
      echo "Both /data/containerd and /var/lib/containerd already contain data; refusing to merge unrelated state." >&2
      sudo -n rm -f "${install_marker}"
      return 2
    fi
    sudo -n mkdir -p "${migration_marker_dir}" "${migration_staging_root}"
    mapfile -d '' -t migration_markers < <(
      sudo -n find "${migration_marker_dir}" -mindepth 1 -maxdepth 1 -type f -print0
    )
    for marker_entry in "${migration_markers[@]}"; do
      marker_name="$(basename "${marker_entry}")"
      entry="/var/lib/containerd/${marker_name}"
      destination="/data/containerd/${marker_name}"
      staging="${migration_staging_root}/${marker_name}"
      if sudo -n test -e "${entry}" || sudo -n test -L "${entry}"; then
        continue
      fi
      if sudo -n test -e "${destination}" || sudo -n test -L "${destination}"; then
        sudo -n rm -f -- "${marker_entry}"
      elif sudo -n test -e "${staging}" || sudo -n test -L "${staging}"; then
        sudo -n mv -- "${staging}" "${destination}"
        sudo -n rm -f -- "${marker_entry}"
      else
        echo "Cannot resume containerd migration: no data remains for ${marker_name}." >&2
        return 2
      fi
    done
    mapfile -d '' -t containerd_entries < <(
      sudo -n find /var/lib/containerd -mindepth 1 -maxdepth 1 -print0
    )
    for entry in "${containerd_entries[@]}"; do
      entry_name="$(basename "${entry}")"
      destination="/data/containerd/${entry_name}"
      staging="${migration_staging_root}/${entry_name}"
      migration_marker="${migration_marker_dir}/${entry_name}"

      if sudo -n test -e "${migration_marker}"; then
        if ! sudo -n test -e "${destination}" && ! sudo -n test -L "${destination}"; then
          if sudo -n test -e "${staging}" || sudo -n test -L "${staging}"; then
            sudo -n mv -- "${staging}" "${destination}"
          else
            echo "Cannot resume containerd migration: both ${destination} and ${staging} are missing." >&2
            return 2
          fi
        fi
        sudo -n rm -rf -- "${entry}"
        sudo -n rm -f -- "${migration_marker}"
        continue
      fi

      if sudo -n test -e "${destination}" || sudo -n test -L "${destination}"; then
        echo "Cannot migrate containerd state: ${destination} exists without a migration marker." >&2
        return 2
      fi

      # Copy across filesystems without changing the source. The marker is
      # written only after the copy completes and before the same-filesystem
      # rename, so every possible interruption has an unambiguous retry path.
      sudo -n rm -rf -- "${staging}"
      sudo -n cp -a -- "${entry}" "${staging}"
      sudo -n touch "${migration_marker}"
      sudo -n mv -- "${staging}" "${destination}"
      sudo -n rm -rf -- "${entry}"
      sudo -n rm -f -- "${migration_marker}"
    done
    sudo -n rmdir "${migration_staging_root}" "${migration_marker_dir}" 2>/dev/null || true
    if ! sudo -n grep -Fqx '/data/containerd /var/lib/containerd none bind 0 0' /etc/fstab; then
      printf '%s\n' '/data/containerd /var/lib/containerd none bind 0 0' \
        | sudo -n tee -a /etc/fstab >/dev/null
    fi
    sudo -n mount /var/lib/containerd
  fi

  sudo -n systemctl enable containerd docker
  sudo -n systemctl restart containerd docker
  services_stopped=0
  configure_docker_access
  if [[ "$(sudo -n docker info --format '{{.DockerRootDir}}')" != /data/docker ]]; then
    echo "Docker started, but its data root is not /data/docker." >&2
    return 2
  fi
  restore_elxr_mirror
  mirror_moved=0
  sudo -n rm -f "${install_marker}"
  trap - EXIT
  echo "Docker installation completed on the DevKit."
)

if [[ "${action}" == setup ]]; then
  registry="${1:-}"
  if ! command -v docker >/dev/null 2>&1 || \
     [[ -e /etc/docker/.sima-sdk-install-in-progress ]]; then
    install_docker
  else
    configure_docker_access
  fi
  configure_container_registry "${registry}"
  exit $?
fi

if [[ "${action}" == docker-check ]]; then
  if command -v docker >/dev/null 2>&1; then
    exit 0
  fi
  echo "Docker is not installed on the DevKit." >&2
  exit 42
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed on the DevKit." >&2
  exit 2
fi

DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    DOCKER=(sudo -n docker)
  else
    echo "Docker is installed on the DevKit, but the current user cannot use it." >&2
    echo "Run DevKit setup again so sima-cli can configure passwordless sudo." >&2
    exit 2
  fi
fi

if [[ "${action}" == registry-setup ]]; then
  configure_container_registry "${1:-}"
  exit $?
fi

run_image() {
  local image="$1"
  shift
  local after_separator=0
  local arg
  local -a run_options=()
  local -a command_args=()
  for arg in "$@"; do
    if [[ "${arg}" == "--" && "${after_separator}" == "0" ]]; then
      after_separator=1
    elif [[ "${after_separator}" == "0" ]]; then
      run_options+=("${arg}")
    else
      command_args+=("${arg}")
    fi
  done
  if (( ${#run_options[@]} > 0 && ${#command_args[@]} > 0 )); then
    "${DOCKER[@]}" run "${run_options[@]}" "${image}" "${command_args[@]}"
  elif (( ${#run_options[@]} > 0 )); then
    "${DOCKER[@]}" run "${run_options[@]}" "${image}"
  elif (( ${#command_args[@]} > 0 )); then
    "${DOCKER[@]}" run "${image}" "${command_args[@]}"
  else
    "${DOCKER[@]}" run "${image}"
  fi
}

require_arm64_image() {
  local image="$1"
  local architecture=""
  if ! architecture="$("${DOCKER[@]}" image inspect --format '{{.Architecture}}' "${image}")"; then
    echo "Image ${image} is not available on the DevKit." >&2
    echo "Use 'dk container deploy' to download it first." >&2
    return 2
  fi
  case "${architecture}" in
    arm64|aarch64)
      ;;
    *)
      echo "Image ${image} is for ${architecture:-an unknown architecture}, not ARM64." >&2
      echo "Rebuild it with 'docker buildx build --platform linux/arm64 --push'." >&2
      return 2
      ;;
  esac
}

case "${action}" in
  deploy)
    image="${1:?missing image}"
    shift
    echo "Downloading ${image} on the DevKit."
    "${DOCKER[@]}" pull "${image}"
    require_arm64_image "${image}"
    echo "Starting ${image} on the DevKit."
    run_image "${image}" "$@"
    ;;
  run)
    image="${1:?missing image}"
    shift
    require_arm64_image "${image}"
    echo "Starting ${image} on the DevKit."
    run_image "${image}" "$@"
    ;;
  pull)
    image="${1:?missing image}"
    "${DOCKER[@]}" pull "${image}"
    require_arm64_image "${image}"
    ;;
  images)
    "${DOCKER[@]}" image ls --filter "reference=${1:?missing registry}/*"
    ;;
  list)
    "${DOCKER[@]}" ps -a
    ;;
  logs)
    container="${1:?missing container name}"
    shift
    "${DOCKER[@]}" logs "$@" "${container}"
    ;;
  stop)
    "${DOCKER[@]}" stop "${1:?missing container name}"
    ;;
  remove)
    container="${1:?missing container name}"
    shift
    "${DOCKER[@]}" rm "$@" "${container}"
    ;;
  *)
    echo "Unknown DevKit container action: ${action}" >&2
    exit 2
    ;;
esac
