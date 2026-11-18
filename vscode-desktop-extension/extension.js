'use strict';

const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const setupPanel = require('./setupPanel');
const hostStatus = require('./hostStatus');
const devcontainer = require('./devcontainer');
const container = require('./container');
const neatPages = require('./neat');
const hostTerminal = require('./hostTerminal');
const sdkWindow = require('./sdkWindow');
const agents = require('./agents');

const INSTALLER_URL_UNIX = 'https://artifacts.neat.sima.ai/sima-cli/linux-mac.sh';
const INSTALLER_URL_WINDOWS = 'https://artifacts.neat.sima.ai/sima-cli/windows.bat';
const IS_WINDOWS = process.platform === 'win32';
const EXE_NAME = IS_WINDOWS ? 'sima-cli.exe' : 'sima-cli';
const SIMA_CLI_HOME = path.join(os.homedir(), '.sima-cli');
const EXTERNAL_TOKEN_FILE = path.join(SIMA_CLI_HOME, '.tokens.json');
const INTERNAL_CONFIG_FILE = path.join(SIMA_CLI_HOME, 'config.json');
// Stops sima-cli from blocking on its "update now? [Y/n]" prompt.
const NO_UPDATE_PROMPT = { SIMA_CLI_CHECK_FOR_UPDATE: '0' };
const CLI_ENV = { ...process.env, ...NO_UPDATE_PROMPT };

let statusItem;
// Last detection result: { file, onPath, version } or undefined.
let simaCli;
const runningTerminals = new Map();
// Fires when sima-cli or login state may have changed, for the setup page.
const stateChanged = new vscode.EventEmitter();
const FIRST_RUN_KEY = 'simaNeat.setupShown';

// Where the official installers put the sima-cli virtualenv.
function knownInstallDirs() {
  const home = os.homedir();
  if (IS_WINDOWS) {
    return [path.join(home, '.sima-cli-env', 'Scripts')];
  }
  return [
    path.join(home, '.sima-cli', '.venv', 'bin'),
    '/data/sima-cli/.venv/bin', // DevKit
    path.join(home, '.local', 'bin'),
  ];
}

