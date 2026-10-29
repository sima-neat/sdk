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
  const manager = createAgentManager(vscode);
  const subscription = manager.subscribe((value) => updates.push(value));
  return { manager, installed, calls, updates, changes, subscription };
}
for (const [key, id, command] of [
  ["codex", "openai.chatgpt", "chatgpt.openSidebar"],
  ["claude", "anthropic.claude-code", "claude-vscode.sidebar.open"],
]) {
  test(`${key} installs the allowlisted extension and opens its verified command`, async () => {
    let activated = 0;
    const h = harness(async (name) => {
      if (name === "workbench.extensions.installExtension")
        h.installed.set(id, { activate: async () => activated++ });
    });
    assert.equal(h.manager.snapshot()[key].status, "available");
    await h.manager.action(key, "install");
    assert.deepEqual(h.calls[0], [
      "workbench.extensions.installExtension",
      id,
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
  h.installed.set("openai.chatgpt", {});
  for (const change of h.changes) change();
  assert.equal(h.updates.at(-1).codex.status, "installed");
  h.installed.delete("openai.chatgpt");
  for (const change of h.changes) change();
  assert.equal(h.updates.at(-1).codex.status, "available");
  h.subscription.dispose();
  assert.equal(h.changes.size, 0);
});
test("open failures preserve installed state and manage opens the correct extension", async () => {
  const h = harness();
  h.installed.set("openai.chatgpt", {
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
  await h.manager.action("codex", "manage");
  assert.match(h.updates.at(-1).codex.error, /Unable to open Extensions/);
  assert.equal(h.manager.snapshot().codex.status, "installing");
  h.installed.set("openai.chatgpt", {});
  finish();
  await install;
  assert.equal(h.updates.at(-1).codex.status, "installed");
  assert.equal(h.updates.at(-1).codex.error, "");
  assert.equal(h.updates.at(-1).codex.busy, false);
});
