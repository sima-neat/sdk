'use strict';

// Host-side versions of the helpers in the SDK extension's src/extension.js.
// They work on the current SDK container through ../container.js, or directly
// on this computer's copy of the workspace where that's simpler.

const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const container = require('../container');
const sdk = require('../sdk');
const { getInsightUrl, readNeatStatus, loadLandingData } = require('./landing-data');

const APPS_REPO_URL = 'https://github.com/sima-neat/apps';
const DEFAULT_DEVKIT_SYNC_USER = 'sima';
const DEFAULT_DEVKIT_SYNC_PASSWORD = 'edgeai';
const DEFAULT_DEVKIT_SYNC_PORT = '22';
const SDK_IMAGE_DEPS_MANIFEST = '/usr/local/share/sima-sdk/deps/manifest.json';

class NoContainerError extends Error {
  constructor() {
    super('No Neat SDK container is running. Start one from Neat Setup.');
    this.code = 'NO_CONTAINER';
  }
}

async function requireContainer() {
  const target = await container.currentContainer();
  if (!target) {
    throw new NoContainerError();
  }
  return target;
}

/** The SDK workspace on this computer: the running container's /workspace, else the setup setting. */
async function hostWorkspace(target) {
  const current = target || await container.currentContainer();
  if (current && current.workspace) {
    return current.workspace;
  }
  return sdk.expandHome(vscode.workspace.getConfiguration('simaNeat.sdk').get('workspace', '~/workspace'));
}

function displayPath(file) {
  const home = os.homedir();
  return file.startsWith(home + path.sep) ? `~${file.slice(home.length)}` : file;
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function runHost(file, args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(file, args, options, (error, stdout, stderr) => {
      if (error) {
        reject(new Error((stderr || stdout || error.message).trim()));
        return;
      }
      resolve(stdout);
    });
  });
}

async function exists(file) {
  try {
    await fs.promises.access(file);
    return true;
  } catch {
    return false;
  }
}

// ─────────────────────────── Insight ────────────────────────────

// Docker publishes Insight on this computer, and the SDK's certificate covers localhost.
function toLocalhost(url) {
  const target = new URL(url);
  target.hostname = 'localhost';
  return target.href;
}

function insightOptions(target) {
  return {
    reader: container.readerFor(target),
    execute: container.executorFor(target),
    resolveBrowserUrl: toLocalhost,
  };
}

/** Insight's address on this computer. `neat --json` output holds secrets: never log it. */
async function getInsightWebUiUrl() {
  const target = await requireContainer();
  return getInsightUrl(await readNeatStatus(container.executorFor(target)), insightOptions(target));
}

// ─────────────────────────── DevKit ─────────────────────────────

/** DevKit Sync settings from the container's environment and ~/.devkit-sync.rc. */
async function getDevKitSyncConfig(target) {
  const fallback = { host: '', user: DEFAULT_DEVKIT_SYNC_USER, port: DEFAULT_DEVKIT_SYNC_PORT };
  try {
    const script = [
      '[[ -f ~/.devkit-sync.rc ]] && source ~/.devkit-sync.rc',
      'printf \'%s\\n\' "${DEVKIT_SYNC_DEVKIT_IP:-}" "${DEVKIT_SYNC_DEVKIT_USER:-sima}" "${DEVKIT_SYNC_DEVKIT_PORT:-22}"',
    ].join('; ');
    const stdout = await container.execIn(target, 'bash', ['-lc', script], { timeout: 5000 });
    // The last three lines, in case a profile script printed something first.
    const [host = '', user = '', port = ''] = stdout.replace(/\n$/, '').split('\n').slice(-3);
    return {
      host: host.trim(),
      user: user.trim() || DEFAULT_DEVKIT_SYNC_USER,
      port: port.trim() || DEFAULT_DEVKIT_SYNC_PORT,
    };
  } catch {
    return fallback;
  }
}

async function succeedsIn(target, file, args, timeout, env) {
  try {
    await container.execIn(target, file, args, { timeout, env });
    return true;
  } catch {
    return false;
  }
}

