'use strict';

// Setup status on this computer (the host): the "Neat SDK" side bar view and the
// "SDK" status bar item. Both show the same thing: not set up, setting up
// (with download progress), or running.

const vscode = require('vscode');
const crypto = require('crypto');
const sdk = require('./sdk');

const VIEW_ID = 'simaNeatTools.host';

let status = { kind: 'none' };
let statusItem;
let view;
let extensionUri;
// Platform version per container name, read once from the container's labels.
const platforms = new Map();
const changed = new vscode.EventEmitter();

/** "ghcr.io/sima-neat/sdk:v3.0.0.1" → "v3.0.0.1". */
function versionFromImage(image) {
  const match = /:([^:/@]+)$/.exec(image || '');
  return match ? match[1] : '';
}

/**
 * kind: 'none' | 'progress' | 'running'
 * progress: { step, total, downloading, failed, pct, version }
 * running: { version, container }
 */
function set(next) {
  if (next.kind === 'running' && next.container) {
    const known = platforms.get(next.container);
    next = { ...next, platform: known || next.platform || '' };
    if (known === undefined) {
      platforms.set(next.container, '');
      sdk.platformVersion(next.container).then((platform) => {
        platforms.set(next.container, platform);
        if (platform && status.kind === 'running' && status.container === next.container) {
          set(status);
        }
      }, () => {});
    }
  }
  status = next;
  updateStatusBar();
  changed.fire();
}

function get() {
  return status;
}

function updateStatusBar() {
  if (!statusItem) {
    return;
  }
  statusItem.color = undefined;
  statusItem.backgroundColor = undefined;
  if (status.kind === 'progress' && status.downloading) {
    statusItem.text = `$(loading~spin) SDK ${status.pct}%`;
    statusItem.tooltip = `Downloading SDK ${status.version || ''} · click to open setup`.replace('  ', ' ');
    statusItem.command = 'simaNeat.openSetup';
    statusItem.show();
  } else if (status.kind === 'progress' && status.failed) {
    statusItem.text = '$(warning) SDK download failed';
    statusItem.tooltip = 'Click to open setup';
    statusItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    statusItem.command = 'simaNeat.openSetup';
    statusItem.show();
  } else if (status.kind === 'running') {
    statusItem.text = '$(vm) Neat SDK: running';
    statusItem.tooltip = `SDK ${status.version || ''} · container ${status.container || ''}${status.platform ? ` · Platform ${status.platform}` : ''}`;
    statusItem.command = 'simaNeat.openSdkInVsCode';
    statusItem.show();
  } else {
    statusItem.hide();
  }
}

// The "Neat SDK" section is drawn inside the view (see package.json), so it collapses here.
let collapsed = false;