function isExecutable(file) {
  try {
    fs.accessSync(file, IS_WINDOWS ? fs.constants.F_OK : fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

/** Returns { file, onPath } for the first sima-cli found, or undefined. */
function findSimaCli() {
  const pathDirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  for (const dir of pathDirs) {
    const file = path.join(dir, EXE_NAME);
    if (isExecutable(file)) {
      return { file, onPath: true };
    }
  }
  for (const dir of knownInstallDirs()) {
    const file = path.join(dir, EXE_NAME);
    if (isExecutable(file)) {
      return { file, onPath: false };
    }
  }
  return undefined;
}

function execSimaCli(file, args) {
  return new Promise((resolve) => {
    execFile(file, args, { env: CLI_ENV, timeout: 60000 }, (err, stdout, stderr) => {
      resolve({ error: err ? err.message : undefined, output: `${stdout || ''}\n${stderr || ''}` });
    });
  });
}

async function readVersion(file) {
  const { output } = await execSimaCli(file, ['--version']);
  const match = output.match(/version:?\s*v?(\d[^\s]*)/i);
  return match ? match[1] : undefined;
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return undefined;
  }
}

// Reads JWT claims without verifying them; only used to show who is logged in.
function jwtClaims(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(Buffer.from(payload, 'base64').toString('utf8'));
  } catch {
    return {};
  }
}

/** Login state as sima-cli stores it under ~/.sima-cli. */
function readLoginState() {
  const state = { external: { loggedIn: false }, internal: { loggedIn: false } };

  const tokens = readJson(EXTERNAL_TOKEN_FILE);
  if (tokens && (tokens.refresh_token || tokens.access_token)) {
    const claims = tokens.id_token ? jwtClaims(tokens.id_token) : {};
    state.external = { loggedIn: true, user: claims.email || claims.name || claims.nickname };
  }

  const internal = (readJson(INTERNAL_CONFIG_FILE) || {}).internal || {};
  if (internal.auth_token) {
    const { exp } = jwtClaims(internal.auth_token);
    state.internal = {
      loggedIn: true,
      user: internal.auth_username,
      expired: typeof exp === 'number' && exp * 1000 < Date.now(),
    };
  }
  return state;
}

function showInternalLogin(login) {
  return vscode.workspace.getConfiguration('simaNeat').get('showInternalLogin', false) || login.internal.loggedIn;
}

function updateStatusBar() {
  stateChanged.fire();
  // On this computer the status bar shows only the SDK setup status (hostStatus.js).
  if (!vscode.env.remoteName) {
    statusItem.hide();
    return;
  }
  if (!simaCli) {
    statusItem.text = '$(cloud-download) Install sima-cli';
    statusItem.tooltip = 'sima-cli was not found. Click to open SiMa Neat Setup.';
    statusItem.command = 'simaNeat.openSetup';
    statusItem.show();
    return;
  }

  const login = readLoginState();
  const label = `$(tools) sima-cli ${simaCli.version || ''}`.trim();
  statusItem.text = login.external.loggedIn ? `${label} $(account)` : `${label} $(sign-in) Log in`;
  statusItem.command = 'simaNeat.showMenu';

  const lines = [`**sima-cli** ${simaCli.version || ''} — \`${simaCli.file}\``, ''];
  if (login.external.loggedIn) {
    lines.push(`$(account) Developer Portal: logged in${login.external.user ? ` as ${login.external.user}` : ''}`);
    lines.push('', '[$(sign-out) Log out](command:simaNeat.logout)');
  } else {
    lines.push('$(circle-slash) Developer Portal: not logged in');
    lines.push('', '[$(sign-in) Log in](command:simaNeat.login)');
  }
  if (showInternalLogin(login)) {
    lines.push('', '---', '');
    if (login.internal.loggedIn) {
      const who = login.internal.user ? ` as ${login.internal.user}` : '';
      lines.push(`$(key) Internal: logged in${who}${login.internal.expired ? ' (token expired)' : ''}`);
      lines.push('', '[$(sign-in) Log in again](command:simaNeat.loginInternal) · [$(sign-out) Log out](command:simaNeat.logoutInternal)');
    } else {
      lines.push('$(key) Internal: not logged in', '', '[$(sign-in) Log in](command:simaNeat.loginInternal)');
    }
  }
  const tooltip = new vscode.MarkdownString(lines.join('\n'), true);
  tooltip.isTrusted = {
    enabledCommands: ['simaNeat.login', 'simaNeat.logout', 'simaNeat.loginInternal', 'simaNeat.logoutInternal'],
  };
  statusItem.tooltip = tooltip;
  statusItem.show();
}

async function refresh(context) {
  const found = findSimaCli();
  exposeOnTerminalPath(context, found);
  simaCli = found ? { ...found, version: await readVersion(found.file) } : undefined;
  updateStatusBar();
  return simaCli;
}

// Make sima-cli available in integrated terminals even when the shell rc
// file the installer edited is not sourced (e.g. .bash_profile in the SDK).
function exposeOnTerminalPath(context, found) {
  const env = context.environmentVariableCollection;
  env.clear();
  // In a remote window, integrated terminals run on the remote side, where this path doesn't exist.
  if (found && !found.onPath && !hostTerminal.isRemoteWindow()) {
    env.prepend('PATH', path.dirname(found.file) + path.delimiter);
    env.description = `Adds ${path.dirname(found.file)} to PATH so sima-cli is available.`;
  }
}

function shellQuote(value) {
  return IS_WINDOWS ? `'${value.replace(/'/g, "''")}'` : `'${value.replace(/'/g, "'\\''")}'`;
}

/**
 * Opens a terminal on this computer running shellPath with shellArgs. In a
 * remote window an ordinary terminal would start on the remote side, so there
 * it's a pseudoterminal backed by a local process.
 */
function openHostTerminal({ name, shellPath, shellArgs, env = {} }) {
  const fullEnv = { ...NO_UPDATE_PROMPT, ...env };
  if (!hostTerminal.isRemoteWindow()) {
    return vscode.window.createTerminal({ name, env: fullEnv, shellPath, shellArgs });
  }
  if (simaCli && !simaCli.onPath) {
    fullEnv.PATH = `${path.dirname(simaCli.file)}${path.delimiter}${process.env.PATH || ''}`;
  }
  return hostTerminal.createHostTerminal({ name, file: shellPath, args: shellArgs, env: fullEnv });
}

/** Opens an interactive shell on this computer that first runs command, which starts with a quoted program path. */
function openHostShell(name, command) {
  const terminal = IS_WINDOWS
    ? openHostTerminal({ name, shellPath: 'powershell.exe', shellArgs: ['-NoExit', '-Command', `& ${command}`] })
    : openHostTerminal({ name, shellPath: '/bin/bash', shellArgs: ['-c', `${command}\nexec bash -i`] });
  terminal.show();
  return terminal;
}

/**
 * Runs a command in a visible terminal that stays open until the user presses
 * Enter, then calls onDone(exitCode). One terminal per key at a time.
 */
function runInTerminal(context, key, name, command, onDone) {
  const existing = runningTerminals.get(key);
  if (existing) {
    existing.show();
    return;
  }
  const options = IS_WINDOWS
    ? {
      shellPath: 'powershell.exe',
      shellArgs: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        `${command}; $code = $LASTEXITCODE; Write-Host ''; Read-Host 'Press Enter to close this terminal'; exit $code`],
    }
    : {
      shellPath: '/bin/bash',
      shellArgs: ['-c', `${command}\nstatus=$?\necho\nread -r -p "Press Enter to close this terminal." _\nexit $status`],
    };
  const terminal = openHostTerminal({ name, ...options });
  runningTerminals.set(key, terminal);
  terminal.show();

  const listener = vscode.window.onDidCloseTerminal((closed) => {
    if (closed !== terminal) {
      return;
    }
    listener.dispose();
    runningTerminals.delete(key);
    onDone(closed.exitStatus ? closed.exitStatus.code : undefined);
  });
  context.subscriptions.push(listener);
}

