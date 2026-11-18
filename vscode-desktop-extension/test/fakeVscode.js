'use strict';

// A small stand-in for the `vscode` module: enough of the API for the host status
// (side bar view, status bar item) and the Set up SDK page to run under Node.js.
// It records what the extension asked VS Code to do, so tests can check it.

const path = require('path');

class EventEmitter {
  constructor() {
    this.listeners = new Set();
    this.event = (listener) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
  }

  fire(value) {
    [...this.listeners].forEach((listener) => listener(value));
  }

  dispose() {
    this.listeners.clear();
  }
}

class Uri {
  constructor(fsPath) {
    this.fsPath = fsPath;
    this.scheme = 'file';
  }

  toString() {
    return `vscode-resource:${this.fsPath}`;
  }

  static file(fsPath) {
    return new Uri(fsPath);
  }

  static joinPath(base, ...parts) {
    return new Uri(path.join(base.fsPath, ...parts));
  }

  static parse(value) {
    const uri = new Uri(value);
    uri.scheme = value.split(':')[0];
    return uri;
  }
}

class ThemeColor {
  constructor(id) {
    this.id = id;
  }
}

/** A webview: html, messages from the extension (posted) and to it (send). */
function createWebview() {
  const received = new EventEmitter();
  return {
    html: '',
    options: {},
    cspSource: 'vscode-csp',
    posted: [],
    asWebviewUri: (uri) => uri,
    postMessage(message) {
      // A copy, as a real webview gets: the extension keeps changing its state object.
      this.posted.push(JSON.parse(JSON.stringify(message)));
      return Promise.resolve(true);
    },
    onDidReceiveMessage: received.event,
    /** Delivers a message from the page to the extension. */
    send: (message) => received.fire(message),
  };
}

function createFakeVscode({ remoteName, config = {} } = {}) {
  const calls = { commands: [], info: [], warnings: [], errors: [], configUpdates: [], clipboard: [], external: [] };
  const statusItems = [];
  const panels = [];
  const viewProviders = new Map();
  const configChanged = new EventEmitter();
  const settings = { ...config };

  const vscode = {
    EventEmitter,
    Uri,
    ThemeColor,
    StatusBarAlignment: { Left: 1, Right: 2 },
    ViewColumn: { Active: -1, One: 1 },
    ConfigurationTarget: { Global: 1 },
    ProgressLocation: { Notification: 15, Window: 10 },
    env: {
      remoteName,
      appName: 'Visual Studio Code',
      clipboard: { writeText: async (text) => { calls.clipboard.push(text); } },
      openExternal: async (uri) => { calls.external.push(uri); return true; },
    },
    commands: {
      executeCommand: async (...args) => { calls.commands.push(args); },
      registerCommand: () => ({ dispose() {} }),
    },
    extensions: {
      onDidChange: () => ({ dispose() {} }),
      getExtension: () => undefined,
    },
    workspace: {
      getConfiguration: (section) => ({
        get: (key, fallback) => {
          const full = `${section}.${key}`;
          return Object.prototype.hasOwnProperty.call(settings, full) ? settings[full] : fallback;
        },
        update: async (key, value) => {
          const full = `${section}.${key}`;
          settings[full] = value;
          calls.configUpdates.push([full, value]);
          configChanged.fire({ affectsConfiguration: (s) => full.startsWith(s) });
        },
      }),
      onDidChangeConfiguration: configChanged.event,
      createFileSystemWatcher: () => ({
        onDidCreate() {}, onDidChange() {}, onDidDelete() {}, dispose() {},
      }),
    },
    RelativePattern: class RelativePattern {
      constructor(base, pattern) {
        this.base = base;
        this.pattern = pattern;
      }
    },
    window: {
      createStatusBarItem(alignment, priority) {
        const item = {
          alignment, priority, text: '', tooltip: '', command: undefined, color: undefined, visible: false,
          show() { this.visible = true; },
          hide() { this.visible = false; },
          dispose() { this.visible = false; },
        };
        statusItems.push(item);
        return item;
      },
      registerWebviewViewProvider(id, provider) {
        viewProviders.set(id, provider);
        return { dispose() {} };
      },
      createWebviewPanel(viewType, title, column, options) {
        const disposed = new EventEmitter();
        const panel = {
          viewType, title, column, options, visible: true, revealed: 0,
          webview: createWebview(),
          reveal() { this.revealed += 1; },
          onDidDispose: disposed.event,
          dispose() { disposed.fire(); },
        };
        panels.push(panel);
        return panel;
      },
      showInformationMessage: async (...args) => { calls.info.push(args); return undefined; },
      showWarningMessage: async (...args) => { calls.warnings.push(args); return undefined; },
      showErrorMessage: async (...args) => { calls.errors.push(args); return undefined; },
      showInputBox: async () => undefined,
      showOpenDialog: async () => undefined,
      withProgress: async (options, task) => task({ report() {} }),
    },
  };

  /** Opens a registered webview view, as VS Code does when the side bar shows it. */
  function resolveView(id) {
    const provider = viewProviders.get(id);
    if (!provider) {
      throw new Error(`No view provider registered for ${id}`);
    }
    const disposed = new EventEmitter();
    const view = { webview: createWebview(), onDidDispose: disposed.event, dispose: () => disposed.fire() };
    provider.resolveWebviewView(view);
    return view;
  }

  return { vscode, calls, statusItems, panels, viewProviders, settings, resolveView };
}

/** A fake extension context with an in-memory globalState. */
function fakeContext(extensionPath) {
  const store = new Map();
  return {
    extensionUri: Uri.file(extensionPath),
    extensionPath,
    subscriptions: [],
    globalState: {
      get: (key, fallback) => (store.has(key) ? store.get(key) : fallback),
      update: async (key, value) => {
        if (value === undefined) {
          store.delete(key);
        } else {
          store.set(key, value);
        }
      },
    },
    environmentVariableCollection: { clear() {}, prepend() {}, description: '' },
  };
}

/** Lets pending promise callbacks and timers of the given length run. */
const settle = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

module.exports = { createFakeVscode, fakeContext, settle, EventEmitter, Uri };
