'use strict';

// Host-side Neat SDK helpers: version lookup, prerequisite checks, image pull
// with retries, and the `sima-cli sdk setup` command. No vscode dependency.

const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile, spawn } = require('child_process');

const ARTIFACTS_URL = 'https://artifacts.neat.sima.ai/sdk';
const RELEASES_API_URL = 'https://api.github.com/repos/sima-neat/sdk/releases?per_page=10';
const IS_WINDOWS = process.platform === 'win32';
const DEFAULT_REQUIRED_GB = 20;
const RETRY_DELAYS_SECONDS = [5, 15, 45, 90, 180];
const MAX_LOG_LINES = 500;

// ───────────────────────────── HTTP ─────────────────────────────

function httpGet(url, redirects = 3) {
  return new Promise((resolve, reject) => {
    const request = https.get(url, { headers: { 'User-Agent': 'sima-neat-desktop' }, timeout: 15000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location && redirects > 0) {
        res.resume();
        resolve(httpGet(new URL(res.headers.location, url).toString(), redirects - 1));
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`${url} returned HTTP ${res.statusCode}`));
        return;
      }
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => resolve(body));
    });
    request.on('timeout', () => request.destroy(new Error(`${url} timed out`)));
    request.on('error', reject);
  });
}

async function getJson(url) {
  return JSON.parse(await httpGet(url));
}

// ─────────────────────────── Versions ───────────────────────────

function branchLabel(name) {
  if (name === 'main') {
    return 'main — latest build of the stable branch';
  }
  if (name === 'develop') {
    return 'develop — pre-release, latest development build';
  }
  return `${name} — release branch`;
}

/** Lists installable SDK refs: GitHub releases, then main, develop and release branches. */
async function listSdkVersions() {
  const [releases, branches] = await Promise.allSettled([
    getJson(RELEASES_API_URL),
    getJson(`${ARTIFACTS_URL}/branches.json`),
  ]);
  const items = [];

  if (releases.status === 'fulfilled' && Array.isArray(releases.value)) {
    let latestMarked = false;
    for (const release of releases.value.filter((r) => !r.draft).slice(0, 5)) {
      const latest = !latestMarked && !release.prerelease;
      latestMarked = latestMarked || latest;
      const note = latest ? ' — latest release' : release.prerelease ? ' — pre-release' : ' — release';
      items.push({ ref: release.tag_name, label: `${release.tag_name}${note}`, recommended: latest });
    }
  }

  const branchNames = branches.status === 'fulfilled' && Array.isArray(branches.value.branches)
    ? branches.value.branches.map((b) => b.name)
    : ['main', 'develop'];
  const releaseBranches = branchNames.filter((n) => /^release-[\d.]+$/.test(n)).sort().reverse();
  for (const name of ['main', 'develop', ...releaseBranches]) {
    if (branchNames.includes(name)) {
      items.push({ ref: name, label: branchLabel(name), recommended: false });
    }
  }

  const failures = [releases, branches].filter((r) => r.status === 'rejected').map((r) => r.reason.message);
  return { items, warning: failures.length ? `Some versions could not be listed: ${failures.join('; ')}` : undefined };
}

function parseSizeGb(value) {
  const match = /([\d.]+)\s*GB/i.exec(value || '');
  return match ? Number(match[1]) : 0;
}

/** Resolves an SDK ref to its container image, the same way `sima-cli neat install sdk@<ref>` does. */
async function resolveSdkRef(ref) {
  const key = encodeURIComponent(ref);
  const tag = (await httpGet(`${ARTIFACTS_URL}/${key}/latest.tag`)).trim();
  const metadata = await getJson(`${ARTIFACTS_URL}/${key}/${tag}/metadata.json`);
  const resource = (metadata.resources || []).find((r) => typeof r === 'string' && r.startsWith('ghcr:'));
  if (!resource) {
    throw new Error(`The ${ref} SDK package does not list a container image.`);
  }
  const size = metadata.size || {};
  return {
    ref,
    tag,
    version: metadata.version,
    resource,
    image: `ghcr.io/${resource.slice('ghcr:'.length)}`,
    requiredGb: (parseSizeGb(size.download) + parseSizeGb(size.install)) || DEFAULT_REQUIRED_GB,
  };
}

// ──────────────────────── Prerequisites ─────────────────────────

