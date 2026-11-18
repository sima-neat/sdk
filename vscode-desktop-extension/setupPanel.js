'use strict';

const vscode = require('vscode');
const crypto = require('crypto');
const fs = require('fs');
const sdk = require('./sdk');
const reset = require('./reset');
const { createSetupRun } = require('./setupRun');
const hostStatus = require('./hostStatus');

// Remembers an unfinished download so the page can offer to resume it after a restart.
const PULL_MARKER_KEY = 'simaNeat.pullInProgress';

let extensionContext;
let api;
let currentPanel;
// The download outlives the page: closing the tab doesn't stop it.
let activePull;
// Setup runs in the background too; the page shows its progress.
let activeSetup;
let pullSnapshot = { state: 'idle' };
// What the side bar and status bar show while the page is closed: last known step, version and containers.
let lastHost = { step: 1, total: 5, version: '', image: '', containers: [] };

function pullPercent(snapshot) {
  const { done, total, bytesDone, bytesTotal } = (snapshot && snapshot.progress) || {};
  if (bytesTotal) {
    return Math.round((bytesDone / bytesTotal) * 100);
  }
  return total ? Math.round((done / total) * 100) : 0;
}

/** Updates the "Neat SDK" side bar view and the "SiMa SDK" status bar item. */
function publishHostStatus() {
  const running = lastHost.containers.find((c) => c.state === 'running');
  if (running) {
    hostStatus.set({ kind: 'running', version: lastHost.version || hostStatus.versionFromImage(lastHost.image), container: running.name });
    return;
  }
  const progress = { kind: 'progress', step: lastHost.step, total: lastHost.total, version: lastHost.version, pct: pullPercent(pullSnapshot) };
  if (pullSnapshot.state === 'running' || pullSnapshot.state === 'waiting') {
    hostStatus.set({ ...progress, downloading: true });
  } else if (pullSnapshot.state === 'failed') {
    hostStatus.set({ ...progress, failed: true });
  } else if (lastHost.step > 1) {
    hostStatus.set(progress);
  } else if (hostStatus.get().kind !== 'running') {
    hostStatus.set({ kind: 'none' });
  }
}

function sdkSettings() {
  return vscode.workspace.getConfiguration('simaNeat.sdk');
}

function readConfig() {
  const settings = sdkSettings();
  return {
    devkitMode: settings.get('devkitMode', 'none'),
    devkitIp: settings.get('devkitIp', ''),
    modelCompiler: settings.get('modelCompiler', 'skip'),
    codingAgents: settings.get('codingAgents', 'skip'),
    aiAgent: settings.get('aiAgent', 'claude'),
    edgematicStudio: settings.get('edgematicStudio', false),
    workspace: settings.get('workspace', '~/workspace'),
  };
}

const RESET_PARTS = ['containers', 'images', 'extensionState', 'logout', 'simaCli'];
const CONFIG_KEYS = new Set(['devkitMode', 'devkitIp', 'modelCompiler', 'codingAgents', 'aiAgent', 'edgematicStudio', 'workspace']);

// The AI agent of Configure, as a Marketplace extension installed in the SDK container.
const AGENT_EXTENSIONS = { claude: 'anthropic.claude-code', codex: 'openai.chatgpt' };

/** containerExtensions with the chosen agent instead of the other one; other extensions are kept. */
function withAgent(extensions, agent) {
  const agentIds = Object.values(AGENT_EXTENSIONS);
  const rest = (extensions || []).filter((id) => !agentIds.includes(String(id).toLowerCase()));
  return AGENT_EXTENSIONS[agent] ? [AGENT_EXTENSIONS[agent], ...rest] : rest;
}