async function installSimaCli(context) {
  const url = IS_WINDOWS ? INSTALLER_URL_WINDOWS : INSTALLER_URL_UNIX;
  const choice = await vscode.window.showInformationMessage(
    'Install sima-cli with the official SiMa.ai installer?',
    {
      modal: true,
      detail: `This downloads and runs ${url} in a terminal. It creates a Python virtualenv, `
        + 'may ask for your sudo password to install python3-venv, and adds sima-cli to your shell profile.',
    },
    'Install',
  );
  if (choice !== 'Install') {
    return;
  }
  const command = IS_WINDOWS
    ? [
      "$f = Join-Path $env:TEMP 'sima-cli-install.bat'",
      `Invoke-WebRequest -UseBasicParsing '${url}' -OutFile $f`,
      '& cmd.exe /c $f',
    ].join('; ')
    : [
      'set -o pipefail',
      `if command -v curl >/dev/null 2>&1; then curl -fsSL '${url}' | bash;`,
      `else wget -qO- '${url}' | bash; fi`,
    ].join('\n');

  runInTerminal(context, 'install', 'sima-cli install', command, async (code) => {
    const result = await refresh(context);
    if (result) {
      const label = result.version ? `sima-cli ${result.version}` : 'sima-cli';
      vscode.window.showInformationMessage(`${label} is installed. Open a new terminal to use it.`);
    } else {
      vscode.window.showErrorMessage(
        `sima-cli was not found after the installer finished${code !== undefined ? ` (exit ${code})` : ''}.`,
      );
    }
  });
}

/** Returns the detected sima-cli, offering to install it when missing. */
async function requireSimaCli(context) {
  const found = await refresh(context);
  if (!found) {
    const choice = await vscode.window.showWarningMessage('sima-cli is not installed.', 'Install');
    if (choice === 'Install') {
      await installSimaCli(context);
    }
  }
  return found;
}

async function login(context, internal) {
  const found = await requireSimaCli(context);
  if (!found) {
    return;
  }
  const args = internal ? '--internal login' : 'login';
  const command = IS_WINDOWS ? `& ${shellQuote(found.file)} ${args}` : `${shellQuote(found.file)} ${args}`;
  const name = internal ? 'sima-cli login (internal)' : 'sima-cli login';
  runInTerminal(context, internal ? 'login-internal' : 'login', name, command, () => {
    const state = readLoginState()[internal ? 'internal' : 'external'];
    updateStatusBar();
    if (state.loggedIn) {
      vscode.window.showInformationMessage(`Logged in to sima-cli${state.user ? ` as ${state.user}` : ''}.`);
    } else {
      vscode.window.showWarningMessage('sima-cli login did not complete. Check the terminal output and try again.');
    }
  });
}

