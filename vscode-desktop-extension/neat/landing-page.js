'use strict';

// The SDK's Getting Started page (landing-page.js in the SDK extension), run
// from this computer. Data comes from the current SDK container. Coding agents
// install from the Marketplace into this VS Code, instead of the SDK's
// qualified-version catalog, which needs code-server's own version files.

const fs = require('fs/promises');
const crypto = require('crypto');

const VIEW_TYPE = 'simaNeatTools.landing';

// Identifiers and commands come from the publishers' extension manifests.
// Never accept an extension ID, URI, or command supplied by the webview.
const AGENTS = Object.freeze({
  codex: { id: 'openai.chatgpt', command: 'chatgpt.openSidebar' },
  claude: { id: 'anthropic.claude-code', command: 'claude-vscode.sidebar.open' },
});

function escape(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

async function landingHtml(vscode, context, webview) {
  const base = vscode.Uri.joinPath(context.extensionUri, 'media', 'neat');
  const asset = (...parts) => escape(webview.asWebviewUri(vscode.Uri.joinPath(base, ...parts)).toString());
  const nonce = crypto.randomBytes(24).toString('hex');
  const body = (await fs.readFile(vscode.Uri.joinPath(base, 'landing', 'landing.html').fsPath, 'utf8'))
    .replace('{{LOGO}}', asset('sima-logo.png'));
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource}; font-src ${webview.cspSource}; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';"><title>Palette SDK</title><link rel="stylesheet" href="${asset('landing', 'landing.css')}"></head><body>${body}<script nonce="${nonce}" src="${asset('landing', 'landing.js')}"></script></body></html>`;
}

/** Install and open Codex and Claude Code from the Marketplace, in this VS Code. */
function createAgentManager(vscode) {
  const pending = new Map();
  const errors = new Map();
  const listeners = new Set();
  const snapshot = () => Object.fromEntries(Object.entries(AGENTS).map(([key, agent]) => {
    const extension = vscode.extensions.getExtension(agent.id);
    return [key, {
      busy: pending.has(key),
      installedVersion: extension && extension.packageJSON && extension.packageJSON.version,
      status: pending.get(key) === 'install' ? 'installing' : extension ? 'installed' : 'available',
      error: errors.get(key) || '',
    }];
  }));
  const notify = () => listeners.forEach((listener) => listener(snapshot()));

  async function action(key, name) {
    if (!Object.hasOwn(AGENTS, key) || !['install', 'open', 'reload', 'manage'].includes(name)) {
      return;
    }
    const agent = AGENTS[key];
    if (name === 'manage') {
      await vscode.commands.executeCommand('workbench.extensions.action.showExtensionsWithIds', [agent.id]);
      return;
    }
    if (pending.has(key)) {
      return;
    }
    errors.delete(key);
    pending.set(key, name);
    notify();
    try {
      if (name === 'install') {
        await vscode.commands.executeCommand('workbench.extensions.installExtension', agent.id);
      } else if (name === 'open') {
        await vscode.commands.executeCommand(agent.command);
      } else if (name === 'reload') {
        await vscode.commands.executeCommand('workbench.action.reloadWindow');
      }
    } catch {
      errors.set(key, name === 'install'
        ? 'Installation did not finish. Check your connection and editor notifications, then retry or use Manage in Extensions.'
        : 'Unable to open the extension. Check that it is enabled in Extensions, or reload the editor and try again.');
    } finally {
      pending.delete(key);
      notify();
    }
  }

  return {
    snapshot,
    action,
    subscribe(listener) {
      listeners.add(listener);
      const changed = vscode.extensions.onDidChange(() => listener(snapshot()));
      return { dispose() { listeners.delete(listener); changed.dispose(); } };
    },
  };
}

// The page shows this where the SDK's qualified agent versions would be.
const COMPONENTS_NOTE = Object.freeze({
  available: false,
  error: 'Coding agents install the latest Marketplace version into this VS Code.',
});

