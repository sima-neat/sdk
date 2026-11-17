'use strict';

// The SDK's Palette sidebar panel (NeatPanelProvider in the SDK extension's
// src/extension.js), run from this computer. Login uses this extension's
// sima-cli login on this computer; DevKit and tutorials go through the
// current SDK container; samples are cloned into the SDK workspace folder.

const crypto = require('crypto');
const { loadStatuses } = require('./panel-status');

const VIEW_ID = 'simaNeatTools.panel';
const SECTIONS = ['container', 'samples', 'tutorials', 'auth', 'devkit'];

function escapeHtml(value) {
  return String(value === undefined || value === null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function iconText(name) {
  const icons = {
    docs: 'D',
    eye: 'I',
    start: 'S',
    remote: '&gt;',
    lock: '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path></svg>',
    out: 'Out',
    ok: 'OK',
    book: '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H7a3 3 0 0 0-3 3V5.5Z"></path><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path></svg>',
    repo: '<svg class="badge-icon github-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5a9.5 9.5 0 0 0-3 18.51c.47.08.64-.2.64-.45v-1.65c-2.6.57-3.15-1.1-3.15-1.1-.43-1.08-1.05-1.37-1.05-1.37-.86-.59.07-.58.07-.58.95.07 1.45.98 1.45.98.84 1.44 2.2 1.02 2.74.78.08-.61.33-1.02.6-1.26-2.08-.24-4.27-1.04-4.27-4.64 0-1.02.37-1.86.97-2.52-.1-.24-.42-1.2.09-2.48 0 0 .79-.25 2.6.96a9 9 0 0 1 4.73 0c1.8-1.21 2.6-.96 2.6-.96.51 1.28.19 2.24.09 2.48.6.66.97 1.5.97 2.52 0 3.61-2.2 4.4-4.29 4.63.34.29.64.86.64 1.74v2.58c0 .25.17.54.65.45A9.5 9.5 0 0 0 12 2.5Z"></path></svg>',
    terminal: '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1.5"></rect><path d="M4 9h3M4 15h3M17 9h3M17 15h3M9 4v3M15 4v3M9 17v3M15 17v3"></path></svg>',
    offline: '!',
  };
  return icons[name] || '';
}

function actionButton(command, icon, title, description, external) {
  return `<button class="action-button" data-command="${escapeHtml(command)}">
    <span class="icon-badge" aria-hidden="true">${iconText(icon)}</span>
    <span class="action-copy">
      <span class="action-title">${escapeHtml(title)}</span>
      <span class="action-description">${escapeHtml(description)}</span>
    </span>
    ${external ? '<span class="external-mark" aria-hidden="true">></span>' : ''}
  </button>`;
}

function formatPathDetail(state) {
  const detail = escapeHtml(state.detail);
  if (!detail) {
    return '';
  }
  if (state.detailKind === 'path-folder') {
    return ` <span class="inline-detail"><code>${detail}</code> folder</span>`;
  }
  return ` <span class="inline-detail">${detail}</span>`;
}

function formatDevKitDetail(state) {
  const detail = escapeHtml(state.detail);
  if (!detail) {
    return '';
  }
  return state.detailKind === 'command' ? ` <code>${detail}</code> to setup DevKit Sync` : ` ${detail}`;
}

function sectionsHtml({ container, samples, tutorials, auth, devkit }) {
  const devKitDisabled = devkit.disabled ? 'disabled' : '';
  const tutorialsDescription = tutorials.detailKind ? '' : escapeHtml(tutorials.status);
  return {
    container: `<p class="subtitle container-line" id="status-container">${escapeHtml(container.status)}</p>`,
    devkit: `<div class="panel-section" id="status-devkit">
    <div class="section-title">DevKit Sync</div>
    <div class="stack">
      <button id="devKitSsh" class="action-button ${devkit.online ? '' : 'secondary'}" data-host="${escapeHtml(devkit.host)}" data-user="${escapeHtml(devkit.user)}" data-port="${escapeHtml(devkit.port)}" ${devKitDisabled}>
        <span class="icon-badge ${devkit.online ? '' : 'secondary'}" aria-hidden="true">${iconText(devkit.online ? 'terminal' : 'offline')}</span>
        <span class="action-copy">
          <span class="action-title">${escapeHtml(devkit.buttonLabel)}</span>
          <span class="action-description">${escapeHtml(devkit.status)}${formatDevKitDetail(devkit)}</span>
        </span>
      </button>
    </div>
  </div>`,
    auth: `<div class="panel-section" id="status-auth">
    <div class="section-title">Developer Portal</div>
    <div class="stack">
      <button id="developerPortalAuth" class="action-button ${auth.signedIn ? 'secondary' : ''}" data-command="${escapeHtml(auth.command)}" ${auth.disabled ? 'disabled' : ''}>
        <span class="icon-badge ${auth.signedIn ? 'secondary' : ''}" aria-hidden="true">${iconText(auth.signedIn ? 'lock' : 'out')}</span>
        <span class="action-copy">
          <span class="action-title">${escapeHtml(auth.buttonLabel)}</span>
          <span class="action-description">${escapeHtml(auth.status)}</span>
        </span>
      </button>
      <p class="detail">${escapeHtml(auth.detail)}</p>
    </div>
  </div>`,
    tutorials: `<div class="panel-section" id="status-tutorials">
    <div class="section-title">Tutorials</div>
    <div class="stack">
      <button id="installTutorials" class="action-button" ${tutorials.disabled ? 'disabled' : ''}>
        <span class="icon-badge teal" aria-hidden="true">${iconText(tutorials.detailKind ? 'ok' : 'book')}</span>
        <span class="action-copy">
          <span class="action-title">${escapeHtml(tutorials.buttonLabel)}</span>
          ${tutorialsDescription ? `<span class="action-description">${tutorialsDescription}</span>` : ''}
        </span>
      </button>
      ${tutorials.detailKind ? `<p class="status">${escapeHtml(tutorials.status)}${formatPathDetail(tutorials)}</p>` : ''}
    </div>
  </div>`,
    samples: `<div class="panel-section" id="status-samples">
    <div class="section-title">Samples</div>
    <div class="stack">
      <button id="cloneSamples" class="action-button" ${samples.disabled ? 'disabled' : ''}>
        <span class="icon-badge teal" aria-hidden="true">${iconText(samples.disabled ? 'ok' : 'repo')}</span>
        <span class="action-copy">
          <span class="action-title">${escapeHtml(samples.buttonLabel)}</span>
          <span class="action-description">${escapeHtml(samples.status)}</span>
        </span>
      </button>
      ${samples.detailKind ? `<p class="status">${escapeHtml(samples.status)}${formatPathDetail(samples)}</p>` : ''}
    </div>
  </div>`,
  };
}

function panelHtml(webview, mediaRoot, vscode, states) {
  const asset = (name) => webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, name));
  const nonce = crypto.randomBytes(16).toString('base64');
  const sections = sectionsHtml(states);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource}; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="${asset('panel.css')}">
