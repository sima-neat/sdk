'use strict';

// A status bar item on the right that follows a multi-step operation: a
// spinner with the current step, then a short "done" or "failed" message.

const vscode = require('vscode');

const DONE_VISIBLE_MS = 6000;

function createProgressStatus(id, name) {
  const item = vscode.window.createStatusBarItem(id, vscode.StatusBarAlignment.Right, 1000);
  item.name = name;
  let hideTimer;

  return {
    /** Shows a step with a spinner. */
    step(text, tooltip) {
      clearTimeout(hideTimer);
      item.text = `$(loading~spin) ${text}`;
      item.tooltip = tooltip || text;
      item.backgroundColor = undefined;
      item.show();
    },
    /** Shows the outcome for a few seconds, then hides. */
    finish(text, { failed = false, tooltip } = {}) {
      clearTimeout(hideTimer);
      item.text = `$(${failed ? 'error' : 'check'}) ${text}`;
      item.tooltip = tooltip || text;
      item.backgroundColor = failed ? new vscode.ThemeColor('statusBarItem.errorBackground') : undefined;
      item.show();
      hideTimer = setTimeout(() => item.hide(), DONE_VISIBLE_MS);
    },
    hide() {
      clearTimeout(hideTimer);
      item.hide();
    },
    dispose() {
      clearTimeout(hideTimer);
      item.dispose();
    },
  };
}

module.exports = { createProgressStatus };
