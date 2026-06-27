#!/usr/bin/env bash
# Supervisord launch wrapper for neat-insight.
#
# Sources ~/.devkit-sync.rc (rewritten by devkit.sh on every DevKit (re-)point)
# so neat-insight -- and the vf WebRTC viewer it spawns -- inherit the current
# CONTAINER_HOST_IP. neat-insight itself stays environment-agnostic: it only
# reads CONTAINER_HOST_IP from its process env. All DevKit-specific knowledge
# (the .devkit-sync.rc format) lives here in the SDK image, not in Insight.
#
# supervisord runs this as root (HOME=/root); devkit.sh also installs the rc
# into the SDK user homes, but the root copy is sufficient for the service env.

rc="${HOME:-/root}/.devkit-sync.rc"
[ -f "$rc" ] || rc="/root/.devkit-sync.rc"
if [ -f "$rc" ]; then
  # shellcheck disable=SC1090
  . "$rc" >/dev/null 2>&1 || true
fi

exec /opt/neat-insight/venv/bin/neat-insight --port "${NEAT_INSIGHT_PORT:-9900}"