function run(command, args, timeout = 30000, env = undefined) {
  return new Promise((resolve) => {
    execFile(command, args, { timeout, env }, (err, stdout, stderr) => {
      const code = err ? (typeof err.code === 'number' ? err.code : -1) : 0;
      resolve({ code, stdout: stdout || '', stderr: stderr || (err && code === -1 ? err.message : '') });
    });
  });
}

function findOnPath(name, extraDirs = []) {
  const dirs = [...(process.env.PATH || '').split(path.delimiter), ...extraDirs].filter(Boolean);
  return dirs.map((dir) => path.join(dir, name)).find((file) => {
    try {
      return fs.statSync(file).isFile();
    } catch {
      return false;
    }
  });
}

function hostOsItem() {
  if (process.platform === 'darwin') {
    return { id: 'os', label: 'Host OS', status: 'ok', detail: `macOS ${os.release()}` };
  }
  if (IS_WINDOWS) {
    return { id: 'os', label: 'Host OS', status: 'ok', detail: `Windows ${os.release()}` };
  }
  let fields = {};
  try {
    fields = Object.fromEntries(fs.readFileSync('/etc/os-release', 'utf8').split('\n')
      .map((line) => line.split('='))
      .filter((parts) => parts.length === 2)
      .map(([k, v]) => [k, v.replace(/^"|"$/g, '')]));
  } catch {
    // Fall through with an unknown distribution.
  }
  const supported = fields.ID === 'ubuntu' && ['22.04', '24.04'].includes(fields.VERSION_ID);
  return {
    id: 'os',
    label: 'Host OS',
    status: supported ? 'ok' : 'warn',
    detail: fields.PRETTY_NAME || 'Linux',
    hint: supported ? undefined : 'The SDK is tested on Ubuntu 22.04 and 24.04. Other hosts may work.',
  };
}

function dockerDaemonItem(output) {
  const text = output.toLowerCase();
  if (text.includes('permission denied')) {
    return {
      id: 'daemon',
      label: 'Docker daemon',
      status: 'error',
      detail: "Your user isn't allowed to use Docker.",
      hint: 'Run `sudo usermod -aG docker $USER`, then log out and back in.',
    };
  }
  return {
    id: 'daemon',
    label: 'Docker daemon',
    status: 'error',
    detail: 'Docker is installed but not running.',
    hint: process.platform === 'linux' ? 'Start it with `sudo systemctl start docker`.' : 'Start Docker Desktop.',
  };
}

async function diskItem(dockerRootDir, requiredGb) {
  if (process.platform !== 'linux') {
    return { id: 'disk', label: 'Disk space', status: 'ok', detail: 'Managed by Docker Desktop; check its disk limit if the download fails.' };
  }
  if (typeof fs.promises.statfs !== 'function') {
    return { id: 'disk', label: 'Disk space', status: 'warn', detail: "Couldn't check free space." };
  }
  // Docker's data folder is usually root-only, so fall back to its parents.
  for (let dir = dockerRootDir || '/'; ; dir = path.dirname(dir)) {
    try {
      const stats = await fs.promises.statfs(dir);
      const freeGb = Math.round((stats.bavail * stats.bsize) / 1e9);
      const status = freeGb >= requiredGb ? 'ok' : freeGb >= 10 ? 'warn' : 'error';
      return {
        id: 'disk',
        label: 'Disk space',
        status,
        detail: `${freeGb} GB free for Docker (${dir}); about ${requiredGb} GB recommended.`,
        hint: status === 'ok' ? undefined : 'Free up space, for example with `docker system prune` to remove unused images and containers.',
      };
    } catch {
      if (dir === path.dirname(dir)) {
        return { id: 'disk', label: 'Disk space', status: 'warn', detail: "Couldn't check free space." };
      }
    }
  }
}

function ethtoolItem() {
  const found = findOnPath('ethtool', ['/usr/sbin', '/sbin']);
  return found
    ? { id: 'ethtool', label: 'ethtool', status: 'ok', detail: found }
    : {
      id: 'ethtool',
      label: 'ethtool',
      status: 'warn',
      detail: 'Not installed. sima-cli needs it to discover DevKits on your network.',
      hint: 'Install it with `sudo apt install ethtool`.',
    };
}

