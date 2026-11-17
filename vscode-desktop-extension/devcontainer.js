'use strict';

// Opens a Neat SDK container in this desktop VS Code through Dev Containers'
// "Attach to Running Container". sima-cli creates the container; Dev Containers
// must never create it, or the SDK's network and DevKit setup is skipped. This
// file starts a stopped container the way sima-cli does (`docker start`),
// prepares it for VS Code, and switches the window into it.

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const sdk = require('./sdk');
const { LAST_CONTAINER_KEY, inspectContainer, remoteUserOf } = require('./container');
const { createProgressStatus } = require('./progressStatus');

const DEV_CONTAINERS_ID = 'ms-vscode-remote.remote-containers';
const WORKSPACE_FOLDER = '/workspace';
// Ships in the SDK image; copies the SDK's own Neat extension into a VS Code profile.
const NEAT_EXTENSION_INSTALLER = 'sima-install-neat-extension';
const NEAT_EXTENSION_ID = 'sima-neat.sima-neat';

let extensionContext;
let api;
// Shows each step on the right of the status bar while the SDK opens.
let status;

function sdkSettings() {
  return vscode.workspace.getConfiguration('simaNeat.sdk');
}

/** The remote authority Dev Containers builds for an attached container. */
function attachAuthority(containerName) {
  const config = JSON.stringify({ containerName: `/${containerName}` });
  return `attached-container+${Buffer.from(config, 'utf8').toString('hex')}`;
}

function attachUri(containerName) {
  return vscode.Uri.from({ scheme: 'vscode-remote', authority: attachAuthority(containerName), path: WORKSPACE_FOLDER });
}

/**
 * Dev Containers keeps per-container settings beside other extensions' storage,
 * in ms-vscode-remote.remote-containers/nameConfigs/<name>.json with ":", "/"
 * and "%" escaped. They take precedence over its per-image settings.
 */
function nameConfigFile(globalStorageDir, containerName) {
  const escaped = containerName.replace(/[:/%]/g, (c) => `%${c.charCodeAt(0).toString(16)}`);
  return path.join(path.dirname(globalStorageDir), DEV_CONTAINERS_ID, 'nameConfigs', `${escaped}.json`);
}

/**
 * Adds what the SDK window needs to a Dev Containers config, keeping anything
 * else already set. Extensions in `removed` are taken out of the list: Dev
 * Containers records every extension installed while attached, so the SDK's
 * Neat extension stays there after it has been installed once.
 */
function mergeNamedConfig(existing, { extensions, publishedPorts, removed = [] }) {
  const config = { ...existing };
  if (!config.workspaceFolder) {
    config.workspaceFolder = WORKSPACE_FOLDER;
  }
  const drop = new Set(removed.map((id) => id.toLowerCase()));
  const current = (Array.isArray(config.extensions) ? config.extensions : []).filter((id) => !drop.has(id.toLowerCase()));
  const known = new Set(current.map((id) => id.toLowerCase()));
  config.extensions = [...current, ...extensions.filter((id) => !known.has(id.toLowerCase()))];
  // Docker already publishes these ports on this computer, so forwarding them again only adds duplicates.
  const ports = { ...config.portsAttributes };
  for (const port of publishedPorts) {
    if (!ports[port]) {
      ports[port] = { label: 'Published by the SDK container', onAutoForward: 'ignore' };
    }
  }
  if (Object.keys(ports).length) {
    config.portsAttributes = ports;
  }
  return config;
}

function publishedPortsOf(info) {
  const bindings = (info.HostConfig && info.HostConfig.PortBindings) || {};
  return Object.keys(bindings).filter((key) => bindings[key] && bindings[key].length).map((key) => key.split('/')[0]);
}

async function startContainer(name) {
  const result = await sdk.run('docker', ['start', name], 120000);
  if (result.code === 0) {
    return;
  }
  const output = `${result.stderr}\n${result.stdout}`;
  if (/port is already allocated|address already in use/i.test(output)) {
    throw new Error(`A port the container ${name} needs is in use. Run setup again to recreate the container.`);
  }
  const reason = output.trim().split('\n').filter(Boolean).pop() || `docker start exited with ${result.code}`;
  throw new Error(`Couldn't start the container ${name}: ${reason}`);
}

