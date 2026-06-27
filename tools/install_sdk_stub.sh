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

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Required command not found: ${name}" >&2
    exit 1
  fi
}

main() {
  require_command sima-cli

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
    sima-cli sdk setup --devkit "${devkit_ip}"
  else
    sima-cli sdk setup
  fi
}

main "$@"
