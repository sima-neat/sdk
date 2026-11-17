'use strict';

// Lets coding agents act in this VS Code window. Each window runs an MCP
// server on 127.0.0.1 (./mcpServer.js) and writes a discovery file to
// ~/.sima-neat-vscode/windows/. Agents start ~/.sima-neat-vscode/bridge.js
// (./bridge.js), which passes their tool calls to the right window.
// When Claude Code is installed, the bridge is registered with it as a user
// MCP server, without asking (simaNeat.agents.connectClaudeCode).
//
// A window attached to a Neat SDK container also serves Claude Code running
// inside that container (the one in the SDK window's side bar). The container
// can't reach the host's 127.0.0.1, so the window installs relay.js and the
// bridge in the container's ~/.sima-neat-vscode and keeps the relay running
// over docker exec (./containerLink.js). The relay serves the tools on a
// socket there and passes requests to this window through docker exec's
// stdin/stdout, which works with any Docker: Linux, macOS, Windows. The
// bridge is registered with the container's Claude Code through docker exec.

const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const { startMcpServer } = require('./mcpServer');
const { startContainerLink } = require('./containerLink');
const { createProgressStatus } = require('../progressStatus');
const container = require('../container');

const SERVER_NAME = 'sima-neat-vscode';
const STATE_DIR = path.join(os.homedir(), '.sima-neat-vscode');
const BRIDGE_FILE = path.join(STATE_DIR, 'bridge.js');
const WINDOW_ENV = 'SIMA_NEAT_VSCODE_WINDOW';
// Version 0.0.19 served containers from this folder in the shared workspace.
const OLD_WORKSPACE_FOLDER = '.sima-neat-vscode';
const OLD_WORKSPACE_MARKER = '# Written by SiMa Neat Tools';
const INSTRUCTIONS = "Tools that act in the user's VS Code window, where SiMa Neat Tools manages the Neat SDK. "
  + 'Use them to show SiMa pages to the user instead of telling them how to open those pages.';

let output;

function logLine(text) {
  if (output) {
    output.appendLine(`[${new Date().toLocaleTimeString()}] ${text}`);
  }
}

function buildTools({ openInsight }) {
  return [
    {
      name: 'open_insight',
      description: "Opens SiMa Neat Insight in an editor tab of the user's VS Code window. Insight is the Neat SDK's web UI "
        + 'for watching pipelines, video streams and performance metrics; it runs in the Neat SDK container. Use it when the '
        + 'user asks to see Insight, or after starting a pipeline whose output or metrics they will want to watch. '
        + 'Returns the URL that was opened, or why it could not be opened (for example, no SDK container is running).',
      inputSchema: { type: 'object', properties: {}, additionalProperties: false },
      async run() {
        const result = await openInsight({ showErrors: false });
        if (result.error) {
          return { text: `Couldn't open Insight: ${result.error}`, isError: true };
        }
        return { text: `Opened Insight in an editor tab of the user's VS Code window: ${result.url}` };
      },
    },
  ];
}

function windowFileIn(dir) {
  return path.join(dir, 'windows', `${process.pid}.json`);
}