function createLandingPage(vscode, context, services) {
  let panel;
  const agents = createAgentManager(vscode);
  return async function open(restored) {
    if (panel && !restored) {
      panel.reveal();
      return;
    }
    const mediaRoot = vscode.Uri.joinPath(context.extensionUri, 'media', 'neat');
    const current = restored || vscode.window.createWebviewPanel(VIEW_TYPE, 'Palette SDK', vscode.ViewColumn.One, {
      enableScripts: true,
      localResourceRoots: [mediaRoot],
      retainContextWhenHidden: true,
    });
    current.title = 'Palette SDK';
    if (restored) {
      current.webview.options = { enableScripts: true, localResourceRoots: [mediaRoot] };
    }
    panel = current;
    let disposed = false;
    let busy = false;
    let devkitConnected = false;
    let cloningApps = false;
    let warnedNoContainer = false;
    const refresh = async () => {
      if (busy || disposed) {
        return;
      }
      busy = true;
      try {
        const value = await services.loadData();
        const appsState = await services.getAppsState();
        devkitConnected = value.devkit && value.devkit.state === 'connected';
        current.title = `Palette SDK · ${value.containerName}`;
        if (!disposed) {
          await current.webview.postMessage({ type: 'data', value: { ...value, appsState, modelsEnabled: services.modelsEnabled } });
        }
      } catch (error) {
        devkitConnected = false;
        if (!disposed) {
          await current.webview.postMessage({ type: 'error' });
        }
        if (error.code === 'NO_CONTAINER' && !warnedNoContainer) {
          warnedNoContainer = true;
          const choice = await vscode.window.showWarningMessage(error.message, 'Open Neat Setup');
          if (choice) {
            await vscode.commands.executeCommand('simaNeat.openSetup');
          }
        }
      } finally {
        busy = false;
      }
    };
    const sendAgents = (value) => {
      if (!disposed) {
        void current.webview.postMessage({ type: 'agents', value });
      }
    };
    const agentChanges = agents.subscribe(sendAgents);
    const sendRegistryState = (value) => {
      if (!disposed) {
        void current.webview.postMessage({ type: 'registryState', value });
      }
    };
    const registryChanges = services.registryState.subscribe(sendRegistryState);
    const receive = current.webview.onDidReceiveMessage(async (message) => {
      if (message && message.type === 'agents-ready') {
        sendAgents(agents.snapshot());
        void current.webview.postMessage({ type: 'components', value: COMPONENTS_NOTE });
        return;
      }
      if (message && message.type === 'agent') {
        await agents.action(message.agent, message.action);
        return;
      }
      if (message && (message.type === 'ready' || message.type === 'refresh')) {
        sendRegistryState(services.registryState.snapshot());
        void services.registryState.refresh();
        await refresh();
        return;
      }
      if (!message || message.type !== 'action') {
        return;
      }
      // Actions carry identifiers only. Never execute commands or open arbitrary
      // URLs supplied by the webview or by device metadata.
      try {
        switch (message.action) {
          case 'panel':
            await vscode.commands.executeCommand('simaNeat.openPalettePanel');
            break;
          case 'devkit':
            if (!devkitConnected) {
              vscode.window.showErrorMessage('Connect a DevKit, then refresh before opening a shell.');
              break;
            }
            await services.openDevKitShell();
            break;
          case 'cloneApps':
            if (cloningApps) {
              break;
            }
            cloningApps = true;
            await current.webview.postMessage({ type: 'appsClone', busy: true });
            try {
              await services.cloneApps();
            } finally {
              cloningApps = false;
              await current.webview.postMessage({ type: 'appsClone', busy: false });
              await refresh();
            }
            break;
          case 'models':
            await vscode.commands.executeCommand('simaNeat.browseModelRegistry');
            break;
          case 'insight':
            await services.openInsight();
            break;
          case 'apps':
            await vscode.env.openExternal(vscode.Uri.parse('https://github.com/sima-neat/apps'));
            break;
          case 'docs':
            await vscode.env.openExternal(vscode.Uri.parse('https://developer.sima.ai/software/getting-started/'));
            break;
          default:
            break;
        }
      } catch (error) {
        vscode.window.showErrorMessage(error.message || 'Unable to open the requested Neat tool. Please try again.');
      }
    });
    current.onDidDispose(() => {
      disposed = true;
      receive.dispose();
      agentChanges.dispose();
      registryChanges.dispose();
      if (panel === current) {
        panel = undefined;
      }
    });
    context.subscriptions.push(current);
    try {
      current.webview.html = await landingHtml(vscode, context, current.webview);
    } catch (error) {
      current.dispose();
      throw error;
    }
  };
}

module.exports = { VIEW_TYPE, createLandingPage };
