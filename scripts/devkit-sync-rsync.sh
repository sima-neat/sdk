#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  devkit-sync-rsync.sh setup --devkit IP --user USER --port PORT --local PATH --remote PATH
  devkit-sync-rsync.sh sync --devkit IP --user USER --port PORT --local PATH --remote PATH [--scope PATH] [--status-file PATH]
  devkit-sync-rsync.sh status --devkit IP --user USER --port PORT --remote PATH [--status-file PATH]
  devkit-sync-rsync.sh map-path --local-root PATH --remote-root PATH --path PATH
  devkit-sync-rsync.sh scope-for-path --local-root PATH --path PATH
  devkit-sync-rsync.sh print-excludes --local PATH
EOF
}

cmd="${1:-}"
if [[ -z "${cmd}" ]]; then
  usage
  exit 2
fi
shift

devkit=""
user="sima"
port="22"
local_root="/workspace"
remote_root="/workspace-rsync"
path=""
scope=""
status_file="${DEVKIT_RSYNC_STATUS_FILE:-${HOME}/.devkit-rsync-status}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --devkit)
      devkit="${2:-}"; shift 2 ;;
    --user)
      user="${2:-}"; shift 2 ;;
    --port)
      port="${2:-}"; shift 2 ;;
    --local)
      local_root="${2:-}"; shift 2 ;;
    --remote)
      remote_root="${2:-}"; shift 2 ;;
    --local-root)
      local_root="${2:-}"; shift 2 ;;
    --remote-root)
      remote_root="${2:-}"; shift 2 ;;
    --path)
      path="${2:-}"; shift 2 ;;
    --scope)
      scope="${2:-}"; shift 2 ;;
    --status-file)
      status_file="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

ssh_target() {
  printf '%s@%s' "${user}" "${devkit}"
}