async function logout(context, internal) {
  const found = await requireSimaCli(context);
  if (!found) {
    return;
  }
  const args = internal ? ['--internal', 'logout'] : ['logout'];
  const { error, output } = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: 'Logging out of sima-cli…' },
    () => execSimaCli(found.file, args),
  );
  updateStatusBar();
  const state = readLoginState()[internal ? 'internal' : 'external'];
  if (error || state.loggedIn) {
    vscode.window.showErrorMessage(`sima-cli logout failed: ${(error || output).trim().split('\n').pop()}`);
  } else {
    vscode.window.showInformationMessage(internal ? 'Logged out of internal SiMa services.' : 'Logged out of the SiMa Developer Portal.');
  }
}

async function checkSimaCli(context) {
  const found = await requireSimaCli(context);
  if (!found) {
    return;
  }
  const where = found.onPath ? 'on PATH' : 'added to the terminal PATH by this extension';
  vscode.window.showInformationMessage(`sima-cli ${found.version || '(unknown version)'} at ${found.file} (${where}).`);
}

async function openSimaCliTerminal(context) {
  const found = await requireSimaCli(context);
  if (!found) {
    return;
  }
  openHostShell('sima-cli', `${shellQuote(found.file)} --help`);
}

async function showMenu(context) {
  if (!simaCli) {
    setupPanel.show();
    return;
  }
  const login = readLoginState();
  const items = [];
  items.push({ label: '$(remote) Open SDK in VS Code', description: 'work inside the SDK container', run: () => devcontainer.openSdkInVsCode() });
  items.push({ label: '$(rocket) Open Neat Setup', description: 'install and start the Neat SDK', run: () => setupPanel.show() });
  items.push({ label: 'Neat SDK', kind: vscode.QuickPickItemKind.Separator });
  items.push({ label: '$(home) Getting Started', description: 'SDK, DevKit, apps, models and agents', run: () => vscode.commands.executeCommand('simaNeat.openGettingStarted') });
  items.push({ label: '$(layout-sidebar-left) Palette panel', run: () => vscode.commands.executeCommand('simaNeat.openPalettePanel') });
  items.push({ label: '$(pulse) Insight', run: () => vscode.commands.executeCommand('simaNeat.openInsight') });
  items.push({ label: '$(package) Browse models', run: () => vscode.commands.executeCommand('simaNeat.browseModelRegistry') });
  items.push({ label: 'Coding agents', kind: vscode.QuickPickItemKind.Separator });
  if (agents.isClaudeCodeConnected()) {
    items.push({ label: '$(debug-disconnect) Disconnect Claude Code from VS Code', description: 'Claude stops opening SiMa pages here', run: () => vscode.commands.executeCommand('simaNeat.disconnectClaudeCode') });
  } else {
    items.push({ label: '$(plug) Connect Claude Code to VS Code', description: 'lets Claude open SiMa pages here', run: () => vscode.commands.executeCommand('simaNeat.connectClaudeCode') });
  }
  items.push({ label: '$(output) Agent tool log', run: () => vscode.commands.executeCommand('simaNeat.showAgentLog') });
  items.push({ label: 'Developer Portal', kind: vscode.QuickPickItemKind.Separator });
  if (login.external.loggedIn) {
    items.push({
      label: '$(sign-out) Log out',
      description: login.external.user ? `logged in as ${login.external.user}` : 'logged in',
      run: () => logout(context, false),
    });
  } else {
    items.push({ label: '$(sign-in) Log in', description: 'not logged in', run: () => login(context, false) });
  }
  if (showInternalLogin(login)) {
    items.push({ label: 'Internal (SiMa employees)', kind: vscode.QuickPickItemKind.Separator });
    if (login.internal.loggedIn) {
      const status = `${login.internal.user || 'logged in'}${login.internal.expired ? ' · token expired' : ''}`;
      items.push({ label: '$(sign-in) Log in again (internal)', description: status, run: () => login(context, true) });
      items.push({ label: '$(sign-out) Log out (internal)', run: () => logout(context, true) });
    } else {
      items.push({ label: '$(sign-in) Log in (internal)', description: 'Artifactory identity token', run: () => login(context, true) });
    }
  }
  items.push({ label: 'sima-cli', kind: vscode.QuickPickItemKind.Separator });
  items.push({ label: '$(terminal) Open sima-cli terminal', run: () => openSimaCliTerminal(context) });
  items.push({ label: '$(info) Check sima-cli', description: simaCli.version, run: () => checkSimaCli(context) });
  items.push({ label: '$(cloud-download) Install or update sima-cli', run: () => installSimaCli(context) });

  const picked = await vscode.window.showQuickPick(items, { placeHolder: 'SiMa Neat' });
  if (picked && picked.run) {
    await picked.run();
  }
}

