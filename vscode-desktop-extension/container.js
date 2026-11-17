'use strict';

// Reaches into a Neat SDK container from this computer. This extension runs on
// the host, so the pages ported from the SDK's own extension read container
// files and run container tools through `docker exec` instead of directly.

const vscode = require('vscode');
const { execFile } = require('child_process');
const sdk = require('./sdk');
const hostTerminal = require('./hostTerminal');

// The container last opened in VS Code; pages show it while it's running.
const LAST_CONTAINER_KEY = 'simaNeat.lastSdkContainer';
const CONTAINER_WORKSPACE = '/workspace';

let extensionContext;

function init(context) {
  extensionContext = context;
}

async function inspectContainer(name) {
  const result = await sdk.run('docker', ['inspect', '--type', 'container', name]);
  if (result.code !== 0) {
    return undefined;
  }
  try {
    return JSON.parse(result.stdout)[0];
  } catch {
    return undefined;
  }
}

/** The user sima-cli set for attaching, from the devcontainer.metadata label. */
function remoteUserOf(info) {
  try {
    const metadata = JSON.parse(info.Config.Labels['devcontainer.metadata']);
    const withUser = (Array.isArray(metadata) ? metadata : [metadata]).filter((entry) => entry && entry.remoteUser).pop();
    if (withUser) {
      return withUser.remoteUser;
    }
  } catch {
    // No label: fall back to the image's user.
  }
  return info.Config.User || 'root';
}

/** The folder on this computer mounted as /workspace. */
function hostWorkspaceOf(info) {
  const mount = (info.Mounts || []).find((m) => m.Destination === CONTAINER_WORKSPACE);
  return mount ? mount.Source : undefined;
}

/** The container this window is attached to, if any. */
function containerOfThisWindow() {
  const folder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  const match = folder && folder.uri.scheme === 'vscode-remote' && /^attached-container\+([0-9a-f]+)/.exec(folder.uri.authority);
  if (!match) {
    return undefined;
  }
  try {
    return JSON.parse(Buffer.from(match[1], 'hex').toString('utf8')).containerName.replace(/^\//, '');
  } catch {
    return undefined;
  }
}

/**
 * The SDK container the pages show: the one this window is attached to, else
 * the one last opened in VS Code, else the first running one. Undefined when
 * none is running.
 */
async function currentContainer() {
  const running = (await sdk.listAllSdkContainers()).filter((c) => c.state === 'running');
  const byName = (name) => running.find((c) => c.name === name);
  const container = byName(containerOfThisWindow())
    || byName(extensionContext.globalState.get(LAST_CONTAINER_KEY))
    || running[0];
  const info = container && await inspectContainer(container.name);
  if (!info) {
    return undefined;
  }
  return {
    name: container.name,
    image: container.image,
    user: remoteUserOf(info),
    workspace: hostWorkspaceOf(info),
  };
}

/** Runs a program in the container and resolves with its stdout. */
function execIn(target, file, args, { timeout = 8000, env = {}, cwd, maxBuffer = 4 * 1024 * 1024 } = {}) {
  const dockerArgs = ['exec', '-u', target.user];
  if (cwd) {
    dockerArgs.push('-w', cwd);
  }
  for (const [key, value] of Object.entries(env)) {
    dockerArgs.push('-e', `${key}=${value}`);
  }
  dockerArgs.push(target.name, file, ...args);
  return new Promise((resolve, reject) => {
    execFile('docker', dockerArgs, { timeout, maxBuffer, killSignal: 'SIGKILL' }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error((stderr || stdout || error.message).trim()));
        return;
      }
      resolve(stdout);
    });
  });
}

/** A readFile(path) that reads from the container, for the ported page code. */
function readerFor(target) {
  return (file) => execIn(target, 'cat', ['--', file]);
}

/**
 * An execute(file, args, options) that runs in the container, for the ported
 * page code. Only SSHPASS is passed through from options.env: everything else
 * there is this computer's environment, not the container's.
 */
function executorFor(target) {
  return (file, args, options = {}) => execIn(target, file, args, {
    timeout: options.timeout || 8000,
    env: options.env && options.env.SSHPASS ? { SSHPASS: options.env.SSHPASS } : {},
  });
}

/**
 * Opens a terminal that runs a bash command in the container. In a window
 * attached to that container, terminals already run there.
 */
function openContainerTerminal(target, name, command) {
  if (containerOfThisWindow() === target.name) {
    const terminal = vscode.window.createTerminal({ name });
    terminal.show();
    terminal.sendText(command);
    return;
  }
  const dockerArgs = ['exec', '-it', '-u', target.user, '-w', CONTAINER_WORKSPACE, target.name, 'bash', '-lc', command];
  // Docker is on this computer; in other remote windows a plain terminal would start on the remote side.
  const terminal = hostTerminal.isRemoteWindow()
    ? hostTerminal.createHostTerminal({ name, file: 'docker', args: dockerArgs })
    : vscode.window.createTerminal({ name, shellPath: 'docker', shellArgs: dockerArgs });
  terminal.show();
}

module.exports = {
  LAST_CONTAINER_KEY,
  CONTAINER_WORKSPACE,
  init,
  inspectContainer,
  remoteUserOf,
  hostWorkspaceOf,
  containerOfThisWindow,
  currentContainer,
  execIn,
  readerFor,
  executorFor,
  openContainerTerminal,
};
