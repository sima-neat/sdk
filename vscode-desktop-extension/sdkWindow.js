'use strict';

// Arranges a window that's open in an SDK container: the SiMa Getting Started
// page instead of Welcome pages, a terminal in /workspace at the bottom, and
// Claude Code in the secondary side bar on the right. In such a window integrated terminals already run inside the
// container.

const vscode = require('vscode');
const container = require('./container');
const { createProgressStatus } = require('./progressStatus');

const CLAUDE_ID = 'anthropic.claude-code';
// Opens Claude Code in its side bar view, which it places in the secondary side bar.
const CLAUDE_OPEN_COMMAND = 'claude-vscode.sidebar.open';
// A first install in the container downloads the extension; give it time.
const CLAUDE_INSTALL_WAIT_MS = 120000;
const WELCOME_WATCH_EXTRA_MS = 30000;
const TERMINAL_NAME = 'Neat SDK';
// VS Code restores terminals from the last session shortly after startup.
const RESTORE_WAIT_MS = 1500;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function openTerminal() {
  await delay(RESTORE_WAIT_MS);
  if (vscode.window.terminals.length) {
    return; // Restored from the last session.
  }
  const terminal = vscode.window.createTerminal({ name: TERMINAL_NAME, cwd: container.CONTAINER_WORKSPACE });
  terminal.show(true);
}

/**
 * Resolves with true once a command exists, or false after timeoutMs. Claude
 * Code runs in the container's extension host; its commands appear when it has
 * started there, which on a first attach is after Dev Containers installs it.
 */
async function whenCommandExists(command, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if ((await vscode.commands.getCommands(true)).includes(command)) {
      return true;
    }
    if (Date.now() >= deadline) {
      return false;
    }
    await delay(1000);
  }
}

/**
 * Opens Claude Code in the secondary side bar, on the right. Resolves with
 * { problem } if it didn't open, { warning } if it opened with a problem, or {}.
 */
async function openClaude(status, beforeOpenClaude) {
  const wanted = vscode.workspace.getConfiguration('simaNeat.sdk').get('containerExtensions', [CLAUDE_ID])
    .some((id) => id.toLowerCase() === CLAUDE_ID);
  if (!(await vscode.commands.getCommands(true)).includes(CLAUDE_OPEN_COMMAND)) {
    if (!wanted) {
      return {};
    }
    status.step(vscode.extensions.getExtension(CLAUDE_ID)
      ? 'Neat SDK: starting Claude Code…'
      : 'Neat SDK: installing Claude Code in the container…',
    'Dev Containers installs Claude Code in the container the first time; this can take a minute or two.');
    if (!await whenCommandExists(CLAUDE_OPEN_COMMAND, CLAUDE_INSTALL_WAIT_MS)) {
      return { problem: "Claude Code didn't start in time. Check Extensions, or reload the window." };
    }
  }
  // Before Claude's first session starts, so that session already has our tools.
  const connectProblem = beforeOpenClaude ? await beforeOpenClaude(status) : undefined;
  status.step('Neat SDK: opening Claude Code…');
  try {
    await vscode.commands.executeCommand(CLAUDE_OPEN_COMMAND);
  } catch {
    return { problem: 'Claude Code needs a window reload to open: run Developer: Reload Window.' };
  }
  return { warning: connectProblem };
}

// VS Code's Welcome page and Claude Code's first-run walkthrough both open as
// "Welcome" editors. Neither is useful in the SDK window.
function isWelcomeTab(tab) {
  return tab.input === undefined && /^(Welcome|Walkthrough)\b/.test(tab.label);
}

/** Closes Welcome editors that open while the SDK window starts, including Claude Code's walkthrough. */
function closeWelcomeTabs() {
  const close = () => {
    const tabs = vscode.window.tabGroups.all.flatMap((group) => group.tabs).filter(isWelcomeTab);
    if (tabs.length) {
      void vscode.window.tabGroups.close(tabs);
    }
  };
  close();
  const listener = vscode.window.tabGroups.onDidChangeTabs((event) => {
    if (event.opened.some(isWelcomeTab)) {
      close();
    }
  });
  // Claude Code opens its walkthrough a second after it first starts, which can take a while on a first attach.
  setTimeout(() => listener.dispose(), CLAUDE_INSTALL_WAIT_MS + WELCOME_WATCH_EXTRA_MS);
}

/**
 * Opens the SiMa Getting Started page when the window has no editors of its
 * own, after VS Code has had time to restore the last session's tabs. A
 * Getting Started tab restored from last time counts as an editor.
 */
async function openGettingStarted() {
  await delay(RESTORE_WAIT_MS);
  const editors = vscode.window.tabGroups.all.flatMap((group) => group.tabs).filter((tab) => !isWelcomeTab(tab));
  if (!editors.length) {
    await vscode.commands.executeCommand('simaNeat.openGettingStarted');
  }
}

/**
 * Runs once when a window opens in an SDK container. beforeOpenClaude(status)
 * runs once Claude Code is installed there, right before it opens, and
 * resolves with a problem to report or undefined.
 */
async function arrange({ beforeOpenClaude } = {}) {
  const name = container.containerOfThisWindow();
  if (!name || !vscode.workspace.getConfiguration('simaNeat.sdk').get('windowLayout', true)) {
    return;
  }
  const running = (await container.currentContainer());
  if (!running || running.name !== name) {
    return; // Not a Neat SDK container.
  }
  const status = createProgressStatus('simaNeat.sdkWindowProgress', 'Neat SDK: setting up this window');
  status.step('Neat SDK: setting up this window…');
  closeWelcomeTabs();
  const [, , claude] = await Promise.all([openGettingStarted(), openTerminal(), openClaude(status, beforeOpenClaude)]);
  if (claude.problem) {
    status.finish('Neat SDK: ready, without Claude Code', { failed: true, tooltip: claude.problem });
  } else if (claude.warning) {
    status.finish('Neat SDK: ready, Claude Code not connected', { failed: true, tooltip: claude.warning });
  } else {
    status.finish('Neat SDK: ready');
  }
}

module.exports = { arrange, whenCommandExists, CLAUDE_OPEN_COMMAND };