</head>
<body>
  <div class="masthead">
    <img class="logo" src="${asset('neat-logo.png')}" alt="SiMa.ai">
    <div>
      <h1 class="title">Palette SDK</h1>
      <p class="subtitle">Build, inspect, and manage SDK workspaces.</p>
    </div>
  </div>
  ${sections.container}
  <div class="quick-links">
    ${actionButton('gettingStarted', 'start', 'Getting Started', 'SDK, DevKit, apps, models and agents', false)}
    ${actionButton('openInVsCode', 'remote', 'Open SDK in VS Code', 'Work inside the SDK container', false)}
    ${actionButton('openDocumentation', 'docs', 'Documentation', 'developer.sima.ai/software', true)}
    ${actionButton('openInsight', 'eye', 'Insight', 'Open detected Insight web UI', true)}
  </div>
  <section class="panel-section" id="status-models" aria-labelledby="registry-title">
    <div class="section-title" id="registry-title">Model Registry</div>
    <div class="stack">
      <p class="subtitle" id="registry-release" aria-live="polite">Release program: Unavailable</p>
      <p class="subtitle" id="registry-program" aria-live="polite" hidden></p>
      ${actionButton('browseModels', 'repo', 'Models', 'Browse model builds and download model files', false)}
    </div>
  </section>
  ${sections.devkit}
  ${sections.auth}
  ${sections.tutorials}
  ${sections.samples}
  <button id="refreshStatus" class="secondary">Refresh status</button>
  <script nonce="${nonce}" src="${asset('panel.js')}"></script>
