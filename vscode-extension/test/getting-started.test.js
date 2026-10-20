const test = require('node:test');
const assert = require('node:assert/strict');
const { registerGettingStarted, GETTING_STARTED_URL } = require('../src/getting-started');

function fixture({ tabs = [], preference, web = true, fail = false } = {}) {
  const state = new Map();
  const calls = [];
  const commands = new Map();
  const context = {
    subscriptions: [],
    globalState: { get: key => state.get(key), update: async (key, value) => state.set(key, value) }
  };
  const vscode = {
    UIKind: { Web: 2 }, env: { uiKind: web ? 2 : 1 },
    workspace: { getConfiguration: () => ({ inspect: () => ({ globalValue: preference }) }) },
    window: { tabGroups: { all: [{ tabs }] } },
    commands: {
      registerCommand: (id, fn) => { commands.set(id, fn); return { dispose() {} }; },
      executeCommand: async (...args) => { calls.push(args); if (fail) throw Error('browser unavailable'); }
    }
  };
  return { vscode, context, calls, commands, state };
}

test('first browser launch opens the requested page once across activations', async () => {
  const f = fixture();
  await registerGettingStarted(f.vscode, f.context);
  await registerGettingStarted(f.vscode, f.context);
  assert.deepEqual(f.calls, [['simpleBrowser.show', GETTING_STARTED_URL]]);
  await f.commands.get('simaNeat.gettingStarted')();
  assert.equal(f.calls.length, 2);
});

test('restored tabs suppress onboarding even if later closed', async () => {
  const f = fixture({ tabs: [{}] });
  await registerGettingStarted(f.vscode, f.context);
  f.vscode.window.tabGroups.all[0].tabs = [];
  await registerGettingStarted(f.vscode, f.context);
  assert.deepEqual(f.calls, []);
});

test('explicit startup preferences and desktop sessions are respected', async () => {
  for (const options of [{ preference: 'none' }, { preference: 'welcomePage' }, { web: false }]) {
    const f = fixture(options);
    await registerGettingStarted(f.vscode, f.context);
    assert.deepEqual(f.calls, []);
  }
});

test('browser command failure does not mark onboarding complete or break activation', async () => {
  const f = fixture({ fail: true });
  await registerGettingStarted(f.vscode, f.context);
  assert.equal(f.state.size, 0);
  await registerGettingStarted(f.vscode, f.context);
  assert.equal(f.calls.length, 2);
});