const SSH_OPTIONS = ['-o', 'ConnectTimeout=3', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null'];

async function canSshHost(target, host, user, port) {
  const destination = `${user}@${host}`;
  if (await succeedsIn(target, 'ssh', ['-p', port, '-o', 'BatchMode=yes', ...SSH_OPTIONS, destination, 'true'], 5000)) {
    return true;
  }
  if (await succeedsIn(target, 'sshpass', ['-e', 'ssh', '-p', port, ...SSH_OPTIONS, destination, 'true'], 5000,
    { SSHPASS: DEFAULT_DEVKIT_SYNC_PASSWORD })) {
    return true;
  }
  if (await succeedsIn(target, 'nc', ['-z', '-w', '3', host, port], 5000)) {
    return true;
  }
  if (!/^[A-Za-z0-9_.:-]+$/.test(host) || !/^[0-9]+$/.test(port)) {
    return false;
  }
  return succeedsIn(target, 'bash', ['-lc', `timeout 3 bash -c 'cat < /dev/null > /dev/tcp/${host}/${port}'`], 5000);
}

async function getDevKitSyncState() {
  const target = await requireContainer();
  const config = await getDevKitSyncConfig(target);
  const { host, user, port } = config;
  if (!host) {
    return {
      host: '', user: '', port: '', online: false,
      buttonLabel: 'DevKit Sync',
      status: 'DevKit Sync is not enabled, use',
      detail: 'sima-cli sdk setup --devkit {ip}',
      detailKind: 'command',
      disabled: true,
    };
  }
  const pingArgs = ['-c', '1', '-W', '1', host];
  if (!await succeedsIn(target, 'ping', pingArgs, 2500) || !await canSshHost(target, host, user, port)) {
    return {
      host, user, port, online: false,
      buttonLabel: 'DevKit Sync',
      status: `DevKit ${host} is unreachable`,
      detail: '',
      disabled: true,
    };
  }
  return {
    host, user, port, online: true,
    buttonLabel: 'SSH to DevKit',
    status: 'DevKit online, click to SSH to the DevKit',
    detail: '',
    disabled: false,
  };
}

async function openDevKitSsh(host, user, port) {
  const target = await requireContainer();
  const config = await getDevKitSyncConfig(target);
  const targetHost = String(host || config.host || '').trim();
  const targetUser = String(user || config.user || DEFAULT_DEVKIT_SYNC_USER).trim();
  const targetPort = String(port || config.port || DEFAULT_DEVKIT_SYNC_PORT).trim();
  if (!targetHost) {
    vscode.window.showErrorMessage('DevKit Sync is not enabled');
    return;
  }
  container.openContainerTerminal(target, `DevKit ${targetHost}`,
    `ssh -p ${shellQuote(targetPort)} ${shellQuote(`${targetUser}@${targetHost}`)}`);
  vscode.window.showInformationMessage(`Use password '${DEFAULT_DEVKIT_SYNC_PASSWORD}' if prompted.`);
}

/** `dk shell` in the container: the SDK's own DevKit shell. */
async function openDevKitShell() {
  const target = await requireContainer();
  container.openContainerTerminal(target, 'DevKit', 'dk shell');
}

// ─────────────────────────── Samples ────────────────────────────

async function getSamplesState() {
  const root = await hostWorkspace();
  const apps = path.join(root, 'apps');
  if (await exists(path.join(apps, '.git'))) {
    return {
      disabled: true,
      buttonLabel: 'Samples Cloned',
      status: 'Samples are available under',
      detail: displayPath(apps),
      detailKind: 'path-folder',
    };
  }
  if (await exists(apps)) {
    return {
      disabled: true,
      buttonLabel: 'Clone Samples',
      status: 'An apps directory already exists, but it is not a Git checkout.',
      detail: displayPath(apps),
    };
  }
  return {
    disabled: false,
    buttonLabel: 'Clone Samples',
    status: 'Clone SiMa Neat samples into the SDK workspace.',
    detail: displayPath(apps),
  };
}

async function cloneSamples() {
  const state = await getSamplesState();
  if (state.disabled) {
    vscode.window.showInformationMessage(state.status);
    return;
  }
  const root = await hostWorkspace();
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'Cloning SiMa Neat samples', cancellable: false },
    async (progress) => {
      progress.report({ message: 'Starting git clone…' });
      await fs.promises.mkdir(root, { recursive: true });
      await runHost('git', ['clone', APPS_REPO_URL, 'apps'], { cwd: root });
    },
  );
  vscode.window.showInformationMessage(`SiMa Neat samples cloned into ${displayPath(path.join(root, 'apps'))}.`);
}

// ─────────────────────────── Tutorials ──────────────────────────

async function findTutorials(root) {
  const candidates = [
    ['tutorials'],
    ['tutorial'],
    ['extras', 'tutorials'],
    ['neat-extras', 'tutorials'],
    ['sima-neat-extras', 'tutorials'],
    ['extras', 'share', 'sima-neat', 'tutorials'],
    ['extras', 'lib', 'sima-neat', 'tutorials'],
  ];
  for (const parts of candidates) {
    if (await exists(path.join(root, ...parts))) {
      return path.join(root, ...parts);
    }
  }
  try {
    for (const entry of await fs.promises.readdir(root, { withFileTypes: true })) {
      if (!entry.isDirectory() || !entry.name.toLowerCase().includes('extras')) {
        continue;
      }
      for (const parts of [['share', 'sima-neat', 'tutorials'], ['lib', 'sima-neat', 'tutorials'], ['tutorials']]) {
        const candidate = path.join(root, entry.name, ...parts);
        if (await exists(candidate)) {
          return candidate;
        }
      }
    }
  } catch {
    // No workspace folder yet.
  }
  return undefined;
}