</body>
</html>`;
}

class PalettePanelProvider {
  constructor(vscode, context, services) {
    this.vscode = vscode;
    this.mediaRoot = vscode.Uri.joinPath(context.extensionUri, 'media', 'neat');
    this.services = services;
    this.disposables = [];
  }

  resolveWebviewView(webviewView) {
    const { vscode } = this;
    this.webviewView = webviewView;
    this.rendered = false;
    webviewView.webview.options = { enableScripts: true, localResourceRoots: [this.mediaRoot] };
    this.disposables.push(
      webviewView.webview.onDidReceiveMessage((message) => this.onMessage(message)),
      webviewView.onDidChangeVisibility(() => webviewView.visible && this.refresh()),
    );
    // Do not keep VS Code waiting for view resolution while probes run.
    void this.refresh();
    return undefined;
  }

  async onMessage(message) {
    const { vscode, services } = this;
    const run = async (label, action) => {
      try {
        await action();
      } catch (error) {
        vscode.window.showErrorMessage(`${label}: ${error.message || error}`);
      } finally {
        await this.refresh();
      }
    };
    switch (message.command) {
      case 'ready':
        this.updateRegistryState(this.registryState);
        return undefined;
      case 'refreshStatus': return this.refresh();
      case 'cloneSamples': return run('Failed to clone samples', services.cloneSamples);
      case 'installTutorials': return run('Failed to install tutorials', services.installTutorials);
      case 'loginDeveloperPortal': return vscode.commands.executeCommand('simaNeat.login');
      case 'logoutDeveloperPortal': return vscode.commands.executeCommand('simaNeat.logout');
      case 'browseModels': return vscode.commands.executeCommand('simaNeat.browseModelRegistry');
      case 'gettingStarted': return vscode.commands.executeCommand('simaNeat.openGettingStarted');
      case 'openInVsCode': return vscode.commands.executeCommand('simaNeat.openSdkInVsCode');
      case 'openDocumentation': return vscode.env.openExternal(vscode.Uri.parse('https://developer.sima.ai/software'));
      case 'openInsight': return run('Insight', services.openInsight);
      case 'openDevKitSsh': return run('DevKit SSH', () => services.openDevKitSsh(message.host, message.user, message.port));
      default: return undefined;
    }
  }

  updateRegistryState(state) {
    this.registryState = state;
    if (this.webviewView && state) {
      void this.webviewView.webview.postMessage({ command: 'registryState', state });
    }
  }

  async refresh() {
    const view = this.webviewView;
    if (!view) {
      return;
    }
    const generation = this.refreshGeneration = (this.refreshGeneration || 0) + 1;
    const loading = (buttonLabel) => ({ disabled: true, buttonLabel, status: 'Checking…', detail: '' });
    const states = {
      container: { status: 'Looking for the SDK container…' },
      samples: loading('Samples'),
      tutorials: loading('Tutorials'),
      auth: loading('Developer Portal'),
      devkit: loading('DevKit Sync'),
    };
    const render = () => panelHtml(view.webview, this.mediaRoot, this.vscode, states);
    if (!this.rendered) {
      view.webview.html = render();
      this.rendered = true;
    } else {
      void view.webview.postMessage({ command: 'panelStatus', html: render() });
    }
    await loadStatuses({
      container: this.services.getContainerState,
      samples: this.services.getSamplesState,
      tutorials: this.services.getTutorialsState,
      auth: this.services.getAuthState,
      devkit: this.services.getDevKitSyncState,
    }, (key, state) => {
      if (this.disposed || this.refreshGeneration !== generation || this.webviewView !== view) {
        return;
      }
      states[key] = state;
      void view.webview.postMessage({ command: 'panelStatus', html: render(), section: key });
    });
  }

  dispose() {
    this.disposed = true;
    this.disposables.forEach((d) => d.dispose());
  }
}

module.exports = { VIEW_ID, SECTIONS, PalettePanelProvider };
