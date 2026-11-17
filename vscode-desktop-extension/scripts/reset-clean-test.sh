#!/usr/bin/env bash
# Resets everything a test of this extension leaves behind, so the next test
# starts as a first run. It asks nothing, and starts nothing:
#   - quits the throwaway VS Code if it's running (only that profile's VS Code);
#   - the throwaway VS Code profile (settings, extensions, restored windows,
#     Dev Containers' per-container settings and its trust answer);
#   - VS Code Server inside every running Neat SDK container (extensions
#     installed while attached, such as Claude Code or the SDK's Neat extension),
#     and this extension's relay files and connection in the container's
#     Claude Code settings.
# Your normal VS Code profile and your workspace folder are not touched.
#
# Usage: scripts/reset-clean-test.sh            (profile in ~/vscode-clean)
#        CLEAN_DIR=/path scripts/reset-clean-test.sh
# Then:  code --user-data-dir ~/vscode-clean/data --extensions-dir ~/vscode-clean/ext ...
set -euo pipefail

CLEAN_DIR="${CLEAN_DIR:-$HOME/vscode-clean}"

clean_running() {
  pgrep -f -- "${CLEAN_DIR}/data" >/dev/null
}

# The clean VS Code's main process: its helpers carry --type=. Electron reorders
# the main process's arguments, so match the folder anywhere in them.
clean_main_pids() {
  for pid in $(pgrep -f -- "${CLEAN_DIR}/data"); do
    ps -o args= -p "$pid" | grep -q -- '--type=' || echo "$pid"
  done
}

# A running clean VS Code would write its state back into the deleted folder,
# and `code --new-window` would open a window in it instead of starting fresh.
# Quitting the main process closes its windows and helpers; killing only
# helpers makes VS Code start them again.
if clean_running; then
  main_pids=$(clean_main_pids)
  if [ -n "$main_pids" ]; then
    kill $main_pids 2>/dev/null || true
  fi
  for _ in $(seq 1 30); do
    clean_running || break
    sleep 0.5
  done
  if clean_running; then
    echo "The clean VS Code didn't quit. Use File > Exit in it, then run this again." >&2
    exit 1
  fi
  echo "Quit the clean VS Code."
fi

rm -rf -- "$CLEAN_DIR"
echo "Removed the clean VS Code profile: $CLEAN_DIR"

# Same match as the extension: images from sima-neat/sdk*.
containers=$(docker ps --format '{{.Names}}|{{.Image}}' | awk -F'|' '$2 ~ /(^|\/)sima-neat\/sdk[A-Za-z0-9_.-]*(:|@|$)/ {print $1}')
if [ -z "$containers" ]; then
  echo "No running Neat SDK containers."
fi
for container in $containers; do
  # Stop any VS Code Server first: a window of your normal VS Code attached to
  # this container loses its connection and reconnects with a fresh server.
  # Also forget the extension's MCP server in Claude Code's settings there
  # (sima-neat-vscode), so the next test connects Claude Code again. Uses
  # VS Code Server's Node.js if the image has none, so before removing it.
  # The server folder name is built from $vs: the pkill below matches its
  # pattern anywhere in a command line, and would kill this very script if
  # the script spelled out the server path.
  docker exec -u root "$container" sh -c '
    vs=vscode-server
    node_bin=$(command -v node || ls -1d /root/.$vs/bin/*/node /home/*/.$vs/bin/*/node 2>/dev/null | tail -n 1)
    if [ -n "$node_bin" ]; then
      for f in /root/.claude.json /home/*/.claude.json; do
        [ -f "$f" ] && "$node_bin" -e "
          const fs = require(\"fs\"); const f = process.argv[1];
          const c = JSON.parse(fs.readFileSync(f, \"utf8\"));
          if (c.mcpServers && c.mcpServers[\"sima-neat-vscode\"]) { delete c.mcpServers[\"sima-neat-vscode\"]; fs.writeFileSync(f, JSON.stringify(c, null, 2)); console.log(\"Removed the Claude Code connection from \" + f); }
        " "$f"
      done
    fi
    pkill -f "/[.]vscode-server(-insiders)?/" 2>/dev/null || true
    rm -rf /root/.vscode-server /root/.vscode-server-insiders /home/*/.vscode-server /home/*/.vscode-server-insiders
    rm -rf /root/.sima-neat-vscode /home/*/.sima-neat-vscode
  ' || status=$?
  if [ "${status:-0}" -ne 0 ]; then
    echo "Couldn't reset $container (exit code $status). Run this script again." >&2
    failed=1
    unset status
    continue
  fi
  echo "Removed VS Code Server from $container"
done

if [ -n "${failed:-}" ]; then
  exit 1
fi

stopped=$(docker ps -a --filter status=exited --format '{{.Names}}|{{.Image}}' | awk -F'|' '$2 ~ /(^|\/)sima-neat\/sdk[A-Za-z0-9_.-]*(:|@|$)/ {print $1}')
for container in $stopped; do
  echo "Skipped stopped container $container (start it and run this again to reset it)."
done