class SetupPanel {
  constructor() {
    this.disposables = [];
    this.started = false;
    this.state = {
      cli: { found: false },
      login: { loggedIn: false },
      // Sign in to SiMa: idle | installing | pending | error, with the reason for an error.
      signin: { phase: 'idle' },
      cliLatest: '',
      // DevKits found on the network for Configure: idle | searching | done.
      devkits: { status: 'idle', items: [] },
      prereqs: { status: 'checking', items: [] },
      versions: { status: 'loading', items: [] },
      selectedRef: undefined,
      release: { status: 'idle' },
      image: { status: 'unknown' },
      containers: [],
      pull: pullSnapshot,
      config: readConfig(),
      configErrors: {},
      command: '',
      setup: { state: 'idle' },
      ideAvailable: false,
      devContainers: api.isDevContainersInstalled(),
      reset: { status: 'closed' },
    };

    const mediaRoot = vscode.Uri.joinPath(extensionContext.extensionUri, 'media');
    this.panel = vscode.window.createWebviewPanel('simaNeatSetup', 'Studio: Set up SDK', vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [mediaRoot],
    });
    this.panel.iconPath = vscode.Uri.joinPath(mediaRoot, 'studio', 'circuit-board.svg');
    this.panel.webview.html = this.html(mediaRoot);