/** Host checks before downloading and starting the SDK. dockerReady gates the download. */
async function checkPrerequisites(requiredGb = DEFAULT_REQUIRED_GB) {
  const items = [hostOsItem()];
  let dockerReady = false;

  const version = await run('docker', ['--version']);
  if (version.code !== 0) {
    items.push({
      id: 'docker',
      label: 'Docker',
      status: 'error',
      detail: 'Docker is not installed, or not on PATH.',
      hint: 'Install Docker Engine: https://docs.docker.com/engine/install/',
    });
  } else {
    items.push({ id: 'docker', label: 'Docker', status: 'ok', detail: version.stdout.trim() });
    const info = await run('docker', ['info', '--format', '{{.ServerVersion}}|{{.DockerRootDir}}']);
    if (info.code !== 0) {
      items.push(dockerDaemonItem(info.stderr + info.stdout));
    } else {
      const [serverVersion, rootDir] = info.stdout.trim().split('|');
      dockerReady = true;
      items.push({ id: 'daemon', label: 'Docker daemon', status: 'ok', detail: `Running (server ${serverVersion}).` });
      items.push(await diskItem(rootDir, requiredGb));
    }
  }
  if (process.platform === 'linux') {
    items.push(ethtoolItem());
  }

  const status = items.some((i) => i.status === 'error') ? 'error' : items.some((i) => i.status === 'warn') ? 'warn' : 'ok';
  return { status, dockerReady, items };
}

// ──────────────────────── Image and container ───────────────────

/** The container name sima-cli uses for an image, e.g. ghcr.io-sima-neat-sdk-develop-latest. */
function containerNameFor(image) {
  return image.replace(/[/:@]/g, '-');
}

async function inspectImage(image) {
  const result = await run('docker', ['image', 'inspect', '--format', '{{.Id}}|{{.Created}}|{{.Size}}', image]);
  if (result.code !== 0) {
    return { present: false };
  }
  const [id, created, size] = result.stdout.trim().split('|');
  return { present: true, id: id.replace('sha256:', '').slice(0, 12), created, sizeGb: Math.round(Number(size) / 1e8) / 10 };
}

/** SDK containers for this image, matched by sima-cli's naming or by image. */
async function listSdkContainers(image) {
  const result = await run('docker', ['ps', '-a', '--format', '{{.Names}}|{{.Image}}|{{.State}}|{{.Status}}']);
  if (result.code !== 0) {
    return [];
  }
  const name = containerNameFor(image);
  return result.stdout.trim().split('\n').filter(Boolean)
    .map((line) => {
      const [containerName, containerImage, state, status] = line.split('|');
      return { name: containerName, image: containerImage, state, status };
    })
    .filter((c) => c.name === name || c.image === image);
}

/** Every Neat SDK container on this computer, running ones first. */
async function listAllSdkContainers() {
  const result = await run('docker', ['ps', '-a', '--format', '{{.Names}}|{{.Image}}|{{.State}}|{{.Status}}']);
  if (result.code !== 0) {
    return [];
  }
  return result.stdout.trim().split('\n').filter(Boolean)
    .map((line) => {
      const [name, image, state, status] = line.split('|');
      return { name, image, state, status };
    })
    .filter((c) => /(^|\/)sima-neat\/sdk[\w.-]*(:|@|$)/.test(c.image))
    .sort((a, b) => Number(b.state === 'running') - Number(a.state === 'running'));
}

/** The SDK browser IDE address that `sima-cli sdk setup` saved, or undefined. Holds a secret: never log it. */
function readCodeUi(containerName) {
  try {
    const file = path.join(os.homedir(), '.sima-cli', 'sdk-code-ui-tokens.json');
    const entry = JSON.parse(fs.readFileSync(file, 'utf8')).containers[containerName].codeUI;
    return entry && entry.url ? { url: entry.url, password: entry.password } : undefined;
  } catch {
    return undefined;
  }
}

// ──────────────────────────── Pull ──────────────────────────────

function lastMeaningfulLine(output) {
  const lines = output.split(/\r?\n|\r/).map((l) => l.trim()).filter(Boolean);
  return lines.length ? lines[lines.length - 1] : '';
}

