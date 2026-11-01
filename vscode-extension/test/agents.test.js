const test = require("node:test");
const assert = require("node:assert/strict");
const { createAgentManager } = require("../src/agents");
function harness(execute) {
  const installed = new Map(),
    calls = [],
    updates = [],
    changes = new Set();
  const vscode = {
    extensions: {
      getExtension: (id) => installed.get(id),
      onDidChange: (fn) => {
        changes.add(fn);
        return { dispose: () => changes.delete(fn) };
      },
    },
    commands: {
      executeCommand: async (...args) => {
        calls.push(args);
        return execute?.(...args);
      },
    },
  };
  const unpinned = new Set();
  const targets = { codex: { id: "openai.chatgpt", version: "1.2.3" }, claude: { id: "anthropic.claude-code", version: "2.3.4" } };
  const catalog = { snapshot: () => ({ available: true, components: targets }),
    refresh: async () => {}, subscribe: () => ({ dispose() {} }),
    readInstalledProfile: async () => {},
    isPinned: target => !unpinned.has(target.id),
    verifyInstalled: async target => { unpinned.delete(target.id); },
    artifact: async key => ({ file: `/verified/${key}.vsix`, target: targets[key] }) };
  vscode.Uri = { file: p => ({ fsPath: p }) };
  const manager = createAgentManager(vscode, catalog);
  const subscription = manager.subscribe((value) => updates.push(value));
  return { manager, installed, calls, updates, changes, subscription, unpinned, catalog };
}
for (const [key, id, command] of [
  ["codex", "openai.chatgpt", "chatgpt.openSidebar"],
  ["claude", "anthropic.claude-code", "claude-vscode.sidebar.open"],
]) {
  test(`${key} installs the allowlisted extension and opens its verified command`, async () => {
    let activated = 0;
    const h = harness(async (name) => {
      if (name === "workbench.extensions.installExtension")
        h.installed.set(id, { packageJSON: {version: key === "codex" ? "1.2.3" : "2.3.4"}, activate: async () => activated++ });
    });
    assert.equal(h.manager.snapshot()[key].status, "available");
    await h.manager.action(key, "install");
    assert.deepEqual(h.calls[0], [
      "workbench.extensions.installExtension",
      { fsPath: `/verified/${key}.vsix` },
      { enable: true, donotSync: true },
    ]);
    assert.equal(h.updates[0][key].status, "installing");
    assert.equal(h.manager.snapshot()[key].status, "installed");
    await h.manager.action(key, "install");
    assert.equal(h.calls.length, 1);
    await h.manager.action(key, "open");
    assert.equal(activated, 1);
    assert.deepEqual(h.calls[1], [command]);
  });
}
test("duplicate installs are ignored while the other agent stays available", async () => {
  let finish;
  const h = harness(() => new Promise((resolve) => (finish = resolve)));
  const first = h.manager.action("codex", "install");
  await new Promise(resolve => setImmediate(resolve));
  await h.manager.action("codex", "install");
  assert.equal(h.calls.length, 1);
  assert.equal(h.manager.snapshot().claude.busy, false);
  finish();
  await first;
  assert.equal(h.manager.snapshot().codex.status, "reload");
});
test("installation error is retryable and private subprocess details never reach the page", async () => {
  let fail = true;
  const h = harness(() => {
    if (fail) throw Error("secret-token");
  });
  await h.manager.action("claude", "install");
  assert.equal(h.manager.snapshot().claude.status, "available");
  assert.match(
    h.manager.snapshot().claude.error,
    /Installation did not finish/,
  );
  assert.doesNotMatch(JSON.stringify(h.updates), /secret-token/);
  fail = false;
  await h.manager.action("claude", "install");
  assert.equal(h.manager.snapshot().claude.error, "");
  await h.manager.action("claude", "reload");
  assert.deepEqual(h.calls.at(-1), ["workbench.action.reloadWindow"]);
});
test("untrusted provider/action messages cannot choose commands or install URLs", async () => {
  const h = harness();
  for (const key of [
    "__proto__",
    "constructor",
    "other",
    "https://example.com/evil.vsix",
    null,
  ])
    await h.manager.action(key, "install");
  for (const action of ["workbench.action.terminal.new", "uninstall", null])
    await h.manager.action("codex", action);
  await h.manager.action("codex", "reload");
  assert.equal(h.calls.length, 0);
});
test("extension changes update status and listeners are removed on disposal", async () => {
  const h = harness();
  h.installed.set("openai.chatgpt", {packageJSON: {version: "1.2.3"}});
  for (const change of h.changes) await change();
  assert.equal(h.updates.at(-1).codex.status, "installed");
  h.installed.delete("openai.chatgpt");
  for (const change of h.changes) await change();
  assert.equal(h.updates.at(-1).codex.status, "available");
  h.subscription.dispose();
  assert.equal(h.changes.size, 0);
});
test("open failures preserve installed state and manage opens the correct extension", async () => {
  const h = harness();
  h.installed.set("openai.chatgpt", {
    packageJSON: {version: "1.2.3"},
    activate: async () => {
      throw Error("failed");
    },
  });
  await h.manager.action("codex", "open");
  assert.equal(h.manager.snapshot().codex.status, "installed");
  assert.match(h.manager.snapshot().codex.error, /Unable to open/);
  await h.manager.action("codex", "manage");
  assert.equal(h.manager.snapshot().codex.error, "");
  assert.equal(h.updates.at(-1).codex.error, "");
  assert.deepEqual(h.calls.at(-1), [
    "workbench.extensions.action.showExtensionsWithIds",
    ["openai.chatgpt"],
  ]);
});