    this.disposables.push(
      this.panel.webview.onDidReceiveMessage((message) => this.onMessage(message).catch((err) => {
        vscode.window.showErrorMessage(`Studio: Set up SDK: ${err.message}`);
      })),
      this.panel.onDidDispose(() => this.dispose()),
      api.onDidChange(() => this.refreshCliAndLogin()),
      vscode.extensions.onDidChange(() => {
        this.state.devContainers = api.isDevContainersInstalled();
        this.post();
      }),
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('simaNeat.sdk')) {
          this.state.config = readConfig();
          this.updateCommand();
          this.post();
        }
      }),
    );
  }

  html(mediaRoot) {
    const webview = this.panel.webview;
    const nonce = crypto.randomBytes(16).toString('base64');
    const css = webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, 'setup.css'));
    const script = webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, 'setup.js'));
    const codicons = webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, 'codicons', 'codicon.css'));
    const template = fs.readFileSync(vscode.Uri.joinPath(mediaRoot, 'setup.html').fsPath, 'utf8');
    return template
      .replace(/\{\{cspSource\}\}/g, webview.cspSource)
      .replace(/\{\{nonce\}\}/g, nonce)
      .replace('{{codiconUri}}', codicons.toString())
      .replace('{{cssUri}}', css.toString())
      .replace('{{scriptUri}}', script.toString());
  }

  post(now = false) {
    const { release, containers } = this.state;
    lastHost = {
      ...lastHost,
      version: release.status === 'ok' && release.version ? `v${String(release.version).replace(/^v/, '')}` : lastHost.version,
      image: release.status === 'ok' ? release.image : lastHost.image,
      containers,
    };
    publishHostStatus();
    const send = () => {
      this.postTimer = undefined;
      this.panel.webview.postMessage({ type: 'state', state: this.state });
    };
    if (now) {
      clearTimeout(this.postTimer);
      send();
    } else if (!this.postTimer) {
      this.postTimer = setTimeout(send, 100);
    }
  }

  async refreshAll() {
    this.refreshCliAndLogin();
    api.latestSimaCliVersion().then((latest) => {
      this.state.cliLatest = latest;
      this.post();
    });
    await Promise.all([this.refreshPrereqs(), this.loadVersions()]);
  }

  refreshCliAndLogin() {
    const cli = api.getSimaCli();
    this.state.cli = cli ? { found: true, version: cli.version, file: cli.file } : { found: false };
    const login = api.readLoginState().external;
    this.state.login = { loggedIn: login.loggedIn, user: login.user, name: login.name, email: login.email };
    this.updateCommand();
    this.post();
  }

  /** Sign in to SiMa: installs sima-cli quietly when it's missing, then signs in through the browser. */
  async signIn() {
    if (this.signinRun) {
      return;
    }
    const setPhase = (signin) => {
      this.state.signin = signin;
      this.post(true);
    };
    try {
      if (!api.getSimaCli() && !(await api.refresh())) {
        setPhase({ phase: 'installing' });
        this.signinRun = api.installSimaCliQuietly();
        const installed = await this.signinRun.done;
        this.refreshCliAndLogin();
        if (!installed.ok) {
          setPhase(installed.cancelled ? { phase: 'idle' } : { phase: 'error', reason: installed.reason, needsTerminal: installed.needsTerminal });
          return;
        }
      }
      setPhase({ phase: 'pending' });
      this.signinRun = api.loginQuietly();
      const result = await this.signinRun.done;
      this.refreshCliAndLogin();
      setPhase(result.ok || result.cancelled ? { phase: 'idle' } : { phase: 'error', reason: result.reason });
    } finally {
      this.signinRun = undefined;
    }
  }

  cancelSignIn() {
    if (this.signinRun) {
      this.signinRun.cancel();
    }
  }

  async refreshPrereqs() {
    this.state.prereqs = { ...this.state.prereqs, status: 'checking' };
    this.post();
    this.state.prereqs = await sdk.checkPrerequisites(this.state.release.requiredGb);
    this.post();
    this.findDevkits();
  }

  /** Looks once for DevKits on the network (needs sima-cli and ethtool), for Configure (frame A4). */
  async findDevkits() {
    const ethtool = (this.state.prereqs.items || []).find((i) => i.id === 'ethtool');
    const cli = api.getSimaCli();
    if (this.state.devkits.status !== 'idle' || !cli || !ethtool || ethtool.status !== 'ok') {
      return;
    }
    this.state.devkits = { status: 'searching', items: [] };
    this.post();
    const items = await sdk.discoverDevkits(cli.file, api.cliEnv);
    this.state.devkits = { status: 'done', items };
    if (items.length && !String(sdkSettings().get('devkitIp', '')).trim()) {
      await sdkSettings().update('devkitIp', items[0].ip, vscode.ConfigurationTarget.Global);
    }
    this.post();
  }

  async loadVersions() {
    this.state.versions = { status: 'loading', items: [] };
    this.post();
    const { items, warning } = await sdk.listSdkVersions();
    const saved = sdkSettings().get('version', '');
    if (saved && !items.some((i) => i.ref === saved)) {
      items.unshift({ ref: saved, label: `${saved} — saved choice`, recommended: false });
    }
    this.state.versions = { status: items.length ? 'ok' : 'error', items, warning };
    const recommended = items.find((i) => i.recommended) || items.find((i) => i.ref === 'main') || items[0];
    const ref = saved || (recommended && recommended.ref);
    if (ref) {
      await this.selectVersion(ref, false);
    } else {
      this.post();
    }
  }

  async selectVersion(ref, save) {
    if (save) {
      await sdkSettings().update('version', ref, vscode.ConfigurationTarget.Global);
    }
    this.state.selectedRef = ref;
    this.state.release = { status: 'loading', ref };
    this.state.image = { status: 'unknown' };
    this.state.containers = [];
    this.post();
    try {
      const release = await sdk.resolveSdkRef(ref);
      if (this.state.selectedRef !== ref) {
        return;
      }
      this.state.release = { status: 'ok', ...release };
      this.loadRegistryInfo(release.image);
    } catch (err) {
      if (this.state.selectedRef !== ref) {
        return;
      }
      this.state.release = { status: 'error', ref, error: err.message };
    }
    this.updateCommand();
    await this.refreshImage();
  }

  async refreshImage() {
    const { release } = this.state;
    if (release.status !== 'ok') {
      this.post();
      return;
    }
    const [image, containers] = await Promise.all([sdk.inspectImage(release.image), sdk.listSdkContainers(release.image)]);
    if (this.state.release !== release) {
      return;
    }
    this.state.image = { status: image.present ? 'present' : 'missing', ...image };
    this.state.containers = containers;
    this.state.ideAvailable = Boolean(sdk.readCodeUi(sdk.containerNameFor(release.image)));
    this.state.devContainers = api.isDevContainersInstalled();

    const marker = extensionContext.globalState.get(PULL_MARKER_KEY);
    if (marker && marker.image === release.image) {
      if (image.present) {
        await extensionContext.globalState.update(PULL_MARKER_KEY, undefined);
      } else if (!activePull && pullSnapshot.state === 'idle') {
        setPullSnapshot({ state: 'interrupted' });
      }
    }
    if (this.state.setup.state === 'idle' && containers.some((c) => c.state === 'running')) {
      this.state.setup = { state: 'done' };
    }
    this.post();
  }

  /** Platform version and download size from ghcr.io, for "Platform 3.0.0 · 10.1 GB download". */
  loadRegistryInfo(image) {
    const info = registryInfo(image);
    info.then(({ layers, platform }) => {
      const { release } = this.state;
      if (release.status !== 'ok' || release.image !== image) {
        return;
      }
      let downloadBytes = 0;
      for (const size of layers.values()) {
        downloadBytes += size;
      }
      this.state.release = { ...release, platform, downloadBytes };
      this.post();
    }, () => {});
  }

  updateCommand() {
    const { cli, release, config } = this.state;
    if (cli.found && release.status === 'ok') {
      const built = sdk.buildSetupCommand({ simaCliFile: cli.file, image: release.image, config });
      this.state.command = built.display;
      this.state.configErrors = built.errors;
    } else {
      this.state.command = '';
      this.state.configErrors = sdk.validateConfig(config);
    }
  }

  startPull() {
    const { cli, release } = this.state;
    if (!cli.found || release.status !== 'ok') {
      return;
    }
    startPullFor(cli.file, { image: release.image, resource: release.resource });
  }

  runPullInTerminal() {
    const { cli, release } = this.state;
    if (!cli.found || release.status !== 'ok') {
      return;
    }
    const command = `${sdk.shellQuote(cli.file)} install ${sdk.shellQuote(release.resource)}`;
    api.runInTerminal('sdk-pull', 'Neat SDK image download', command, () => {
      setPullSnapshot({ state: 'idle' });
      if (currentPanel) {
        currentPanel.refreshImage();
      }
    });
  }

  async runSetup(inTerminal = false) {
    const { cli, release, config, containers } = this.state;
    if (!cli.found || release.status !== 'ok') {
      return;
    }
    const built = sdk.buildSetupCommand({ simaCliFile: cli.file, image: release.image, config });
    if (Object.keys(built.errors).length) {
      vscode.window.showWarningMessage('Finish the Configure step first.');
      return;
    }
    if (containers.length) {
      const choice = await vscode.window.showWarningMessage(
        `Setup recreates the SDK container "${containers[0].name}".`,
        {
          modal: true,
          detail: 'Your workspace folder on this computer is kept. Anything stored only inside the container is removed.',
        },
        'Continue',
      );
      if (choice !== 'Continue') {
        return;
      }
    }
    fs.mkdirSync(sdk.expandHome(config.workspace.trim()), { recursive: true });
    const finish = async (exitCode, extra = {}) => {
      if (currentPanel !== this) {
        return;
      }
      await this.refreshImage();
      const running = this.state.containers.some((c) => c.state === 'running');
      // A failed setup can leave the previous container running; that's still a failure.
      const succeeded = running && (exitCode === 0 || exitCode === undefined);
      this.state.setup = { ...extra, state: succeeded ? 'done' : 'failed', exitCode, containerRunning: running };
      this.post();
      if (succeeded && sdkSettings().get('openAfterSetup', true)) {
        await api.openSdkInVsCode({ containerName: sdk.containerNameFor(release.image), interactive: false });
      }
    };
    // Windows has no pseudo-terminal for background runs, so prompts need a real terminal there.
    if (inTerminal || process.platform === 'win32') {
      this.state.setup = { state: 'running', inTerminal: true };
      this.post();
      api.runInTerminal('sdk-setup', 'Neat SDK setup', built.shellCommand, (exitCode) => finish(exitCode));
      return;
    }
    this.state.setup = { state: 'running', log: [], status: 'Starting setup…' };
    this.post();
    activeSetup = createSetupRun({
      file: built.file,
      args: built.args,
      // Plain, wide output reads better in the page's log.
      env: { ...api.cliEnv, ...built.env, NO_COLOR: '1', COLUMNS: '160', PYTHONUNBUFFERED: '1' },
      ask: ({ kind, prompt }) => vscode.window.showInputBox({
        title: 'Neat SDK setup needs an answer',
        prompt: kind === 'password' ? `${prompt} (sudo is needed to share your workspace with the DevKit)` : prompt,
        password: kind === 'password',
        ignoreFocusOut: true,
      }),
      onUpdate: (snapshot) => {
        if (snapshot.state === 'running') {
          this.state.setup = { state: 'running', log: snapshot.log, status: snapshot.status, startedAt: snapshot.startedAt };
          this.post();
          return;
        }
        activeSetup = undefined;
        void finish(snapshot.exitCode, { log: snapshot.log, status: snapshot.status, cancelled: snapshot.state === 'cancelled' });
      },
    });
  }

  openInVsCode() {
    const { release } = this.state;
    const containerName = release.status === 'ok' ? sdk.containerNameFor(release.image) : undefined;
    return api.openSdkInVsCode({ containerName });
  }

  async openIde() {
    const { release } = this.state;
    const codeUi = release.status === 'ok' && sdk.readCodeUi(sdk.containerNameFor(release.image));
    if (!codeUi) {
      vscode.window.showWarningMessage('No SDK IDE address found yet. Run setup first.');
      return;
    }
    await vscode.env.openExternal(vscode.Uri.parse(codeUi.url));
    if (codeUi.password) {
      await vscode.env.clipboard.writeText(codeUi.password);
      vscode.window.showInformationMessage(
        'Opened the SDK IDE in your browser. Its password is on your clipboard. '
          + 'If the browser warns about the certificate, that is the SDK\'s own local certificate.',
      );
    }
  }

  openShell() {
    const { cli } = this.state;
    if (!cli.found) {
      return;
    }
    api.openHostShell('Neat SDK', `${sdk.shellQuote(cli.file)} sdk neat`);
  }

  async loadReset() {
    this.state.reset = { status: 'loading' };
    this.post();
    this.state.reset = { status: 'open', info: await reset.describe() };
    this.post();
  }

  /** Asks for confirmation with the exact list, then removes the chosen parts. */
  async runReset(choices) {
    const picked = Object.fromEntries(RESET_PARTS.map((key) => [key, Boolean(choices && choices[key])]));
    if (!Object.values(picked).some(Boolean)) {
      return;
    }
    const info = await reset.describe();
    const names = info.containers.map((c) => c.name);
    const lines = [];
    if (picked.containers && names.length) {
      lines.push(`• SDK containers: ${names.join(', ')}`);
    }
    if (picked.images && info.images.length) {
      lines.push(`• SDK images: ${info.images.map((i) => `${i.ref} (${i.size})`).join(', ')}. Setup downloads them again.`);
    }
    if (picked.extensionState) {
      lines.push("• This extension's settings and setup progress, and Dev Containers' settings for SDK containers");
    }
    if (picked.logout || picked.simaCli) {
      lines.push('• Your sima-cli logins (Developer Portal and internal)');
    }
    if (picked.simaCli) {
      lines.push('• sima-cli itself (~/.sima-cli)');
    }
    if (!lines.length) {
      vscode.window.showInformationMessage('Nothing to remove for the selected parts.');
      return;
    }
    lines.push('', 'Your workspace folder and its files are kept.');
    if (picked.containers && info.attachedTo && names.includes(info.attachedTo)) {
      lines.push(`This window is open in ${info.attachedTo}, so it will lose its connection.`);
    }
    const choice = await vscode.window.showWarningMessage('Start over? This removes:', { modal: true, detail: lines.join('\n') }, 'Reset');
    if (choice !== 'Reset') {
      return;
    }
    if (activePull) {
      activePull.cancel();
    }
    this.state.reset = { status: 'running' };
    this.post();
    const cli = api.getSimaCli();
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: 'Starting over' },
      (progress) => reset.run(extensionContext, picked, { simaCliFile: cli && cli.file, env: api.cliEnv, progress }),
    );
    await extensionContext.globalState.update(PULL_MARKER_KEY, undefined);
    setPullSnapshot({ state: 'idle' });
    await api.refresh();
    if (currentPanel !== this) {
      return;
    }
    this.state.reset = { status: 'closed', result };
    this.state.setup = { state: 'idle' };
    this.state.config = readConfig();
    await this.refreshAll();
    if (result.failed.length) {
      vscode.window.showWarningMessage(`Start over finished with ${result.failed.length} problem(s). See the bottom of the setup page.`);
    } else {
      vscode.window.showInformationMessage('Start over finished. Setup begins again from step 1.');
    }
  }

  async onMessage(message) {
    if (message.type === 'ready') {
      this.post(true);
      if (!this.started) {
        this.started = true;
        await this.refreshAll();
      }
      return;
    }
    if (message.type === 'hostStatus' && message.value) {
      const { active, total } = message.value;
      if (active !== lastHost.step || total !== lastHost.total) {
        lastHost = { ...lastHost, step: active, total };
        publishHostStatus();
      }
      return;
    }
    if (message.type === 'config' && CONFIG_KEYS.has(message.key)) {
      await sdkSettings().update(message.key, message.value, vscode.ConfigurationTarget.Global);
      if (message.key === 'aiAgent') {
        const extensions = withAgent(sdkSettings().get('containerExtensions', [AGENT_EXTENSIONS.claude]), message.value);
        await sdkSettings().update('containerExtensions', extensions, vscode.ConfigurationTarget.Global);
      }
      return;
    }
    if (message.type !== 'action') {
      return;
    }
    switch (message.id) {
      case 'installCli': return api.installSimaCli();
      case 'login': return api.login();
      case 'logout': return api.logout();
      case 'signin': return this.signIn();
      case 'signinCancel': return this.cancelSignIn();
      case 'recheck': return Promise.all([this.refreshPrereqs(), this.refreshImage()]);
      case 'selectVersion': return this.selectVersion(message.value, true);
      case 'pull': return this.startPull();
      case 'cancelPull': return activePull && activePull.cancel();
      case 'retryNow': return activePull && activePull.retryNow();
      case 'pullInTerminal': return this.runPullInTerminal();
      case 'browseWorkspace': {
        const picked = await vscode.window.showOpenDialog({
          canSelectFolders: true, canSelectFiles: false, canSelectMany: false, openLabel: 'Use as SDK workspace',
        });
        if (picked && picked[0]) {
          await sdkSettings().update('workspace', picked[0].fsPath, vscode.ConfigurationTarget.Global);
        }
        return undefined;
      }
      case 'copyCommand':
        await vscode.env.clipboard.writeText(this.state.command);
        vscode.window.showInformationMessage('Setup command copied.');
        return undefined;
      case 'runSetup': return this.runSetup();
      case 'setupInTerminal': return this.runSetup(true);
      case 'cancelSetup': return activeSetup && activeSetup.cancel();
      case 'openVsCode': return this.openInVsCode();
      case 'resetLoad': return this.loadReset();
      case 'resetCancel':
        this.state.reset = { status: 'closed' };
        this.post();
        return undefined;
      case 'resetRun': return this.runReset(message.value);
      case 'openIde': return this.openIde();
      case 'openShell': return this.openShell();
      case 'doctor':
        if (this.state.cli.found) {
          api.runInTerminal('sdk-doctor', 'Neat SDK doctor', `${sdk.shellQuote(this.state.cli.file)} sdk doctor`, () => {});
        }
        return undefined;
      case 'openLink':
        if (/^https:\/\//.test(message.value || '')) {
          await vscode.env.openExternal(vscode.Uri.parse(message.value));
        }
        return undefined;
      default:
        return undefined;
    }
  }

  dispose() {
    clearTimeout(this.postTimer);
    this.disposables.forEach((d) => d.dispose());
    if (currentPanel === this) {
      currentPanel = undefined;
    }
  }
}

