const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { registerGettingStarted, workbenchWelcomeLabel } = require("../src/getting-started");
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
    extensions: {
      getExtension: () => undefined,
      onDidChange: () => ({ dispose() {} }),
    },
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
test("empty browser launches open the landing page even with an old onboarding marker", async () => {
  const f = fixture();
  await registerGettingStarted(f.vscode, f.context, f.services);
  assert.equal(f.panels.length, 1);
  assert.match(f.panels[0].webview.html, /Content-Security-Policy/);
  assert.doesNotMatch(
    f.panels[0].webview.html,
    /sdk\.example|v1\.8\.0|B2263|DESIGN PREVIEW/,
  );
  f.state.set("simaNeat.landing.initialized", true);
  await registerGettingStarted(f.vscode, f.context, f.services);
  assert.equal(f.panels.length, 2);
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
  panel.title = "Palette Neat";
  await f.context.serializer.deserializeWebviewPanel(panel);
  assert.equal(panel.title, "Palette SDK");
  assert.match(panel.webview.html, /Palette SDK/);
  assert.equal(panel.webview.options.enableScripts, true);
  await panel.receive({ type: "ready" });
  assert.equal(panel.message.type, "data");
});

test("stock Welcome tab does not suppress first browser onboarding", async () => {
  const f = fixture({ tabs: [{ label: "Welcome", input: undefined }] });
  await registerGettingStarted(f.vscode, f.context, f.services);
  assert.equal(f.panels.length, 1);
  assert.equal(f.state.get("simaNeat.landing.initialized"), undefined);
});
test("Welcome alongside user work or a startup preference stays untouched", async () => {
  for (const options of [
    { tabs: [{ label: "Welcome", input: { uri: "file:///Welcome" } }] },
    { tabs: [{ label: "Welcome" }, { label: "main.py", input: {} }] },
    { tabs: [{ label: "Welcome" }], preference: "welcomePage" },
    { tabs: [{ label: "Welcome" }], preference: "none" },
    { tabs: [{ label: "Other unknown editor" }] },
  ]) {
    const f = fixture(options);
    await registerGettingStarted(f.vscode, f.context, f.services);
    assert.equal(f.panels.length, 0);
  }
});
test("core language pack supplies Welcome without extension localization", async () => {
  const fs = require("fs/promises");
  const os = require("os");
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "neat-nls-"));
  const previous = process.env.VSCODE_NLS_CONFIG;
  try {
    const translationsConfigFile = path.join(dir, "tcf.json");
    const core = path.join(dir, "main.i18n.json");
    await fs.writeFile(translationsConfigFile, JSON.stringify({ vscode: core }));
    await fs.writeFile(core, JSON.stringify({ contents: {
      "vs/workbench/contrib/welcomeGettingStarted/browser/gettingStartedInput": {
        getStarted: "Bienvenue",
      },
    } }));
    for (const config of [
      { languagePack: { translationsConfigFile } },
      { _translationsConfigFile: translationsConfigFile },
    ]) {
      process.env.VSCODE_NLS_CONFIG = JSON.stringify(config);
      assert.equal(await workbenchWelcomeLabel(), "Bienvenue");
      const f = fixture({ tabs: [{ label: "Bienvenue" }] });
      await registerGettingStarted(f.vscode, f.context, f.services);
      assert.equal(f.panels.length, 1);
      const userFile = fixture({ tabs: [{ label: "Bienvenue", input: {} }] });
      await registerGettingStarted(userFile.vscode, userFile.context, userFile.services);
      assert.equal(userFile.panels.length, 0);
    }
    await fs.writeFile(core, JSON.stringify({ contents: {} }));
    assert.equal(await workbenchWelcomeLabel(), "Welcome");
    await fs.writeFile(core, "invalid JSON");
    assert.equal(await workbenchWelcomeLabel(), "Welcome");
    await fs.unlink(core);
    assert.equal(await workbenchWelcomeLabel(), "Welcome");
  } finally {
    if (previous === undefined) delete process.env.VSCODE_NLS_CONFIG;
    else process.env.VSCODE_NLS_CONFIG = previous;
    await fs.rm(dir, { recursive: true, force: true });
  }
});
test("absent or invalid NLS configuration safely uses English", async () => {
  for (const config of ["", "{}", "invalid JSON", "null"]) {
    assert.equal(await workbenchWelcomeLabel(config), "Welcome");
  }
});

test("Apps clone action refreshes workspace availability after cloning", async () => {
  const f = fixture();
  let cloned = false;
  f.services.getAppsState = async () => ({
    disabled: cloned,
    status: cloned ? "Samples are available under" : "Clone SiMa Neat samples into this workspace.",
    detail: "apps",
  });
  f.services.cloneApps = async () => { cloned = true; };
  await registerGettingStarted(f.vscode, f.context, f.services);
  const page = f.panels[0];
  await page.receive({ type: "ready" });
  assert.equal(page.message.value.appsState.disabled, false);
  await page.receive({ type: "action", action: "cloneApps", command: "ignored" });
  assert.equal(cloned, true);
  assert.equal(page.message.type, "data");
  assert.equal(page.message.value.appsState.disabled, true);
  assert.equal(page.message.value.appsState.detail, "apps");
});

test("DevKit Connect only opens the fixed shell action after a connected status", async () => {
  const f = fixture();
  const commands = [];
  f.vscode.window.createTerminal = (name) => {
    assert.equal(name, "DevKit");
    return { show() {}, sendText: (command) => commands.push(command) };
  };
  await registerGettingStarted(f.vscode, f.context, f.services);
  const page = f.panels[0];
  await page.receive({ type: "action", action: "devkit" });
  assert.deepEqual(commands, []);
  f.services.loadData = async () => ({ sdk: {}, devkit: { state: "connected" }, insight: {} });
  await page.receive({ type: "ready" });
  await page.receive({ type: "action", action: "devkit", command: "ignored" });
  assert.deepEqual(commands, ["dk shell"]);
  f.services.loadData = async () => { throw Error("offline"); };
  await page.receive({ type: "refresh" });
  await page.receive({ type: "action", action: "devkit" });
  assert.deepEqual(commands, ["dk shell"]);
});
