#!/usr/bin/env bash
set -euo pipefail

prompt_yes_no() {
  local prompt="$1"
  local answer

  while true; do
    read -r -p "${prompt} [y/N]: " answer
    answer="$(printf '%s' "${answer}" | tr '[:upper:]' '[:lower:]')"
    case "${answer}" in
      y|yes)
        return 0
        ;;
      ""|n|no)
        return 1
        ;;
      *)
        echo "Please answer y or n."
        ;;
    esac
  done
}

resolve_sima_cli() {
  local candidate
  local candidates=()

  if [[ -n "${SIMA_CLI:-}" ]]; then
    if [[ -x "${SIMA_CLI}" ]]; then
      printf '%s\n' "${SIMA_CLI}"
      return 0
    fi

    echo "SIMA_CLI is set but is not executable: ${SIMA_CLI}" >&2
    return 1
  fi

  if command -v sima-cli >/dev/null 2>&1; then
    command -v sima-cli
    return 0
  fi

  candidates+=(
    "${HOME}/.sima-cli/.venv/bin/sima-cli"
    "${HOME}/.local/bin/sima-cli"
    "/data/sima-cli/.venv/bin/sima-cli"
    "/opt/sima-cli/venv/bin/sima-cli"
    "/usr/local/bin/sima-cli"
  )

  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

main() {
  local sima_cli

  if ! sima_cli="$(resolve_sima_cli)"; then
    echo "Required command not found: sima-cli" >&2
    echo "Checked PATH and common user install locations under ${HOME}." >&2
    echo "If sima-cli is installed elsewhere, set SIMA_CLI=/path/to/sima-cli and retry." >&2
    exit 1
  fi

  echo "SiMa.ai Palette Neat SDK image is available locally."
  echo "Starting SDK setup."

  if prompt_yes_no "Do you want to pair this SDK with a DevKit now?"; then
    local devkit_ip=""
    while [[ -z "${devkit_ip}" ]]; do
      read -r -p "Enter DevKit IP address: " devkit_ip
      devkit_ip="${devkit_ip//[[:space:]]/}"
      if [[ -z "${devkit_ip}" ]]; then
        echo "DevKit IP address cannot be empty."
      fi
    done
    "${sima_cli}" sdk setup --devkit "${devkit_ip}"
  else
    "${sima_cli}" sdk setup
  fi
}

main "$@"