// Registry answers per image, shared by the page and the download.
const registryAnswers = new Map();
function registryInfo(image) {
  if (!registryAnswers.has(image)) {
    const answer = sdk.registryImage(image);
    answer.catch(() => registryAnswers.delete(image));
    registryAnswers.set(image, answer);
  }
  return registryAnswers.get(image);
}

/** Starts (or resumes: Docker keeps finished layers) the download of an SDK image. */
function startPullFor(simaCliFile, target) {
  if (activePull) {
    return;
  }
  extensionContext.globalState.update(PULL_MARKER_KEY, { ...target, startedAt: Date.now() });
  activePull = sdk.createPull({
    simaCliFile,
    env: api.cliEnv,
    ...target,
    maxRetries: vscode.workspace.getConfiguration('simaNeat.sdk').get('pullRetries', 4),
    onUpdate: (snapshot) => onPullUpdate(snapshot, target),
    layerSizes: registryInfo(target.image).then((info) => info.layers),
  });
}

/** "SDK download stopped at 61%: network connection lost." with Open setup and Retry (frame A3c). */
function notifyPullFailed(snapshot, target) {
  const reason = String((snapshot.error && snapshot.error.message) || 'the download failed').replace(/\.$/, '');
  vscode.window.showWarningMessage(`SDK download stopped at ${pullPercent(snapshot)}%: ${reason}.`, 'Open setup', 'Retry')
    .then((choice) => {
      if (choice === 'Open setup') {
        show();
      } else if (choice === 'Retry') {
        const cli = api.getSimaCli();
        if (cli) {
          startPullFor(cli.file, target);
        }
      }
    });
}

