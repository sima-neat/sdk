const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { registerGettingStarted } = require("../src/getting-started");
function fixture({ tabs = [], preference, web = true, fail = false } = {}) {
  const state = new Map(),
    commands = new Map(),
    panels = [],
    actions = [];
  const uri = (p) => ({ fsPath: p, toString: () => p });
  const context = {
    extensionUri: uri(path.resolve(__dirname, "..")),
    subscriptions: [],
    globalState: {
      get: (key) => state.get(key),
      update: async (key, v) => state.set(key, v),
    },
  };
  const vscode = {
    UIKind: { Web: 2 },
    ViewColumn: { One: 1 },
    env: { uiKind: web ? 2 : 1, openExternal: async (u) => actions.push(u) },
    Uri: {
      joinPath: (base, ...parts) => uri(path.join(base.fsPath, ...parts)),
      parse: uri,
    },
    workspace: {
      getConfiguration: () => ({
        inspect: () => ({ globalValue: preference }),
      }),
    },
    commands: {
      registerCommand: (id, fn) => {
        commands.set(id, fn);
        return { dispose() {} };
      },
      executeCommand: async (id) => actions.push(id),
    },
    window: {
      registerWebviewPanelSerializer: (id, serializer) => {
        context.serializer = serializer;
        return { dispose() {} };
      },
      tabGroups: { all: [{ tabs }] },
      showErrorMessage: () => {},
      createWebviewPanel: () => {
        if (fail) throw Error("unavailable");
        const p = {
          reveal() {},
          dispose() {
            this.disposer?.();
          },
          onDidDispose(fn) {
            this.disposer = fn;
          },
          webview: {
            asWebviewUri: (u) => u,
            cspSource: "test-source",
            onDidReceiveMessage(fn) {
              p.receive = fn;
              return { dispose() {} };
            },
            postMessage: async (m) => {
              p.message = m;
            },
          },
        };
        panels.push(p);
        return p;
      },
    },
  };
  const services = {
    getDevkitConfig: async () => ({}),
    openInsight: async () => actions.push("insight"),
    modelsEnabled: true,
    loadData: async () => ({ sdk: {}, devkit: {}, insight: {} }),
  };
  return { vscode, context, services, state, panels, commands, actions };
}
test("first browser launch opens a local landing page once; command can reopen it", async () => {
  const f = fixture();
  await registerGettingStarted(f.vscode, f.context, f.services);
  assert.equal(f.panels.length, 1);
  assert.match(f.panels[0].webview.html, /Content-Security-Policy/);
  assert.doesNotMatch(
    f.panels[0].webview.html,
    /sdk\.example|v1\.8\.0|B2263|DESIGN PREVIEW/,
  );
  await registerGettingStarted(f.vscode, f.context, f.services);
  assert.equal(f.panels.length, 1);
  await f.commands.get("simaNeat.gettingStarted")();
  assert.equal(f.panels.length, 2);
});
test("restored tabs and explicit preferences suppress automatic onboarding", async () => {
  for (const options of [
    { tabs: [{}] },
    { preference: "none" },
    { preference: "welcomePage" },
    { web: false },
  ]) {
    const f = fixture(options);
    await registerGettingStarted(f.vscode, f.context, f.services);
    assert.equal(f.panels.length, 0);
  }
});
test("failed page creation can retry on subsequent activation", async () => {
  const f = fixture({ fail: true });
  await registerGettingStarted(f.vscode, f.context, f.services);
  assert.equal(f.state.size, 0);
});
test("landing page sends live data and only dispatches allowlisted actions", async () => {
  const f = fixture();
  await registerGettingStarted(f.vscode, f.context, f.services);
  const p = f.panels[0];
  await p.receive({ type: "ready" });
  assert.equal(p.message.type, "data");
  assert.equal(p.message.value.modelsEnabled, true);
  for (const action of [
    "panel",
    "models",
    "insight",
    "apps",
    "docs",
    "workbench.action.terminal.new",
  ])
    await p.receive({ type: "action", action });
  assert.equal(f.actions.length, 5);
  assert.deepEqual(f.actions.slice(0, 3), [
    "simaNeat.showPanel",
    "simaNeat.browseModels",
    "insight",
  ]);
  await f.commands.get("simaNeat.gettingStarted")();
  assert.equal(f.panels.length, 1);
  p.dispose();
  await f.commands.get("simaNeat.gettingStarted")();
  assert.equal(f.panels.length, 2);
});

test("restores the landing tab after a browser reload", async () => {
  const f = fixture();
  await registerGettingStarted(f.vscode, f.context, f.services);
  const panel = f.panels[0];
  panel.dispose();
  await f.context.serializer.deserializeWebviewPanel(panel);
  assert.match(panel.webview.html, /Palette Neat/);
  assert.equal(panel.webview.options.enableScripts, true);
  await panel.receive({ type: "ready" });
  assert.equal(panel.message.type, "data");
});