function writeNamedConfig(name, info, removed) {
  const file = nameConfigFile(extensionContext.globalStorageUri.fsPath, name);
  let existing = {};
  if (fs.existsSync(file)) {
    try {
      existing = JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch {
      return; // Edited by hand (for example with comments): leave it alone.
    }
  }
  const config = mergeNamedConfig(existing, {
    extensions: sdkSettings().get('containerExtensions', ['anthropic.claude-code']),
    publishedPorts: publishedPortsOf(info),
    removed,
  });
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(config, null, '\t')}\n`);
}

/**
 * Installs the SDK's Neat extension into the VS Code Server profile before
 * attaching. It isn't on the Marketplace, and the browser IDE's copy lives in
 * a different folder. The profile is inside the container, so recreating the
 * container removes it; that's why this runs on every open.
 */
async function installNeatExtension(name, user) {
  const serverDir = vscode.env.appName.includes('Insiders') ? '.vscode-server-insiders' : '.vscode-server';
  const script = `command -v ${NEAT_EXTENSION_INSTALLER} >/dev/null 2>&1 || exit 3; `
    + `exec ${NEAT_EXTENSION_INSTALLER} "$HOME/${serverDir}/extensions"`;
  const result = await sdk.run('docker', ['exec', '-u', user, name, 'sh', '-c', script], 60000);
  return result.code === 0 ? 'installed' : result.code === 3 ? 'unavailable' : 'failed';
}

/**
 * Uninstalls the SDK's Neat extension from the container's VS Code Server, if
 * an earlier version of this extension or a manual install put it there: its
 * pages and its Palette view would show next to this extension's.
 */
async function removeNeatExtension(name, user) {
  const serverDir = vscode.env.appName.includes('Insiders') ? '.vscode-server-insiders' : '.vscode-server';
  const script = `for server in "$HOME/${serverDir}"/bin/*/bin/code-server "$HOME/${serverDir}"/cli/servers/*/server/bin/code-server; do `
    + '[ -x "$server" ] || continue; '
    + `"$server" --list-extensions 2>/dev/null | grep -qix ${NEAT_EXTENSION_ID} || exit 0; `
    + `exec "$server" --uninstall-extension ${NEAT_EXTENSION_ID}; done`;
  await sdk.run('docker', ['exec', '-u', user, name, 'sh', '-c', script], 60000);
}

async function prepareContainer(name, progress) {
  const info = await inspectContainer(name);
  if (!info) {
    throw new Error(`The container ${name} no longer exists. Run setup to create it.`);
  }
  if (!info.State.Running) {
    progress.report({ message: 'starting the container…' });
    await startContainer(name);
  }
  progress.report({ message: 'preparing VS Code for the container…' });
  // This extension shows the same pages from the host, so the SDK's copy is opt-in to avoid duplicates.
  const withSdkExtension = sdkSettings().get('installSdkExtension', false);
  // Dev Containers keeps every extension it ever installed in this list; take out the ones not wanted now.
  const wanted = sdkSettings().get('containerExtensions', ['anthropic.claude-code']).map((id) => id.toLowerCase());
  const removed = [withSdkExtension ? undefined : NEAT_EXTENSION_ID, wanted.includes('anthropic.claude-code') ? undefined : 'anthropic.claude-code']
    .filter(Boolean);
  writeNamedConfig(name, info, removed);
  if (!withSdkExtension) {
    await removeNeatExtension(name, remoteUserOf(info));
  } else if (await installNeatExtension(name, remoteUserOf(info)) === 'failed') {
    vscode.window.showWarningMessage("Couldn't install the SDK's Neat extension for VS Code. The SDK window opens without it.");
  }
}

/**
 * Installs Dev Containers when it's missing. It normally arrives with this
 * extension (extensionPack); this covers it being uninstalled since.
 * Returns whether it's available.
 */
async function ensureDevContainers() {
  if (vscode.extensions.getExtension(DEV_CONTAINERS_ID)) {
    return true;
  }
  status.step('Neat SDK: installing Dev Containers…');
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Installing Microsoft's Dev Containers extension…" },
      () => vscode.commands.executeCommand('workbench.extensions.installExtension', DEV_CONTAINERS_ID),
    );
    return true;
  } catch (err) {
    vscode.window.showErrorMessage(
      `Couldn't install Dev Containers: ${err.message}. It's available only in Microsoft's VS Code builds; `
        + 'you can use the SDK\'s browser IDE instead.',
    );
    return false;
  }
}

function isThisWindow(containerName) {
  const folder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  return Boolean(folder && folder.uri.scheme === 'vscode-remote' && folder.uri.authority.startsWith(attachAuthority(containerName)));
}

