#!/usr/bin/env bash
set -euo pipefail

program_name="$(basename "$0")"
command="${1:-}"

usage() {
  cat <<EOF
Usage:
  ${program_name} update [branch] [version]
  ${program_name} status
  ${program_name} stop
  ${program_name} restart
  ${program_name} logs [lines]

Defaults:
  branch  = \${NEAT_INSIGHT_BRANCH:-main}
  version = \${NEAT_INSIGHT_VERSION:-latest}
EOF
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
  echo "This command requires root privileges and sudo is not available." >&2
  return 1
}

supervisorctl_if_available() {
  if ! command -v supervisorctl >/dev/null 2>&1 && ! run_as_root command -v supervisorctl >/dev/null 2>&1; then
    echo "supervisorctl is not available." >&2
    return 127
  fi
  run_as_root supervisorctl "$@"
}

show_logs() {
  local lines="${1:-120}"
  if [[ ! "${lines}" =~ ^[0-9]+$ ]] || (( lines < 1 )); then
    echo "Invalid line count: ${lines}" >&2
    return 2
  fi

  echo "== neat-insight stdout =="
  run_as_root tail -n "${lines}" /var/log/supervisor/neat-insight.log 2>/dev/null || true
  echo "== neat-insight stderr =="
  run_as_root tail -n "${lines}" /var/log/supervisor/neat-insight.err.log 2>/dev/null || true
}

is_supervisor_running() {
  supervisorctl_if_available status >/dev/null 2>&1
}

update_insight() {
  local branch="${1:-${NEAT_INSIGHT_BRANCH:-main}}"
  local version="${2:-${NEAT_INSIGHT_VERSION:-latest}}"
  local venv_dir="${NEAT_INSIGHT_VENV_DIR:-/opt/neat-insight/venv}"
  local tmp_script

  tmp_script="$(mktemp /tmp/install-neat-insight.XXXXXX.py)"
  trap 'rm -f "${tmp_script}"' EXIT

  curl -fsSL https://apps.sima-neat.com/tools/install-neat-insight.py -o "${tmp_script}"
  run_as_root env NEAT_INSIGHT_VENV_DIR="${venv_dir}" python3 "${tmp_script}" "${branch}" "${version}"
  run_as_root ln -sf "${venv_dir}/bin/neat-insight" /usr/local/bin/neat-insight
  rm -f "${tmp_script}"
  trap - EXIT

  if is_supervisor_running; then
    echo "Restarting neat-insight..."
    supervisorctl_if_available restart neat-insight
  else
    echo "neat-insight will start under supervisord when the container starts."
  fi
}

case "${command}" in
  update)
    shift
    update_insight "$@"
    ;;
  status)
    supervisorctl_if_available status neat-insight
    ;;
  stop)
    supervisorctl_if_available stop neat-insight
    ;;
  restart)
    supervisorctl_if_available restart neat-insight
    ;;
  logs)
    shift
    show_logs "$@"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: ${command}" >&2
    usage >&2
    exit 2
    ;;
esac