function writePrivate(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`, { mode: 0o600 });
  fs.chmodSync(file, 0o600);
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

/** Removes discovery files and sockets of VS Code windows that are gone. */
function removeStaleWindows(dir) {
  for (const sub of ['windows', '.']) {
    let names = [];
    try {
      names = fs.readdirSync(path.join(dir, sub));
    } catch {
      continue;
    }
    for (const name of names) {
      const match = /^(\d+)\.(json|sock)$/.exec(name);
      const pid = match && Number(match[1]);
      if (pid && pid !== process.pid && !isAlive(pid)) {
        fs.rmSync(path.join(dir, sub, name), { force: true });
      }
    }
  }
}

/** Puts the bridge and the tool list in a state folder. */
function prepareStateDir(dir, tools, version) {
  removeStaleWindows(dir);
  fs.mkdirSync(path.join(dir, 'windows'), { recursive: true, mode: 0o700 });
  fs.copyFileSync(path.join(__dirname, 'bridge.js'), path.join(dir, 'bridge.js'));
  writePrivate(path.join(dir, 'tools.json'), {
    version,
    instructions: INSTRUCTIONS,
    tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
  });
}

function localFolders() {
  return (vscode.workspace.workspaceFolders || [])
    .filter((folder) => folder.uri.scheme === 'file')
    .map((folder) => folder.uri.fsPath);
}

function run(file, args, env) {
  return new Promise((resolve) => {
    execFile(file, args, { timeout: 30000, env: env ? { ...process.env, ...env } : process.env }, (error, stdout, stderr) => {
      resolve({ ok: !error, code: error ? error.code : 0, output: `${stdout || ''}${stderr || ''}`.trim() });
    });
  });
}

/** The claude CLI: on PATH, in its usual install folders, or bundled with the Claude Code extension. */
async function findClaude() {
  const exe = process.platform === 'win32' ? 'claude.exe' : 'claude';
  const candidates = ['claude', path.join(os.homedir(), '.local', 'bin', exe), path.join(os.homedir(), '.claude', 'local', exe)];
  const extension = vscode.extensions.getExtension('anthropic.claude-code');
  if (extension) {
    candidates.push(path.join(extension.extensionPath, 'resources', 'native-binary', exe));
  }
  for (const candidate of candidates) {
    if ((await run(candidate, ['--version'])).ok) {
      return candidate;
    }
  }
  return undefined;
}

/** How to run bridge.js: Node.js if it's installed, else VS Code's own runtime in Node mode. */
async function bridgeCommand() {
  if ((await run('node', ['--version'])).ok) {
    return { command: 'node', env: {} };
  }
  return { command: process.execPath, env: { ELECTRON_RUN_AS_NODE: '1' } };
}

/** Claude Code's user settings file, where `claude mcp add --scope user` saves servers. */
function claudeConfigFile() {
  return path.join(process.env.CLAUDE_CONFIG_DIR || os.homedir(), '.claude.json');
}

/** Our entry in Claude Code's user MCP servers, if any. Only reads that one entry. */
function registeredEntry() {
  try {
    const config = JSON.parse(fs.readFileSync(claudeConfigFile(), 'utf8'));
    return config.mcpServers && config.mcpServers[SERVER_NAME];
  } catch {
    return undefined;
  }
}

function isUpToDate(entry, { command, args, env }) {
  return Boolean(entry)
    && entry.command === command
    && JSON.stringify(entry.args || []) === JSON.stringify(args)
    && Object.entries(env).every(([key, value]) => entry.env && entry.env[key] === value);
}

/** Registers the bridge with Claude Code. Resolves with { ok, message }. */
async function register(claude) {
  const bridge = await bridgeCommand();
  const envArgs = Object.entries(bridge.env).flatMap(([key, value]) => ['-e', `${key}=${value}`]);
  // Replace any earlier registration, which may point at an old runtime.
  await run(claude, ['mcp', 'remove', '--scope', 'user', SERVER_NAME]);
  const added = await run(claude, ['mcp', 'add', '--scope', 'user', SERVER_NAME, ...envArgs, '--', bridge.command, BRIDGE_FILE]);
  logLine(added.ok ? `Connected Claude Code (${claude}) to VS Code.` : `Connecting Claude Code failed: ${added.output}`);
  return { ok: added.ok, message: added.output || `exit code ${added.code}` };
}

/** The Connect command: registers even if it looks current, and says what happened. */
async function connectClaudeCode() {
  await vscode.workspace.getConfiguration('simaNeat').update('agents.connectClaudeCode', true, vscode.ConfigurationTarget.Global);
  const state = await startup;
  if (state && state.link) {
    // In an SDK window, the Claude Code that matters is the one in the container.
    const { problem } = await connectContainer(undefined, { force: true });
    if (problem) {
      vscode.window.showErrorMessage(problem);
    } else if (containerConnected) {
      vscode.window.showInformationMessage(
        'Claude Code in the SDK container can now open SiMa pages in this window. Start a new Claude session to pick it up.');
    } else {
      vscode.window.showWarningMessage('Claude Code is not installed in the SDK container yet.');
    }
  }
  const claude = await findClaude();
  if (!claude) {
    if (!(state && state.link)) {
      vscode.window.showErrorMessage('Claude Code was not found on this computer. Install it, then run this again.');
    }
    return;
  }
  const result = await register(claude);
  if (result.ok) {
    vscode.window.showInformationMessage(
      'Claude Code can now open SiMa pages in VS Code. Claude sessions that are already running pick it up after a restart.');
  } else {
    vscode.window.showErrorMessage(`Couldn't connect Claude Code to VS Code: ${result.message}`);
  }
}