async function pickContainer(containers, preferredName, interactive) {
  const byName = (name) => containers.find((c) => c.name === name);
  if (preferredName && byName(preferredName)) {
    return byName(preferredName);
  }
  if (containers.length === 1) {
    return containers[0];
  }
  const last = byName(extensionContext.globalState.get(LAST_CONTAINER_KEY));
  if (!interactive) {
    return last;
  }
  const ordered = last ? [last, ...containers.filter((c) => c !== last)] : containers;
  const picked = await vscode.window.showQuickPick(
    ordered.map((c) => ({
      label: c.name,
      description: c.image,
      detail: c.state === 'running' ? `$(play) Running · ${c.status}` : `$(debug-stop) Stopped · ${c.status}`,
      container: c,
    })),
    { placeHolder: 'Which Neat SDK container should VS Code open?' },
  );
  return picked && picked.container;
}

/**
 * Switches VS Code into a Neat SDK container, at /workspace. Reuses this window
 * when it's empty, otherwise opens a new one. Returns whether it opened.
 */
async function openSdkInVsCode({ containerName, interactive = true } = {}) {
  const containers = await sdk.listAllSdkContainers();
  if (!containers.length) {
    const choice = await vscode.window.showWarningMessage('There is no Neat SDK container on this computer yet.', 'Open Neat Setup');
    if (choice) {
      api.showSetup();
    }
    return false;
  }
  const container = await pickContainer(containers, containerName, interactive);
  if (!container) {
    return false;
  }
  if (isThisWindow(container.name)) {
    vscode.window.showInformationMessage(`This window is already open in the Neat SDK container ${container.name}.`);
    return true;
  }
  if (!await ensureDevContainers()) {
    status.finish('Neat SDK: Dev Containers is needed', { failed: true });
    return false;
  }
  status.step('Neat SDK: checking the container…', `Opening ${container.name} in VS Code`);
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `Opening the Neat SDK (${container.name})` },
      (progress) => prepareContainer(container.name, {
        report(value) {
          progress.report(value);
          status.step(`Neat SDK: ${value.message}`, `Opening ${container.name} in VS Code`);
        },
      }),
    );
  } catch (err) {
    status.finish("Neat SDK: couldn't open", { failed: true, tooltip: err.message });
    const choice = await vscode.window.showErrorMessage(err.message, 'Open Neat Setup');
    if (choice) {
      api.showSetup();
    }
    return false;
  }
  await extensionContext.globalState.update(LAST_CONTAINER_KEY, container.name);
  const forceNewWindow = Boolean(vscode.env.remoteName || vscode.workspace.workspaceFolders || vscode.workspace.workspaceFile);
  // When this window is reused it reloads into the container, and the SDK window shows the next steps.
  status.step('Neat SDK: connecting VS Code to the container…', `Opening ${container.name} in VS Code`);
  try {
    await vscode.commands.executeCommand('vscode.openFolder', attachUri(container.name), { forceNewWindow });
  } catch {
    // The attach address isn't a documented API; fall back to Dev Containers' own picker.
    await vscode.commands.executeCommand('remote-containers.attachToRunningContainer');
  }
  if (forceNewWindow) {
    status.finish('Neat SDK: opened in a new window');
  }
  return true;
}

/** When VS Code starts with an empty local window and an SDK container exists, offers to open it. */
async function openOnStartup() {
  const settings = sdkSettings();
  const mode = settings.get('openOnStartup', 'ask');
  if (mode === 'never' || vscode.env.remoteName || vscode.workspace.workspaceFolders || vscode.workspace.workspaceFile) {
    return;
  }
  const containers = await sdk.listAllSdkContainers();
  if (!containers.length) {
    return;
  }
  const remembered = containers.find((c) => c.name === extensionContext.globalState.get(LAST_CONTAINER_KEY));
  const container = remembered || (containers.length === 1 ? containers[0] : undefined);
  if (mode === 'ask') {
    const choice = await vscode.window.showInformationMessage(
      `Open the Neat SDK${container ? ` (${container.name})` : ''} in this window?`,
      'Open',
      'Always',
      'Never',
    );
    if (choice === 'Always' || choice === 'Never') {
      await settings.update('openOnStartup', choice.toLowerCase(), vscode.ConfigurationTarget.Global);
    }
    if (!choice || choice === 'Never') {
      return;
    }
  }
  await openSdkInVsCode({ containerName: container && container.name });
}

function isDevContainersInstalled() {
  return Boolean(vscode.extensions.getExtension(DEV_CONTAINERS_ID));
}

function init(context, extensionApi) {
  extensionContext = context;
  api = extensionApi;
  status = createProgressStatus('simaNeat.openProgress', 'Neat SDK: opening in VS Code');
  context.subscriptions.push(status);
}

module.exports = {
  init,
  openSdkInVsCode,
  openOnStartup,
  isDevContainersInstalled,
  // Exported for tests.
  attachAuthority,
  nameConfigFile,
  mergeNamedConfig,
  publishedPortsOf,
};
