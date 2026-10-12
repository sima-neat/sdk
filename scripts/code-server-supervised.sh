#!/usr/bin/env bash
set -euo pipefail

supervised="${CODE_SERVER_SUPERVISED:-${OPENVSCODE_SERVER_SUPERVISED:-1}}"
if [[ "${supervised}" == "0" ]]; then
  echo "code-server supervision disabled by CODE_SERVER_SUPERVISED=0"
  exit 0
fi

workspace="${CODE_SERVER_WORKSPACE:-${OPENVSCODE_WORKSPACE:-/workspace}}"
target_user="${CODE_SERVER_USER:-${OPENVSCODE_SERVER_USER:-}}"

if [[ -z "${target_user}" || "${target_user}" == "root" ]]; then
  exec /usr/local/bin/sima-code "${workspace}"
fi

wait_seconds="${CODE_SERVER_USER_WAIT_SECONDS:-${OPENVSCODE_SERVER_USER_WAIT_SECONDS:-60}}"
deadline=$((SECONDS + wait_seconds))
home_dir=""
shell_path=""

while (( SECONDS < deadline )); do
  if user_entry="$(getent passwd "${target_user}" 2>/dev/null)"; then
    home_dir="$(printf '%s' "${user_entry}" | cut -d: -f6)"
    shell_path="$(printf '%s' "${user_entry}" | cut -d: -f7)"
    if [[ -n "${home_dir}" && -d "${home_dir}" ]]; then
      break
    fi
  fi
  sleep 1
done

if [[ -z "${home_dir}" || ! -d "${home_dir}" ]]; then
  echo "code-server user '${target_user}' was not configured within ${wait_seconds}s; starting as root." >&2
  exec /usr/local/bin/sima-code "${workspace}"
fi

if [[ -z "${shell_path}" ]]; then
  shell_path="/bin/bash"
fi

if command -v runuser >/dev/null 2>&1; then
  exec runuser -u "${target_user}" -- env \
    HOME="${home_dir}" \
    USER="${target_user}" \
    LOGNAME="${target_user}" \
    SHELL="${shell_path}" \
    PWD="${workspace}" \
    /usr/local/bin/sima-code "${workspace}"
fi

if command -v sudo >/dev/null 2>&1; then
  exec sudo -H -u "${target_user}" -- env \
    USER="${target_user}" \
    LOGNAME="${target_user}" \
    SHELL="${shell_path}" \
    PWD="${workspace}" \
    /usr/local/bin/sima-code "${workspace}"
fi

echo "Neither runuser nor sudo is available; starting code-server as root." >&2
exec /usr/local/bin/sima-code "${workspace}"