async function promptIfMissing(context) {
  const config = vscode.workspace.getConfiguration('simaNeat');
  if (!config.get('promptToInstall', true)) {
    return;
  }
  const choice = await vscode.window.showInformationMessage(
    'sima-cli is not installed. Install it now?',
    'Install',
    'Not now',
    "Don't ask again",
  );
  if (choice === 'Install') {
    await installSimaCli(context);
  } else if (choice === "Don't ask again") {
    await config.update('promptToInstall', false, vscode.ConfigurationTarget.Global);
  }
}

// Keep the status bar in sync when login happens in any terminal.
function watchLoginFiles(context) {
  const watcher = vscode.workspace.createFileSystemWatcher(
    new vscode.RelativePattern(vscode.Uri.file(SIMA_CLI_HOME), '{.tokens.json,config.json}'),
  );
  watcher.onDidCreate(updateStatusBar);
  watcher.onDidChange(updateStatusBar);
  watcher.onDidDelete(updateStatusBar);
  context.subscriptions.push(watcher);
}

async function activate(context) {
  setupPanel.init(context, {
    getSimaCli: () => simaCli,
    readLoginState,
    installSimaCli: () => installSimaCli(context),
    login: () => login(context, false),
    logout: () => logout(context, false),
    runInTerminal: (key, name, command, onDone) => runInTerminal(context, key, name, command, onDone),
    openHostShell,
    refresh: () => refresh(context),
    onDidChange: stateChanged.event,
    cliEnv: CLI_ENV,
    openSdkInVsCode: (options) => devcontainer.openSdkInVsCode(options),
    isDevContainersInstalled: () => devcontainer.isDevContainersInstalled(),
  });
  container.init(context);
  devcontainer.init(context, { showSetup: () => setupPanel.show() });
  const pages = neatPages.register(context, { getSimaCli: () => simaCli, readLoginState, onDidChange: stateChanged.event });
  agents.init(context, { openInsight: pages.openInsight }).catch((error) => console.error('SiMa Neat agents:', error));
  hostStatus.register(context);
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  context.subscriptions.push(
    statusItem,
    stateChanged,
    vscode.commands.registerCommand('simaNeat.openSetup', () => setupPanel.show()),
    vscode.commands.registerCommand('simaNeat.openSdkInVsCode', () => devcontainer.openSdkInVsCode()),
    vscode.commands.registerCommand('simaNeat.showMenu', () => showMenu(context)),
    vscode.commands.registerCommand('simaNeat.installSimaCli', () => installSimaCli(context)),
    vscode.commands.registerCommand('simaNeat.checkSimaCli', () => checkSimaCli(context)),
    vscode.commands.registerCommand('simaNeat.openSimaCliTerminal', () => openSimaCliTerminal(context)),
    vscode.commands.registerCommand('simaNeat.login', () => login(context, false)),
    vscode.commands.registerCommand('simaNeat.logout', () => logout(context, false)),
    vscode.commands.registerCommand('simaNeat.loginInternal', () => login(context, true)),
    vscode.commands.registerCommand('simaNeat.logoutInternal', () => logout(context, true)),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('simaNeat.showInternalLogin')) {
        updateStatusBar();
      }
    }),
  );
  watchLoginFiles(context);
  const found = await refresh(context);
  if (!context.globalState.get(FIRST_RUN_KEY)) {
    await context.globalState.update(FIRST_RUN_KEY, true);
    setupPanel.show();
  } else if (!found) {
    promptIfMissing(context);
  } else {
    devcontainer.openOnStartup();
  }
  sdkWindow.arrange({ beforeOpenClaude: (status) => agents.connectContainerClaude(status) });
}

function deactivate() {
  setupPanel.dispose();
}

module.exports = { activate, deactivate };