/** Removes the registration and stops connecting automatically. */
async function disconnectClaudeCode() {
  await vscode.workspace.getConfiguration('simaNeat').update('agents.connectClaudeCode', false, vscode.ConfigurationTarget.Global);
  const claude = await findClaude();
  if (claude && registeredEntry()) {
    const removed = await run(claude, ['mcp', 'remove', '--scope', 'user', SERVER_NAME]);
    logLine(removed.ok ? 'Disconnected Claude Code from VS Code.' : `Disconnecting Claude Code failed: ${removed.output}`);
  }
  await disconnectContainerClaude();
  vscode.window.showInformationMessage('Claude Code no longer uses VS Code tools. Connect again from the SiMa Neat menu.');
}

// ─────────────── Claude Code inside the SDK container ───────────────

// Resolves with { server, link }: link is set in a window attached to an SDK
// container whose /workspace is shared from this computer.
let startup = Promise.resolve(undefined);
let containerConnected = false;
let containerConnecting;

// Finds, in the container, the claude CLI that comes with the Claude Code
// extension, else one on PATH.
const FIND_IN_CONTAINER = [
  'claude=$(ls -1d "$HOME"/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | sort -V | tail -n 1)',
  '[ -n "$claude" ] || claude=$(command -v claude || true)',
  'printf "%s\\n" "$claude"',
].join('\n');

// Prints only our entry of the container's Claude Code user MCP servers.
const READ_ENTRY_JS = "const p=require('path'),f=p.join(process.env.CLAUDE_CONFIG_DIR||require('os').homedir(),'.claude.json');"
  + "let e=null;try{e=(JSON.parse(require('fs').readFileSync(f,'utf8')).mcpServers||{})[process.argv[1]]||null}catch(_){}"
  + 'process.stdout.write(JSON.stringify(e))';

/** Removes the folder 0.0.19 put in the shared workspace; the relay doesn't need it. */
function removeOldWorkspaceFolder(workspace) {
  if (!workspace) {
    return;
  }
  const dir = path.join(workspace, OLD_WORKSPACE_FOLDER);
  try {
    if (fs.readFileSync(path.join(dir, '.gitignore'), 'utf8').startsWith(OLD_WORKSPACE_MARKER)) {
      fs.rmSync(dir, { recursive: true, force: true });
      logLine(`Removed ${dir}, which an older version of this extension used.`);
    }
  } catch {
    // Not there, or not ours.
  }
}

/** In a window attached to an SDK container: serves the tools in the container through the relay. */
async function serveContainer(server, tools, version) {
  const name = container.containerOfThisWindow();
  if (!name) {
    return undefined;
  }
  const target = await container.currentContainer();
  if (!target || target.name !== name) {
    return undefined; // Not a Neat SDK container.
  }
  removeOldWorkspaceFolder(target.workspace);
  const read = (file) => fs.readFileSync(path.join(__dirname, file), 'utf8');
  const relay = await startContainerLink({
    target,
    respond: server.respond,
    windowPid: process.pid,
    log: logLine,
    files: {
      'relay.js': read('relay.js'),
      'bridge.js': read('bridge.js'),
      'tools.json': `${JSON.stringify({
        version,
        instructions: INSTRUCTIONS,
        tools: tools.map(({ name: toolName, description, inputSchema }) => ({ name: toolName, description, inputSchema })),
      }, null, 2)}\n`,
    },
  });
  logLine(`Serving Claude Code in container ${name} from ${relay.dir}.`);
  return { target, relay };
}

/**
 * Registers the bridge with Claude Code inside this window's SDK container,
 * unless it's already registered the same way. Shows its step on status.
 * Resolves with { problem, registered }.
 */