function classifyPullError(output, spawnError) {
  const text = output.toLowerCase();
  if (spawnError) {
    return { kind: 'cli', retryable: false, message: `Couldn't start sima-cli: ${spawnError.message}`, hint: 'Reinstall sima-cli in step 1.' };
  }
  if (/github authorization|gh auth|github_token/.test(text)) {
    return {
      kind: 'auth', retryable: false, needsTerminal: true,
      message: 'This image needs GitHub authorization.',
      hint: 'Run the download in a terminal so you can sign in to GitHub.',
    };
  }
  if (text.includes('aborted!')) {
    return {
      kind: 'prompt', retryable: false, needsTerminal: true,
      message: 'sima-cli stopped to ask a question.',
      hint: 'Run the download in a terminal to answer it.',
    };
  }
  if (text.includes('no space left on device')) {
    return {
      kind: 'disk', retryable: false,
      message: 'The disk is full.',
      hint: 'Free up space, for example with `docker system prune`, then retry. Layers already downloaded are kept.',
    };
  }
  if (text.includes('permission denied') && text.includes('docker')) {
    return { kind: 'docker', retryable: false, message: "Your user isn't allowed to use Docker.", hint: 'See the Prerequisites step.' };
  }
  if (/cannot connect to the docker daemon|docker not available|unable to start docker/.test(text)) {
    return { kind: 'docker', retryable: false, message: 'Docker is not running.', hint: 'See the Prerequisites step.' };
  }
  if (/manifest unknown|not found: manifest|repository does not exist|name unknown/.test(text)) {
    return { kind: 'notfound', retryable: false, message: 'This image version does not exist in the registry.', hint: 'Choose another version.' };
  }
  if (/toomanyrequests|rate limit/.test(text)) {
    return { kind: 'ratelimit', retryable: true, slow: true, message: 'The registry is rate-limiting downloads.', hint: 'Retrying with longer waits.' };
  }
  return {
    kind: 'network', retryable: true,
    message: lastMeaningfulLine(output) || 'The download failed.',
    hint: 'Usually a network problem. Retrying resumes from the layers already downloaded.',
  };
}

/**
 * Pulls an SDK image with `sima-cli install ghcr:…`, retrying transient
 * failures with backoff. Success means the image exists locally afterwards,
 * because sima-cli can exit 0 without pulling (e.g. when Docker is down).
 * onUpdate receives a plain snapshot on every change.
 */
