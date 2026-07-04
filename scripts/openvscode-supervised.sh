#!/usr/bin/env bash
set -euo pipefail

if [[ "${OPENVSCODE_SERVER_SUPERVISED:-1}" == "0" ]]; then
  echo "OpenVSCode Server supervision disabled by OPENVSCODE_SERVER_SUPERVISED=0"
  exit 0
fi

workspace="${OPENVSCODE_WORKSPACE:-/workspace}"
target_user="${OPENVSCODE_SERVER_USER:-}"

if [[ -z "${target_user}" || "${target_user}" == "root" ]]; then
  exec /usr/local/bin/sima-code "${workspace}"
fi

wait_seconds="${OPENVSCODE_SERVER_USER_WAIT_SECONDS:-60}"
deadline=$((SECONDS + wait_seconds))
home_dir=""

while (( SECONDS < deadline )); do
  if user_entry="$(getent passwd "${target_user}" 2>/dev/null)"; then
    home_dir="$(printf '%s' "${user_entry}" | cut -d: -f6)"
    if [[ -n "${home_dir}" && -d "${home_dir}" ]]; then
      break
    fi
  fi
  sleep 1
done

if [[ -z "${home_dir}" || ! -d "${home_dir}" ]]; then
  echo "OpenVSCode Server user '${target_user}' was not configured within ${wait_seconds}s; starting as root." >&2
  exec /usr/local/bin/sima-code "${workspace}"
fi

if command -v runuser >/dev/null 2>&1; then
  exec runuser -u "${target_user}" -- env HOME="${home_dir}" /usr/local/bin/sima-code "${workspace}"
fi

if command -v sudo >/dev/null 2>&1; then
  exec sudo -H -u "${target_user}" -- /usr/local/bin/sima-code "${workspace}"
fi

echo "Neither runuser nor sudo is available; starting OpenVSCode Server as root." >&2
exec /usr/local/bin/sima-code "${workspace}"