async function connectContainer(status, { force = false } = {}) {
  const state = await startup;
  const link = state && state.link;
  const config = vscode.workspace.getConfiguration('simaNeat');
  if (!link || !config.get('agents.connectClaudeCode', true)) {
    return {};
  }
  if (containerConnecting) {
    return containerConnecting;
  }
  containerConnecting = (async () => {
    const { target } = link;
    try {
      const claude = (await container.execIn(target, 'bash', ['-c', FIND_IN_CONTAINER])).split('\n')[0].trim();
      if (!claude) {
        return {}; // Claude Code isn't in the container (yet).
      }
      const { dir, node } = link.relay;
      const wanted = {
        command: node,
        args: [`${dir}/bridge.js`],
        env: { SIMA_NEAT_VSCODE_DIR: dir, SIMA_NEAT_CONTAINER: target.name },
      };
      const entry = JSON.parse(await container.execIn(target, node, ['-e', READ_ENTRY_JS, SERVER_NAME]) || 'null');
      if (!force && isUpToDate(entry, wanted)) {
        containerConnected = true;
        return {};
      }
      if (status) {
        status.step('Neat SDK: connecting Claude Code to VS Code…', 'Lets Claude Code in the container open SiMa pages, such as Insight, in this window.');
      }
      await container.execIn(target, claude, ['mcp', 'remove', '--scope', 'user', SERVER_NAME], { timeout: 30000 }).catch(() => undefined);
      const envArgs = Object.entries(wanted.env).flatMap(([key, value]) => ['-e', `${key}=${value}`]);
      await container.execIn(target, claude, ['mcp', 'add', '--scope', 'user', SERVER_NAME, ...envArgs, '--', node, `${dir}/bridge.js`], { timeout: 30000 });
      containerConnected = true;
      logLine(`Connected Claude Code in container ${target.name} to this window.`);
      return { registered: true };
    } catch (error) {
      logLine(`Connecting Claude Code in container ${target.name} failed: ${error.message}`);
      return { problem: `Claude Code in the container can't open SiMa pages: ${error.message}` };
    } finally {
      containerConnecting = undefined;
    }
  })();
  return containerConnecting;
}

/** For the SDK window: connects, and resolves with a problem to report or undefined. */
async function connectContainerClaude(status) {
  return (await connectContainer(status)).problem;
}

/** Connects in the background, with its own status item. */
async function connectContainerInBackground(status) {
  const { problem, registered } = await connectContainer(status);
  if (problem) {
    status.finish('Claude Code not connected', { failed: true, tooltip: problem });
  } else if (registered) {
    status.finish('Claude Code can use VS Code', { tooltip: 'Claude Code in the SDK container can open SiMa pages, such as Insight, in this window. New Claude sessions get it.' });
  }
}

async function disconnectContainerClaude() {
  const state = await startup;
  const link = state && state.link;
  if (!link) {
    return;
  }
  try {
    const claude = (await container.execIn(link.target, 'bash', ['-c', FIND_IN_CONTAINER])).split('\n')[0].trim();
    if (claude) {
      await container.execIn(link.target, claude, ['mcp', 'remove', '--scope', 'user', SERVER_NAME], { timeout: 30000 });
      logLine(`Disconnected Claude Code in container ${link.target.name}.`);
    }
  } catch (error) {
    logLine(`Disconnecting Claude Code in container ${link.target.name} failed: ${error.message}`);
  }
  containerConnected = false;
}

let autoConnecting = false;

/**
 * Connects Claude Code without asking when it's installed and not connected,
 * or connected with an outdated command. Runs at startup and whenever
 * extensions change (for example, right after Claude Code is installed).
 */
async function autoConnectClaudeCode(status) {
  const config = vscode.workspace.getConfiguration('simaNeat');
  if (autoConnecting || !config.get('agents.enabled', true) || !config.get('agents.connectClaudeCode', true)) {
    return;
  }
  autoConnecting = true;
  try {
    const claude = await findClaude();
    if (!claude || isUpToDate(registeredEntry(), { ...(await bridgeCommand()), args: [BRIDGE_FILE] })) {
      return;
    }
    status.step('Connecting Claude Code to VS Code…');
    const result = await register(claude);
    if (result.ok) {
      status.finish('Claude Code can use VS Code', { tooltip: 'Claude Code can open SiMa pages, such as Insight, in VS Code. New Claude sessions get it; running ones after a restart.' });
    } else {
      status.finish('Claude Code not connected', { failed: true, tooltip: `${result.message}\nRun "SiMa Neat: Connect Claude Code to VS Code" to try again.` });
    }
  } finally {
    autoConnecting = false;
  }
}