test("manage remains usable during an install without releasing its duplicate guard", async () => {
  let finish;
  const h = harness((command) => command === "workbench.extensions.installExtension"
    ? new Promise(resolve => { finish = resolve; }) : undefined);
  const install = h.manager.action("codex", "install");
  await new Promise(resolve => setImmediate(resolve));
  await h.manager.action("codex", "manage");
  assert.deepEqual(h.calls.at(-1), ["workbench.extensions.action.showExtensionsWithIds", ["openai.chatgpt"]]);
  assert.equal(h.manager.snapshot().codex.status, "installing");
  await h.manager.action("codex", "install");
  assert.equal(h.calls.length, 2);
  finish();
  await install;
});

test("successful install clears a concurrent management error and publishes installed state", async () => {
  let finish;
  const h = harness((command) => {
    if (command === "workbench.extensions.installExtension")
      return new Promise(resolve => { finish = resolve; });
    throw Error("management failed");
  });
  const install = h.manager.action("codex", "install");
  await new Promise(resolve => setImmediate(resolve));
  await h.manager.action("codex", "manage");
  assert.match(h.updates.at(-1).codex.error, /Unable to open Extensions/);
  assert.equal(h.manager.snapshot().codex.status, "installing");
  h.installed.set("openai.chatgpt", {packageJSON: {version: "1.2.3"}});
  finish();
  await install;
  assert.equal(h.updates.at(-1).codex.status, "installed");
  assert.equal(h.updates.at(-1).codex.error, "");
  assert.equal(h.updates.at(-1).codex.busy, false);
});

test("an existing incompatible version offers a pinned repair and cannot be opened",async()=>{
 const h=harness();
 h.installed.set('openai.chatgpt',{packageJSON:{version:'9.9.9'},activate:()=>assert.fail('must not activate an incompatible version')});
 assert.equal(h.manager.snapshot().codex.status,'update');
 await h.manager.action('codex','open');assert.equal(h.calls.length,0);
 await h.manager.action('codex','install');
 assert.equal(h.calls[0][1].fsPath,'/verified/codex.vsix');
 assert.equal(h.manager.snapshot().codex.status,'reload');
});

test("a matching gallery version offers repair and is reinstalled to establish its pin", async () => {
  const h = harness();
  h.installed.set("openai.chatgpt", {packageJSON: {version: "1.2.3"}});
  h.unpinned.add("openai.chatgpt");
  assert.equal(h.manager.snapshot().codex.status, "update");
  assert.equal(h.manager.snapshot().codex.unpinned, true);
  await h.manager.action("codex", "install");
  assert.equal(h.calls[0][1].fsPath, "/verified/codex.vsix");
  assert.equal(h.manager.snapshot().codex.status, "installed");
  await h.manager.action("codex", "install");
  assert.equal(h.calls.length, 1);
});

test("offline policy still opens installed agents and missing packages give a reconnect action", async () => {
  const h = harness();
  const snapshot = h.catalog.snapshot;
  h.catalog.snapshot = () => ({...snapshot(), source: "offline"});
  let activated = false;
  h.installed.set("openai.chatgpt", {packageJSON: {version: "1.2.3"}, activate: async () => {activated = true;}});
  assert.equal(h.manager.snapshot().codex.offline, true);
  assert.equal(h.manager.snapshot().codex.status, "installed");
  await h.manager.action("codex", "open");
  assert.equal(activated, true);
  assert.deepEqual(h.calls.at(-1), ["chatgpt.openSidebar"]);
  h.catalog.artifact = async () => {throw Object.assign(Error("private details"), {code: "OFFLINE_ARTIFACT_UNAVAILABLE"});};
  await h.manager.action("claude", "install");
  assert.match(h.manager.snapshot().claude.error, /Offline.*not cached.*Reconnect/);
  assert.doesNotMatch(h.manager.snapshot().claude.error, /private details/);
  assert.equal(h.manager.snapshot().claude.busy, false);
  assert.equal(h.calls.length, 1);
});
