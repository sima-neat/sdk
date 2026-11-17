#!/usr/bin/env bash
# One step for a first-run test: resets the throwaway VS Code profile and the
# SDK containers' VS Code Server (reset-clean-test.sh), installs the newest
# packaged .vsix into that profile, and opens it.
#
# Usage: scripts/test-clean.sh            (newest sima-neat-desktop-*.vsix)
#        scripts/test-clean.sh path.vsix
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLEAN_DIR="${CLEAN_DIR:-$HOME/vscode-clean}"
VSIX="${1:-$(ls -t "$HERE"/../sima-neat-desktop-*.vsix 2>/dev/null | head -1)}"
if [ -z "$VSIX" ] || [ ! -f "$VSIX" ]; then
  echo "No .vsix found. Run 'npm run package' first." >&2
  exit 1
fi

code_clean() {
  code --user-data-dir "$CLEAN_DIR/data" --extensions-dir "$CLEAN_DIR/ext" "$@"
}

CLEAN_DIR="$CLEAN_DIR" "$HERE/reset-clean-test.sh"
echo "Installing $(basename "$VSIX")…"
code_clean --install-extension "$VSIX" 2>&1 | grep -v -e DeprecationWarning -e 'trace-deprecation'
echo "Installed extensions: $(ls "$CLEAN_DIR/ext" | grep -v extensions.json | tr '\n' ' ')"
code_clean --new-window
echo "Opened the clean VS Code."