function createPull({ simaCliFile, env, resource, image, maxRetries, onUpdate }) {
  const layers = new Map();
  const log = [];
  let state = 'running';
  let attempt = 0;
  let statusLine = '';
  let error;
  let retryAt;
  let child;
  let timer;
  let cancelled = false;
  let output = '';
  let partial = '';

  const snapshot = () => {
    const done = [...layers.values()].filter((s) => /^(pull complete|already exists)$/i.test(s)).length;
    return {
      state, attempt, maxAttempts: maxRetries + 1, statusLine, error, retryAt,
      progress: { done, total: layers.size },
      log: log.slice(-200),
    };
  };
  const emit = () => onUpdate(snapshot());

  const onLine = (line) => {
    const text = line.trim();
    if (!text) {
      return;
    }
    log.push(text);
    if (log.length > MAX_LOG_LINES) {
      log.shift();
    }
    const layer = /^([0-9a-f]{12}): (.+)$/.exec(text);
    if (layer) {
      layers.set(layer[1], layer[2]);
    }
    statusLine = text;
    emit();
  };

  const onData = (chunk) => {
    const text = partial + chunk.toString();
    output += chunk.toString();
    const lines = text.split(/\r?\n|\r/);
    partial = lines.pop();
    lines.forEach(onLine);
  };

  const finish = async (code, spawnError) => {
    child = undefined;
    if (partial) {
      onLine(partial);
      partial = '';
    }
    if (cancelled) {
      state = 'cancelled';
      emit();
      return;
    }
    const local = await inspectImage(image);
    if (code === 0 && local.present && !spawnError) {
      state = 'done';
      error = undefined;
      statusLine = 'Image downloaded.';
      emit();
      return;
    }
    error = code === 0 && !local.present && !spawnError
      ? { kind: 'docker', retryable: false, message: 'sima-cli finished but the image is not on this computer.', hint: lastMeaningfulLine(output) }
      : classifyPullError(output, spawnError);
    if (error.retryable && attempt < maxRetries + 1) {
      const base = RETRY_DELAYS_SECONDS[Math.min(attempt - 1, RETRY_DELAYS_SECONDS.length - 1)];
      const delay = error.slow ? base * 4 : base;
      state = 'waiting';
      retryAt = Date.now() + delay * 1000;
      timer = setTimeout(start, delay * 1000);
    } else {
      state = 'failed';
    }
    emit();
  };

  function start() {
    clearTimeout(timer);
    attempt += 1;
    state = 'running';
    error = undefined;
    retryAt = undefined;
    output = '';
    statusLine = attempt > 1 ? `Retrying (attempt ${attempt} of ${maxRetries + 1})…` : 'Starting download…';
    emit();
    child = spawn(simaCliFile, ['install', resource], {
      env: { ...env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: !IS_WINDOWS, // own process group, so cancel also stops `docker pull`
    });
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('error', (err) => finish(null, err));
    child.on('close', (code) => finish(code));
  }

  start();

  return {
    cancel() {
      cancelled = true;
      clearTimeout(timer);
      if (!child) {
        state = 'cancelled';
        emit();
        return;
      }
      try {
        if (IS_WINDOWS) {
          child.kill();
        } else {
          process.kill(-child.pid, 'SIGTERM');
        }
      } catch {
        child.kill();
      }
    },
    retryNow() {
      if (state === 'waiting') {
        start();
      }
    },
  };
}

// ──────────────────────────── Setup ─────────────────────────────

function expandHome(value) {
  return value.replace(/^~(?=$|[\\/])/, os.homedir());
}

function shellQuote(value) {
  if (IS_WINDOWS) {
    return `'${value.replace(/'/g, "''")}'`;
  }
  return /^[\w@%+=:,./-]+$/.test(value) ? value : `'${value.replace(/'/g, "'\\''")}'`;
}

function validateConfig(config) {
  const errors = {};
  if (config.devkitMode === 'pair') {
    const ip = (config.devkitIp || '').trim();
    if (!ip) {
      errors.devkitIp = 'Enter the DevKit IP address, or choose "No DevKit".';
    } else if (!/^[A-Za-z0-9.-]{1,253}$/.test(ip)) {
      errors.devkitIp = 'Use an IP address like 192.168.1.20 or a host name.';
    }
  }
  const workspace = (config.workspace || '').trim();
  if (!workspace) {
    errors.workspace = 'Choose a workspace folder.';
  } else if (!path.isAbsolute(expandHome(workspace))) {
    errors.workspace = 'Use an absolute path, or one starting with ~.';
  }
  return errors;
}

/**
 * Builds `sima-cli sdk setup` with every answer the page collected. -n takes
 * the defaults for anything else (for example the DevKit registry) instead of
 * asking. -y continues past failed host checks, which -n alone turns into an
 * abort: sima-cli's firewall check fails wherever ufw is installed, even
 * inactive, because "inactive" contains "active". -y would also install the
 * Model Compiler and Edgematic Studio, so both are always explicit below.
 * Setup then only stops for a sudo password.
 */
function buildSetupCommand({ simaCliFile, image, config }) {
  const errors = validateConfig(config);
  const args = ['sdk', 'setup', '-n', '-y', '--image', image];
  const env = {};
  if (config.devkitMode === 'pair') {
    args.push('--devkit', (config.devkitIp || '').trim());
  }
  if (config.modelCompiler !== 'install') {
    args.push('--no-model-compiler');
  }
  if (config.codingAgents === 'install') {
    args.push('--all-extensions');
  } else if (config.codingAgents === 'skip') {
    env.SDK_SKIP_CODING_AGENT_INSTALL = '1';
  }
  args.push(config.edgematicStudio ? '--studio' : '--no-studio');
  args.push('--workspace', expandHome((config.workspace || '').trim()));

  const quotedArgs = args.map(shellQuote).join(' ');
  const envNames = Object.keys(env);
  const shellCommand = IS_WINDOWS
    ? `${envNames.map((k) => `$env:${k}='${env[k]}'; `).join('')}& ${shellQuote(simaCliFile)} ${quotedArgs}`
    : `${envNames.map((k) => `${k}=${env[k]} `).join('')}${shellQuote(simaCliFile)} ${quotedArgs}`;
  const display = IS_WINDOWS
    ? `${envNames.map((k) => `$env:${k}='${env[k]}'; `).join('')}sima-cli ${quotedArgs}`
    : `${envNames.map((k) => `${k}=${env[k]} `).join('')}sima-cli ${quotedArgs}`;
  return { shellCommand, display, errors, file: simaCliFile, args, env };
}

module.exports = {
  listSdkVersions,
  resolveSdkRef,
  checkPrerequisites,
  containerNameFor,
  inspectImage,
  listSdkContainers,
  listAllSdkContainers,
  readCodeUi,
  createPull,
  classifyPullError,
  validateConfig,
  buildSetupCommand,
  expandHome,
  shellQuote,
  run,
};