function setPullSnapshot(snapshot) {
  pullSnapshot = snapshot;
  publishHostStatus();
  if (currentPanel) {
    currentPanel.state.pull = snapshot;
    currentPanel.post();
  }
}

function onPullUpdate(snapshot, target) {
  setPullSnapshot(snapshot);
  if (!['done', 'failed', 'cancelled'].includes(snapshot.state)) {
    return;
  }
  activePull = undefined;
  if (snapshot.state === 'done') {
    extensionContext.globalState.update(PULL_MARKER_KEY, undefined);
    vscode.window.showInformationMessage(`SiMa SDK ${lastHost.version || hostStatus.versionFromImage(target.image)} downloaded.`);
  } else if (snapshot.state === 'failed') {
    notifyPullFailed(snapshot, target);
  }
  if (currentPanel) {
    currentPanel.refreshImage();
  }
}

/** Opens the setup page, or brings the open one to the front. */
function show() {
  if (currentPanel) {
    currentPanel.panel.reveal();
    return;
  }
  currentPanel = new SetupPanel();
}

function init(context, extensionApi) {
  extensionContext = context;
  api = extensionApi;
}

function dispose() {
  if (activePull) {
    activePull.cancel();
  }
  if (activeSetup) {
    activeSetup.cancel();
  }
  if (currentPanel) {
    currentPanel.panel.dispose();
  }
}

module.exports = { init, show, dispose, withAgent };