require_connection_args() {
  if [[ -z "${devkit}" || -z "${user}" || -z "${port}" ]]; then
    echo "--devkit, --user, and --port are required." >&2
    exit 2
  fi
  if [[ ! "${port}" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "Invalid SSH port: ${port}" >&2
    exit 2
  fi
}

ssh_base() {
  ssh -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "$(ssh_target)" "$@"
}

ssh_bash() {
  ssh -T -p "${port}" -o BatchMode=yes -o ConnectTimeout=8 "$(ssh_target)" bash -s -- "$@"
}

default_excludes() {
  cat <<'EOF'
.git/
.gitmodules
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.cache/
.venv/
venv/
node_modules/
*.log
.DS_Store
EOF
}

write_status() {
  local state="$1"
  local detail="$2"
  local sync_scope="${3:-}"
  mkdir -p "$(dirname "${status_file}")"
  {
    printf 'timestamp=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'state=%s\n' "${state}"
    if [[ -n "${sync_scope}" ]]; then
      printf 'scope=%q\n' "${sync_scope}"
    fi
    printf 'detail=%q\n' "${detail}"
  } > "${status_file}"
}

normalize_local_path() {
  local input="$1"
  local part
  local -a parts=()
  local -a normalized_parts=()

  if [[ "${input}" != /* ]]; then
    input="${PWD}/${input}"
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

scope_for_path() {
  local input="$1"
  local normalized

  if [[ -z "${input}" ]]; then
    input="${local_root}"
  fi
  normalized="$(normalize_local_path "${input}")"

  case "${normalized}" in
    "${local_root}")
      printf '%s\n' "${local_root}"
      ;;
    "${local_root}"/*)
      local rel first
      rel="${normalized#"${local_root%/}/"}"
      first="${rel%%/*}"
      if [[ -n "${first}" ]]; then
        printf '%s/%s\n' "${local_root%/}" "${first}"
      else
        printf '%s\n' "${local_root}"
      fi
      ;;
    *)
      echo "Scope must be inside ${local_root}: ${input}" >&2
      return 2
      ;;
  esac
}

remote_for_local_path() {
  local input="$1"
  local normalized
  normalized="$(normalize_local_path "${input}")"
  case "${normalized}" in
    "${local_root}")
      printf '%s\n' "${remote_root%/}"
      ;;
    "${local_root}"/*)
      printf '%s/%s\n' "${remote_root%/}" "${normalized#"${local_root%/}/"}"
      ;;
    *)
      echo "Path must be inside ${local_root}: ${input}" >&2
      return 2
      ;;
  esac
}

build_exclude_args() {
  local tmp="$1"
  local exclude_base="${2:-${local_root}}"
  default_excludes > "${tmp}"
  if [[ -f "${exclude_base}/.devkit-rsync-exclude" ]]; then
    cat "${exclude_base}/.devkit-rsync-exclude" >> "${tmp}"
  elif [[ "${exclude_base}" != "${local_root}" && -f "${local_root}/.devkit-rsync-exclude" ]]; then
    cat "${local_root}/.devkit-rsync-exclude" >> "${tmp}"
  fi
  if [[ -n "${DEVKIT_RSYNC_EXCLUDES_FILE:-}" && -f "${DEVKIT_RSYNC_EXCLUDES_FILE}" ]]; then
    cat "${DEVKIT_RSYNC_EXCLUDES_FILE}" >> "${tmp}"
  fi
  if [[ -n "${DEVKIT_RSYNC_EXTRA_EXCLUDES:-}" ]]; then
    printf '%s\n' "${DEVKIT_RSYNC_EXTRA_EXCLUDES}" >> "${tmp}"
  fi
}

case "${cmd}" in
  setup)
    require_connection_args
    if ! command -v rsync >/dev/null 2>&1; then
      echo "rsync is not installed in the SDK container." >&2
      exit 1
    fi
    ssh_bash "${remote_root}" <<'EOS' || {
set -euo pipefail
remote_root="$1"
if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO="__missing_sudo__"
fi

as_root() {
  if [[ -z "${SUDO}" ]]; then
    "$@"
  elif [[ "${SUDO}" == "__missing_sudo__" ]]; then
    echo "Passwordless sudo is required on the DevKit for rsync fallback setup." >&2
    return 1
  else
    sudo "$@"
  fi
}

if ! command -v rsync >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update --allow-releaseinfo-change
    as_root apt-get install -y --no-install-recommends rsync
  fi
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is not installed on the DevKit and could not be installed automatically." >&2
  exit 1
fi

physical_root="${remote_root}"
if [[ "${remote_root}" == "/workspace-rsync" && -d "/nvme/media" ]]; then
  physical_root="/nvme/media/workspace-rsync"
fi

if [[ "${physical_root}" == "${remote_root}" ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    mkdir -p "${remote_root}"
    chmod 0755 "${remote_root}"
  elif mkdir -p "${remote_root}" >/dev/null 2>&1; then
    chmod 0755 "${remote_root}" || true
  elif [[ "${SUDO}" != "__missing_sudo__" ]]; then
    as_root mkdir -p "${remote_root}"
    as_root chown "$(id -u):$(id -g)" "${remote_root}"
    as_root chmod 0755 "${remote_root}"
  else
    echo "Cannot create ${remote_root}; passwordless sudo is required." >&2
    exit 1
  fi
else
  if [[ "$(id -u)" -eq 0 ]]; then
    mkdir -p "${physical_root}"
    chown "$(id -u):$(id -g)" "${physical_root}"
    chmod 0755 "${physical_root}"
  elif mkdir -p "${physical_root}" >/dev/null 2>&1; then
    chmod 0755 "${physical_root}" || true
  elif [[ "${SUDO}" != "__missing_sudo__" ]]; then
    as_root mkdir -p "${physical_root}"
    as_root chown "$(id -u):$(id -g)" "${physical_root}"
    as_root chmod 0755 "${physical_root}"
  else
    echo "Cannot create ${physical_root}; passwordless sudo is required." >&2
    exit 1
  fi

  if [[ -L "${remote_root}" ]]; then
    as_root ln -sfn "${physical_root}" "${remote_root}"
  elif [[ -e "${remote_root}" ]]; then
    if rmdir "${remote_root}" >/dev/null 2>&1 || as_root rmdir "${remote_root}"; then
      as_root ln -sfn "${physical_root}" "${remote_root}"
    else
      echo "WARNING: ${remote_root} already exists and is not empty; using existing root filesystem path." >&2
      physical_root="${remote_root}"
    fi
  else
    as_root ln -sfn "${physical_root}" "${remote_root}"
  fi
fi

df -h "${physical_root}" 2>/dev/null | tail -n 1 | awk -v logical="${remote_root}" -v physical="${physical_root}" '
  { printf "rsync remote workspace: logical=%s physical=%s available=%s filesystem=%s\n", logical, physical, $4, $1 }
'
EOS
      echo "DevKit rsync setup failed. Ensure rsync can be installed and ${remote_root} is writable." >&2
      exit 1
    }
    ;;
  sync)
    require_connection_args
    local_sync_root="$(scope_for_path "${scope:-${PWD}}")"
    remote_sync_root="$(remote_for_local_path "${local_sync_root}")"
    if [[ ! -d "${local_sync_root}" ]]; then
      echo "Local sync root not found: ${local_sync_root}" >&2
      write_status failed "local root not found: ${local_sync_root}" "${local_sync_root}" || true
      exit 1
    fi
    tmp_excludes="$(mktemp)"
    trap 'rm -f "${tmp_excludes}"' EXIT
    build_exclude_args "${tmp_excludes}" "${local_sync_root}"
    rsync_args=(-az --delete "--exclude-from=${tmp_excludes}")
    case "${DEVKIT_RSYNC_PROGRESS:-AUTO}" in
      OFF|off|0|false|FALSE|no|NO)
        ;;
      AUTO|auto|"")
        if [[ -t 1 ]]; then
          rsync_args+=("--info=progress2,stats2" --human-readable)
        fi
        ;;
      *)
        rsync_args+=("--info=progress2,stats2" --human-readable)
        ;;
    esac
    echo "Syncing ${local_sync_root} -> $(ssh_target):${remote_sync_root}"
    if rsync "${rsync_args[@]}" -e "ssh -p ${port} -o BatchMode=yes -o ConnectTimeout=8" "${local_sync_root%/}/" "$(ssh_target):${remote_sync_root%/}/"; then
      write_status ok "synced ${local_sync_root} to ${remote_sync_root}" "${local_sync_root}" || true
    else
      rc=$?
      write_status failed "rsync exited ${rc}" "${local_sync_root}" || true
      exit "${rc}"
    fi
    ;;
  status)
    require_connection_args
    echo "rsync remote root: ${remote_root}"
    if ssh_base "test -d '${remote_root}'"; then
      echo "remote root: present"
      ssh_base "if [ -L '${remote_root}' ]; then printf 'physical root: '; readlink -f '${remote_root}'; else echo 'physical root: ${remote_root}'; fi; df -h '${remote_root}' 2>/dev/null | tail -n 1 | awk '{print \"available space: \" \$4 \" on \" \$1}'" || true
    else
      echo "remote root: missing"
    fi
    if [[ -f "${status_file}" ]]; then
      echo "last sync:"
      sed 's/^/  /' "${status_file}"
    else
      echo "last sync: never"
    fi
    ;;
  print-excludes)
    tmp_excludes="$(mktemp)"
    trap 'rm -f "${tmp_excludes}"' EXIT
    build_exclude_args "${tmp_excludes}"
    cat "${tmp_excludes}"
    ;;
  map-path)
    if [[ -z "${path}" ]]; then
      echo "--path is required for map-path." >&2
      exit 2
    fi
    case "${path}" in
      "${local_root}"/*)
        printf '%s/%s\n' "${remote_root%/}" "${path#"${local_root%/}/"}"
        ;;
      "${local_root}")
        printf '%s\n' "${remote_root%/}"
        ;;
      *)
        printf '%s\n' "${path}"
        ;;
    esac
    ;;
  scope-for-path)
    if [[ -z "${path}" ]]; then
      echo "--path is required for scope-for-path." >&2
      exit 2
    fi
    scope_for_path "${path}"
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    usage
    exit 2
    ;;
esac