async function init(context, { openInsight }) {
  output = vscode.window.createOutputChannel('SiMa Neat Agents');
  context.subscriptions.push(
    output,
    vscode.commands.registerCommand('simaNeat.connectClaudeCode', () => connectClaudeCode()),
    vscode.commands.registerCommand('simaNeat.disconnectClaudeCode', () => disconnectClaudeCode()),
    vscode.commands.registerCommand('simaNeat.showAgentLog', () => output.show()),
  );
  if (!vscode.workspace.getConfiguration('simaNeat').get('agents.enabled', true)) {
    return;
  }
  startup = start(context, buildTools({ openInsight })).catch((error) => {
    logLine(`Couldn't start the agent server: ${error.message}`);
    return undefined;
  });
  const state = await startup;
  if (!state) {
    return;
  }

  const status = createProgressStatus('simaNeat.agentsProgress', 'SiMa Neat: coding agents');
  const autoConnect = () => autoConnectClaudeCode(status).catch((error) => logLine(`Claude Code check failed: ${error.message}`));
  // Claude Code installed later in the container (the SDK window does the first time itself).
  const connectContainerLater = async () => {
    if (state.link && (await vscode.commands.getCommands(true)).includes('claude-vscode.sidebar.open')) {
      await connectContainerInBackground(status);
    }
  };
  // Installing the Claude Code extension changes the extensions list.
  context.subscriptions.push(status, vscode.extensions.onDidChange(() => {
    autoConnect();
    connectContainerLater();
  }));
  autoConnect();
  // Without the SDK window layout, nothing opens Claude Code: connect it once it's there.
  if (state.link && !vscode.workspace.getConfiguration('simaNeat.sdk').get('windowLayout', true)) {
    const sdkWindow = require('../sdkWindow');
    if (await sdkWindow.whenCommandExists(sdkWindow.CLAUDE_OPEN_COMMAND, 120000)) {
      await connectContainerInBackground(status);
    }
  }
}

async function start(context, tools) {
  const version = context.extension.packageJSON.version;
  const server = await startMcpServer({
    tools,
    serverInfo: { name: SERVER_NAME, version },
    instructions: INSTRUCTIONS,
    onCall: (name, args, outcome) => logLine(`${name} ${JSON.stringify(args)} → ${outcome.isError ? 'error' : 'ok'}: ${outcome.text}`),
  });
  logLine(`Agent server listening on 127.0.0.1:${server.port} for this window (pid ${process.pid}).`);
  try {
    prepareStateDir(STATE_DIR, tools, version);
  } catch (error) {
    logLine(`Couldn't set up ${STATE_DIR}: ${error.message}`);
  }
  let link;
  try {
    link = await serveContainer(server, tools, version);
  } catch (error) {
    logLine(`Couldn't serve the SDK container: ${error.message}`);
  }

  let focusedAt = vscode.window.state.focused ? Date.now() : 0;
  const publish = () => {
    const common = { pid: process.pid, token: server.token, name: vscode.workspace.name || '', focusedAt, version };
    const files = [[windowFileIn(STATE_DIR), { ...common, port: server.port, folders: localFolders() }]];
    if (link) {
      // The relay writes it in the container.
      link.relay.update({ ...common, container: link.target.name, folders: [container.CONTAINER_WORKSPACE] });
    }
    for (const [file, data] of files) {
      try {
        writePrivate(file, data);
      } catch (error) {
        logLine(`Couldn't write ${file}: ${error.message}`);
      }
    }
  };
  publish();

  // Agents started in this window's terminals use this window, also in the container.
  context.environmentVariableCollection.persistent = false;
  context.environmentVariableCollection.description = 'Lets coding agents started here act in this VS Code window.';
  context.environmentVariableCollection.replace(WINDOW_ENV, String(process.pid));

  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((windowState) => {
      if (windowState.focused) {
        focusedAt = Date.now();
        publish();
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(publish),
    {
      dispose: () => {
        fs.rmSync(windowFileIn(STATE_DIR), { force: true });
        server.close();
        if (link) {
          link.relay.dispose();
        }
      },
    },
  );
  return { server, link };
}

/** Whether Claude Code has our server registered (for the status bar menu). */
function isClaudeCodeConnected() {
  return containerConnected || Boolean(registeredEntry());
}

module.exports = { init, isUpToDate, isClaudeCodeConnected, connectContainerClaude };
