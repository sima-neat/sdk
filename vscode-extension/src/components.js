const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const CATALOG_URL = 'https://artifacts.neat.sima.ai/sdk/components.json';
const IDS = { codex: 'openai.chatgpt', claude: 'anthropic.claude-code' };
const ARCHES = { x64: 'amd64', arm64: 'arm64' };
const VERSION = /^\d+\.\d+\.\d+(?:\.\d+)?$/;
const SHA = /^[a-f0-9]{64}$/;
const HOSTS = new Set(['artifacts.neat.sima.ai', 'open-vsx.org', 'openvsx.eclipsecontent.org', 'registry.npmjs.org']);
function artifact(value) {
  if (!value || !SHA.test(value.sha256 || '')) throw Error('Missing artifact SHA-256');
  const url = new URL(value.url);
  if (url.protocol !== 'https:' || !HOSTS.has(url.hostname) || url.username || url.password || url.hash || url.search || url.port)
    throw Error('Unsupported component artifact URL');
}
function validateCatalog(value) {
  if (!value || value.schema_version !== 1 || !Number.isSafeInteger(value.revision) || value.revision < 1 ||
      !value.sdks || Array.isArray(value.sdks) || !Object.hasOwn(value.sdks, value.build_sdk_version))
    throw Error('Unsupported SDK component manifest');
  const releases = new Set();
  for (const [sdk, row] of Object.entries(value.sdks)) {
    if (!VERSION.test(sdk) || !['candidate', 'qualified', 'revoked'].includes(row.status) ||
        !Array.isArray(row.sdk_releases) || !row.sdk_releases.length ||
        !Array.isArray(row.engines) || !row.engines.length ||
        !Array.isArray(row.architectures) || !row.architectures.length ||
        row.architectures.some(a => !['amd64', 'arm64'].includes(a))) throw Error('Invalid SDK compatibility entry');
    for (const release of row.sdk_releases) {
      if (!VERSION.test(release) || releases.has(release)) throw Error('Ambiguous SDK release mapping');
      releases.add(release);
    }
    for (const engine of row.engines)
      if (!/^4\.\d+\.\d+$/.test(engine.code_server) || !/^1\.\d+\.\d+$/.test(engine.vscode))
        throw Error('Invalid code-server/VS Code engine pair');
    for (const [key, id] of Object.entries(IDS)) {
      const component = row.components?.[key];
      if (component?.id !== id || !VERSION.test(component.version)) throw Error('Invalid agent component');
      for (const arch of row.architectures) artifact(component.artifacts?.[arch]);
    }
    if (row.components?.['codex-cli']?.package !== '@openai/codex' ||
        !VERSION.test(row.components['codex-cli'].version)) throw Error('Invalid Codex CLI component');
    artifact(row.components['codex-cli'].artifact);

  }
  return value;
}
function resolveCatalog(catalog, { release, arch, codeServer, vscode, testVersion, allowCandidate = false }) {
  validateCatalog(catalog);
  const normalized = /^v?(\d+\.\d+\.\d+(?:\.\d+)?)$/.exec(release || '')?.[1];
  // Development images require an explicit test-only SDK selection, never a platform-version fallback.
  const sdk = testVersion && allowCandidate ? testVersion : Object.keys(catalog.sdks).find(
    key => catalog.sdks[key].sdk_releases.includes(normalized));
  const row = sdk && catalog.sdks[sdk];
  if (!row) throw Error('No compatible component mapping for this SDK release');
  if (row.status !== 'qualified' && !(allowCandidate && row.status === 'candidate'))
    throw Error(`SDK ${sdk} components are ${row.status}; no qualified installation is available`);
  if (!row.architectures.includes(arch)) throw Error('This SDK architecture has not been qualified');
  if (!row.engines.some(engine => engine.code_server === codeServer && engine.vscode === vscode))
    throw Error('This code-server / VS Code engine pair has not been qualified');
  return { sdkVersion: sdk, status: row.status, ...row };
}
async function responseFrom(url, fetcher, signal) {
  for (let redirects = 0; redirects < 5; redirects++) {
    artifact({ url, sha256: '0'.repeat(64) });
    const response = await fetcher(url, { signal, redirect: 'manual', headers: { 'Cache-Control': 'no-cache' } });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      await response.body?.cancel();
      url = new URL(response.headers.get('location'), url).href;
      continue;
    }
    if (!response.ok) { await response.body?.cancel(); throw Error(`Component request failed (HTTP ${response.status})`); }
    return response;
  }
  throw Error('Too many component download redirects');
}
async function fetchCatalog(fetcher = fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await responseFrom(CATALOG_URL, fetcher, controller.signal);
    const chunks = []; let size = 0;
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 256 * 1024) { const error = Error('Component manifest exceeds size limit'); error.invalidCatalog = true; throw error; }
      chunks.push(Buffer.from(chunk));
    }
    // Distinguish malformed/revoked remote data from a network outage: never hide it behind a stale cache.
    try { return validateCatalog(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
    catch (error) { error.invalidCatalog = true; throw error; }
  } finally { controller.abort(); clearTimeout(timer); }
}
async function digest(file) {
  const hash = crypto.createHash('sha256');
  const handle = await fs.open(file, 'r');
  try { for await (const chunk of handle.createReadStream()) hash.update(chunk); }
  finally { await handle.close(); }
  return hash.digest('hex');
}
async function downloadArtifact(item, directory, fetcher = fetch, suffix = '.vsix', { cacheOnly = false } = {}) {
  artifact(item);
  await fs.mkdir(directory, { recursive: true, mode: 0o700 });
  const file = path.join(directory, item.sha256 + suffix);
  try { if (await digest(file) === item.sha256) return file; } catch { /* Download below. */ }
  if (cacheOnly) {
    const error = Error('Offline: this extension package is not cached. Reconnect and retry the installation.');
    error.code = 'OFFLINE_ARTIFACT_UNAVAILABLE';
    throw error;
  }
  const temporary = file + '.' + crypto.randomUUID();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10 * 60 * 1000);
  let handle;
  try {
    const response = await responseFrom(item.url, fetcher, controller.signal);
    handle = await fs.open(temporary, 'wx', 0o600);
    const hash = crypto.createHash('sha256'); let size = 0;
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 1024 * 1024 * 1024) throw Error('Component artifact exceeds size limit');
      hash.update(chunk); await handle.writeFile(chunk);
    }
    await handle.close(); handle = undefined;
    if (hash.digest('hex') !== item.sha256) throw Error('Component artifact checksum mismatch');
    await fs.rename(temporary, file);
    return file;
  } finally { controller.abort(); clearTimeout(timer); await handle?.close(); await fs.rm(temporary, { force: true }); }
}
class ComponentCatalog {
  constructor(context, options = {}) {
    this.context = context;
    this.options = options;
    this.directory = context.globalStorageUri.fsPath;
    this.value = { available: false, loading: true, error: 'Checking SDK component compatibility…' };
    this.listeners = new Set();
  }
  snapshot() { return this.value; }
  subscribe(listener) { this.listeners.add(listener); return { dispose: () => this.listeners.delete(listener) }; }
  async refresh() {
    if (this.pending) return this.pending;
    this.pending = this.load().catch(error => { this.value = { ...this.detected, available: false, error: error.message }; }).then(() => {
      for (const listener of this.listeners) listener(this.value);
      return this.value;
    }).finally(() => { this.pending = undefined; });
    return this.pending;
  }
  async load() {
    await this.readInstalledProfile();
    const env = this.options.env || process.env;
    let catalog, source = 'online';
    const cache = path.join(this.directory, 'components-cache.json');
    try {
      catalog = await (this.options.fetchCatalog || fetchCatalog)();
      try {
        validateCatalog(catalog);
        let previous = this.lastCatalog;
        if (!previous) { try { previous = validateCatalog(JSON.parse(await fs.readFile(cache, 'utf8'))); } catch {} }
        if (previous && previous.revision > catalog.revision) throw Error('Refusing an older component manifest revision');
      } catch (error) { error.invalidCatalog = true; throw error; }
      this.remoteRejected = false;
      this.lastCatalog = catalog;
      try {
        await fs.mkdir(this.directory, { recursive: true, mode: 0o700 });
        const tmp = cache + '.' + crypto.randomUUID();
        await fs.writeFile(tmp, JSON.stringify(catalog), { mode: 0o600 });
        await fs.rename(tmp, cache);
      } catch { /* A cache-write failure must not replace a valid online revocation with stale data. */ }
    } catch (error) {
      if (error.invalidCatalog) { this.remoteRejected = true; throw error; }
      if (this.remoteRejected) throw Error('A valid online component manifest is required after rejected compatibility data');
      source = 'offline';
      catalog = this.lastCatalog;
      for (const file of catalog ? [] : [cache, path.join(this.context.extensionPath, 'components.json')]) {
        try { catalog = validateCatalog(JSON.parse(await fs.readFile(file, 'utf8'))); break; } catch { /* Try bundled copy. */ }
      }
      if (!catalog) throw Error('Component manifest is unavailable online and no validated offline copy exists');
    }
    const execute = this.options.execute || promisify(execFile);
    const releaseText = this.options.releaseText ?? await fs.readFile('/etc/sdk-release', 'utf8');
    const release = /^SDK Release\s*=\s*(.+)$/m.exec(releaseText)?.[1].trim();
    const server = this.options.codeServer ?? JSON.parse(await fs.readFile(this.options.serverVersionFile || '/opt/code-server/package.json', 'utf8')).version;
    let cliVersion = 'Unavailable';
    try { cliVersion = (await execute('codex', ['--version'], { timeout: 5000, env: Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('VSCODE_') && key !== 'ELECTRON_RUN_AS_NODE')) })).stdout.trim().replace(/^codex-cli\s+/, ''); } catch { /* Display unavailable. */ }
    this.detected = { sdkRelease: release, codeServer: server, installedCliVersion: cliVersion };
    const resolved = resolveCatalog(catalog, { release, arch: ARCHES[process.arch], codeServer: server,
      vscode: this.options.vscodeVersion, testVersion: env.SIMA_SDK_COMPONENT_TEST_VERSION,
      allowCandidate: env.SIMA_SDK_COMPONENTS_ALLOW_CANDIDATE === '1' });
    this.value = { ...resolved, available: true, source, installedCliVersion: cliVersion, error: '' };
  }
  async readInstalledProfile() {
    try {
      const profile = JSON.parse(await fs.readFile(path.join(path.dirname(this.context.extensionPath), 'extensions.json'), 'utf8'));
      this.installedProfile = Array.isArray(profile) ? profile : [];
    } catch { this.installedProfile = []; }
  }
  isPinned(target) {
    return Boolean(this.installedProfile?.some(entry => entry.identifier?.id?.toLowerCase() === target.id &&
      entry.version === target.version && entry.metadata?.pinned === true));
  }
  async verifyInstalled(target) {
    await this.readInstalledProfile();
    if (!this.isPinned(target)) throw Error('The editor did not pin the expected component version');
  }
  async artifact(key) {
    const state = await this.refresh();
    if (!state.available) throw Error(state.error);
    const target = state.components[key];
    const file = await downloadArtifact(target.artifacts[ARCHES[process.arch]], path.join(this.directory, 'component-artifacts'), fetch, '.vsix', { cacheOnly: state.source === 'offline' });
    const run = this.options.execute || promisify(execFile);
    const contents = (await run('python3', ['-c',
      'import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(z.read("extension/package.json").decode())', file],
      { timeout: 15000, maxBuffer: 1024 * 1024 })).stdout;
    const metadata = JSON.parse(contents);
    if (`${metadata.publisher}.${metadata.name}`.toLowerCase() !== target.id || metadata.version !== target.version)
      throw Error('VSIX identity or version does not match the component manifest');
    const latest = await this.refresh();
    if (!latest.available || JSON.stringify(latest.components[key]) !== JSON.stringify(target))
      throw Error('Component qualification changed during download; refresh and retry');
    return { file, target };
  }
}
module.exports = { CATALOG_URL, IDS, ARCHES, validateCatalog, resolveCatalog, fetchCatalog, downloadArtifact, ComponentCatalog };