async function getTutorialsState() {
  const tutorials = await findTutorials(await hostWorkspace());
  if (tutorials) {
    return {
      disabled: true,
      buttonLabel: 'Tutorials Installed',
      status: 'Tutorials are available under',
      detail: displayPath(tutorials),
      detailKind: 'path-folder',
    };
  }
  return {
    disabled: !await container.currentContainer(),
    buttonLabel: 'Install Tutorials',
    status: 'Download Neat tutorials into the SDK workspace.',
    detail: '',
  };
}

function validateDependencyRef(raw, key) {
  const ref = raw.trim();
  if (!ref) {
    throw new Error(`dependency ${key} has an empty ref`);
  }
  if (ref.includes('@') || /\s/.test(ref)) {
    throw new Error(`dependency ${key} ref must not contain '@' or whitespace: ${ref}`);
  }
  if (!ref.includes(':')) {
    if (!/^[A-Za-z0-9._/-]+$/.test(ref)) {
      throw new Error(`dependency ${key} ref must be a git tag/ref like v0.1.0: ${ref}`);
    }
    return ref;
  }
  const parts = ref.split(':');
  if (parts.length !== 2) {
    throw new Error(`dependency ${key} ref must be tag, branch:latest, or branch:githash: ${ref}`);
  }
  const [branch, spec] = parts.map((part) => part.trim());
  if (!branch || !spec) {
    throw new Error(`dependency ${key} ref must include both branch and spec: ${ref}`);
  }
  if (!/^[A-Za-z0-9._/-]+$/.test(branch)) {
    throw new Error(`dependency ${key} branch contains unsupported characters: ${branch}`);
  }
  if (spec !== 'latest' && !/^[A-Fa-f0-9]+$/.test(spec)) {
    throw new Error(`dependency ${key} spec must be 'latest' or a git hash: ${spec}`);
  }
  return `${branch}:${spec}`;
}

/** The Neat core version the SDK image was built with, from its dependency manifest. */
async function resolveCoreTutorialsTarget(target) {
  let text;
  try {
    text = await container.readerFor(target)(SDK_IMAGE_DEPS_MANIFEST);
  } catch {
    try {
      text = await fs.promises.readFile(path.join(await hostWorkspace(target), 'deps', 'manifest.json'), 'utf8');
    } catch {
      return 'core';
    }
  }
  const data = JSON.parse(text);
  const value = data.core;
  const ref = typeof value === 'string' ? value : value && value.ref;
  return ref ? `core@${validateDependencyRef(String(ref), 'core')}` : 'core';
}

async function installTutorials() {
  const state = await getTutorialsState();
  if (state.disabled) {
    vscode.window.showInformationMessage(state.buttonLabel === 'Install Tutorials' ? 'Start the Neat SDK container first.' : state.status);
    return;
  }
  const target = await requireContainer();
  const coreTarget = await resolveCoreTutorialsTarget(target);
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'Installing Neat tutorials', cancellable: false },
    async (progress) => {
      progress.report({ message: `Downloading ${coreTarget} extras package…` });
      // The container's sima-cli matches the SDK image; it installs into /workspace.
      await container.execIn(target, 'bash', ['-lc', 'exec sima-cli neat install "$1" -t extras', 'sima-cli', coreTarget], {
        cwd: container.CONTAINER_WORKSPACE,
        env: { SIMA_CLI_CHECK_FOR_UPDATE: '0' },
        timeout: 30 * 60 * 1000,
      });
    },
  );
  const tutorials = await findTutorials(await hostWorkspace(target));
  vscode.window.showInformationMessage(tutorials
    ? `Neat tutorials installed under ${displayPath(tutorials)}.`
    : 'Neat tutorials package installed.');
}

// ─────────────────────────── Getting Started data ───────────────

async function loadGettingStartedData() {
  const target = await requireContainer();
  const data = await loadLandingData(() => getDevKitSyncConfig(target), insightOptions(target));
  return { ...data, containerName: target.name };
}

module.exports = {
  NoContainerError,
  requireContainer,
  hostWorkspace,
  displayPath,
  getInsightWebUiUrl,
  getDevKitSyncConfig,
  getDevKitSyncState,
  openDevKitSsh,
  openDevKitShell,
  getSamplesState,
  cloneSamples,
  getTutorialsState,
  installTutorials,
  loadGettingStartedData,
  validateDependencyRef,
};