class HostViewProvider {
  resolveWebviewView(webviewView) {
    view = webviewView;
    webviewView.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'media')] };
    const render = () => { webviewView.webview.html = this.html(webviewView.webview); };
    render();
    const sub = changed.event(render);
    webviewView.onDidDispose(() => { sub.dispose(); view = undefined; });
    webviewView.webview.onDidReceiveMessage((message) => {
      if (message && message.type === 'toggle') {
        collapsed = !collapsed;
        render();
        return;
      }
      if (message && message.type === 'repair') {
        vscode.commands.executeCommand('simaNeat.repair');
        return;
      }
      if (message && message.type === 'action') {
        const command = message.id === 'open' ? 'simaNeat.openSdkInVsCode' : 'simaNeat.openSetup';
        vscode.commands.executeCommand(command);
      }
    });
  }

  html(webview) {
    const nonce = crypto.randomBytes(16).toString('base64');
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    let dot = 'var(--vscode-descriptionForeground)';
    let title = 'SDK not set up';
    let text = 'Sign in, check this computer and download the SDK. About 15 minutes, mostly download.';
    let button = 'Set up SDK';
    let action = 'setup';
    let bar = '';
    if (status.kind === 'progress') {
      dot = 'var(--vscode-editorWarning-foreground)';
      title = 'Setting up';
      button = 'Continue setup';
      if (status.downloading) {
        text = `Downloading SDK ${status.version || ''} · ${status.pct}%`;
        bar = `<div class="bar"><div style="width:${Number(status.pct) || 0}%"></div></div>`;
      } else if (status.failed) {
        text = `SDK download failed at ${status.pct}%`;
      } else {
        text = `Step ${status.step} of ${status.total}`;
      }
    } else if (status.kind === 'running') {
      dot = 'var(--vscode-testing-iconPassed)';
      title = `SDK running${status.version ? ` · ${status.version}` : ''}`;
      text = `Container ${status.container || ''}${status.platform ? ` · Platform ${status.platform}` : ''}`;
      button = 'Open SiMa Neat Studio';
      action = 'open';
    }
    const codicons = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', 'codicons', 'codicon.css'));
    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
<link rel="stylesheet" href="${codicons}">
<style>
  body { margin: 0; padding: 0; color: var(--vscode-foreground); font-family: var(--vscode-font-family); font-size: 13px; }
  .section { height: 22px; display: flex; align-items: center; gap: 2px; padding: 0 8px 0 2px; font-size: 11px; font-weight: 700; text-transform: uppercase; border-top: 1px solid var(--vscode-sideBarSectionHeader-border, transparent); cursor: pointer; user-select: none; }
  .section .codicon { font-size: 14px; }
  .wrap { padding: 10px 20px 12px; display: flex; flex-direction: column; gap: 10px; line-height: 1.4; }
  .head { display: flex; align-items: center; gap: 8px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .title { font-weight: 600; }
  .text { color: var(--vscode-descriptionForeground); }
  .bar { height: 3px; border-radius: 2px; background: var(--vscode-input-background); overflow: hidden; }
  .bar > div { height: 100%; background: var(--vscode-progressBar-background); }
  button { width: 100%; height: 26px; border: 1px solid var(--vscode-button-border, transparent); border-radius: 2px; background: var(--vscode-button-background); color: var(--vscode-button-foreground); font-family: inherit; font-size: 13px; cursor: pointer; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  .foot { font-size: 12px; color: var(--vscode-descriptionForeground); }
  .repair { display: flex; align-items: center; gap: 6px; width: max-content; font-size: 12px; color: var(--vscode-textLink-foreground); text-decoration: none; cursor: pointer; }
  .repair:hover { text-decoration: underline; }
  .repair .codicon { font-size: 13px; }
</style></head>
<body><div class="section" id="section" role="button" aria-expanded="${!collapsed}"><i class="codicon codicon-chevron-${collapsed ? 'right' : 'down'}"></i>Neat SDK</div>
<div class="wrap"${collapsed ? ' hidden' : ''}>
  <div class="head"><span class="dot" style="background:${dot}"></span><span class="title">${esc(title)}</span></div>
  <span class="text">${esc(text)}</span>
  ${bar}
  <button id="go">${esc(button)}</button>
  <span class="foot">Catalog, Devices and Insight are inside the SDK.</span>
  <a href="#" class="repair" id="repair" title="Reinstalls sima-cli and recreates the SDK container. Your workspace folder is kept."><i class="codicon codicon-tools"></i>Repair SiMa Neat Studio…</a>
</div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  document.getElementById('section').addEventListener('click', () => vscode.postMessage({ type: 'toggle' }));
  document.getElementById('go').addEventListener('click', () => vscode.postMessage({ type: 'action', id: '${action}' }));
  document.getElementById('repair').addEventListener('click', (event) => { event.preventDefault(); vscode.postMessage({ type: 'repair' }); });
</script>
</body></html>`;
  }
}

/** On start, before the setup page has run: is an SDK container already running? */
async function probe() {
  try {
    const containers = await sdk.listAllSdkContainers();
    const running = containers.find((c) => c.state === 'running');
    if (running && status.kind === 'none') {
      set({ kind: 'running', version: versionFromImage(running.image), container: running.name });
    }
  } catch {
    // Docker missing or not running: the view keeps "SDK not set up".
  }
}

function register(context) {
  // The setup status belongs to this computer; inside the SDK container the window shows other views.
  if (vscode.env.remoteName) {
    return;
  }
  extensionUri = context.extensionUri;
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, -100);
  statusItem.name = 'Neat SDK';
  context.subscriptions.push(
    statusItem,
    changed,
    vscode.window.registerWebviewViewProvider(VIEW_ID, new HostViewProvider()),
  );
  updateStatusBar();
  void probe();
}

module.exports = { register, set, get, versionFromImage, VIEW_ID, isVisible: () => Boolean(view) };
