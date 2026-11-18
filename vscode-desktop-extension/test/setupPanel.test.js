'use strict';

// The Set up SDK page on the extension side (setupPanel.js): its tab, "Sign in to SiMa"
// without a terminal (installing sima-cli first when it's missing), and what it tells
// the "Neat SDK" side bar and the status bar (step, download percentage, running SDK).

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { ROOT, requireWithVscode } = require('./helpers');
const { createFakeVscode, fakeContext, settle, EventEmitter } = require('./fakeVscode');

const IMAGE = 'ghcr.io/sima-neat/sdk:v3.0.0.1';

/** A run the page can await and cancel, finished by the test. */
function controllableRun() {
  let finish;
  const run = {
    cancelled: 0,
    done: new Promise((resolve) => { finish = resolve; }),
    cancel() { run.cancelled += 1; },
    finish: (result) => finish(result),
  };
  return run;
}

/**
 * Loads setupPanel.js afresh with a fake vscode, a fake extension API and stubbed
 * Docker / registry calls, and opens the page.
 */
function openPage({ cli = { file: '/home/me/.sima-cli/.venv/bin/sima-cli', version: '0.0.40' }, login = { loggedIn: false }, containers = [], imagePresent = false } = {}) {
  for (const key of Object.keys(require.cache)) {
    if (key.startsWith(ROOT) && !key.includes(`${path.sep}test${path.sep}`) && !key.includes('node_modules')) {
      delete require.cache[key];
    }
  }
  const fake = createFakeVscode();
  const sdk = requireWithVscode(path.join(ROOT, 'sdk.js'), fake.vscode);
  const pulls = [];
  const layerSizeCalls = [];
  Object.assign(sdk, {
    checkPrerequisites: async () => ({ status: 'ok', items: [{ id: 'docker', label: 'Docker', status: 'ok' }] }),
    listSdkVersions: async () => ({ items: [{ ref: 'v3.0.0.1', label: 'v3.0.0.1', recommended: true }] }),
    resolveSdkRef: async (ref) => ({ ref, version: '3.0.0.1', image: IMAGE, resource: `ghcr:${IMAGE}`, requiredGb: 20 }),
    inspectImage: async () => (imagePresent ? { present: true, id: 'abc' } : { present: false }),
    listSdkContainers: async () => containers,
    listAllSdkContainers: async () => containers,
    readCodeUi: () => undefined,
    platformVersion: async () => '3.0.0',
    registryImage: (image) => {
      layerSizeCalls.push(image);
      return Promise.resolve({ layers: new Map([['aaaaaaaaaaaa', 6_000_000_000], ['bbbbbbbbbbbb', 4_100_000_000]]), platform: '3.0.0' });
    },
    createPull: (options) => {
      const pull = { options, cancelled: 0, cancel() { pull.cancelled += 1; } };
      pulls.push(pull);
      return pull;
    },
  });
  const hostStatus = requireWithVscode(path.join(ROOT, 'hostStatus.js'), fake.vscode);
  const setupPanel = requireWithVscode(path.join(ROOT, 'setupPanel.js'), fake.vscode);
  const context = fakeContext(ROOT);
  hostStatus.register(context);

  const changed = new EventEmitter();
  const api = {
    simaCli: cli,
    loginState: login,
    calls: { install: 0, login: 0, refresh: 0 },
    installRun: undefined,
    loginRun: undefined,
    latest: '0.0.41',
    getSimaCli: () => api.simaCli,
    readLoginState: () => ({ external: api.loginState }),
    latestSimaCliVersion: async () => api.latest,
    isDevContainersInstalled: () => true,
    onDidChange: changed.event,
    refresh: async () => { api.calls.refresh += 1; return api.simaCli; },
    installSimaCliQuietly: () => { api.calls.install += 1; api.installRun = controllableRun(); return api.installRun; },
    loginQuietly: () => { api.calls.login += 1; api.loginRun = controllableRun(); return api.loginRun; },
    cliEnv: {},
  };
  setupPanel.init(context, api);
  setupPanel.show();
  const panel = fake.panels[fake.panels.length - 1];
  const webview = panel.webview;
  const states = () => webview.posted.filter((m) => m.type === 'state').map((m) => m.state);
  const lastState = () => states()[states().length - 1];
  return { fake, sdk, hostStatus, setupPanel, api, panel, webview, states, lastState, pulls, layerSizeCalls };
}

/** Waits for the page's debounced state message. */
const flush = () => settle(150);

test('the page opens as "Studio: Set up SDK" with the Neat Studio icon', () => {
  const { panel, fake, setupPanel } = openPage();
  assert.equal(panel.viewType, 'simaNeatSetup');
  assert.equal(panel.title, 'Studio: Set up SDK');
  assert.equal(panel.iconPath.fsPath, path.join(ROOT, 'media', 'studio', 'circuit-board.svg'));
  assert.ok(panel.options.retainContextWhenHidden);

  const { html } = panel.webview;
  assert.doesNotMatch(html, /\{\{\w+\}\}/, 'every placeholder is filled');
  assert.ok(html.includes(`href="vscode-resource:${path.join(ROOT, 'media', 'codicons', 'codicon.css')}"`));
  assert.ok(html.includes(`href="vscode-resource:${path.join(ROOT, 'media', 'setup.css')}"`));

  // Opening it again brings the same page to the front.
  setupPanel.show();
  assert.equal(fake.panels.length, 1);
  assert.equal(panel.revealed, 1);
});

test('the page gets the signed-in name and email and the latest sima-cli version', async () => {
  const { webview, lastState, api } = openPage({
    login: { loggedIn: true, user: 'ana@sima.ai', name: 'Ana Dev', email: 'ana@sima.ai' },
  });
  webview.send({ type: 'ready' });
  await flush();
  const state = lastState();
  assert.deepEqual(state.login, { loggedIn: true, user: 'ana@sima.ai', name: 'Ana Dev', email: 'ana@sima.ai' });
  assert.deepEqual(state.cli, { found: true, version: '0.0.40', file: api.simaCli.file });
  assert.equal(state.cliLatest, '0.0.41');
  assert.deepEqual(state.signin, { phase: 'idle' });
});

test('Sign in with sima-cli present: waits for the browser, then is idle again', async () => {
  const { webview, api, states } = openPage();
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  assert.equal(api.calls.install, 0, 'sima-cli is already there');
  assert.equal(api.calls.login, 1);
  assert.deepEqual(states().at(-1).signin, { phase: 'pending' });

  api.loginState = { loggedIn: true, user: 'ana@sima.ai', name: '', email: 'ana@sima.ai' };
  api.loginRun.finish({ ok: true });
  await settle();
  const last = states().at(-1);
  assert.deepEqual(last.signin, { phase: 'idle' });
  assert.equal(last.login.loggedIn, true);
});

test('Sign in without sima-cli installs it quietly first', async () => {
  const { webview, api, states } = openPage({ cli: null });
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  assert.equal(api.calls.refresh, 1, 'looks for sima-cli once more before installing');
  assert.equal(api.calls.install, 1);
  assert.deepEqual(states().at(-1).signin, { phase: 'installing' });
  assert.equal(api.calls.login, 0);

  api.simaCli = { file: '/home/me/.sima-cli/.venv/bin/sima-cli', version: '0.0.41' };
  api.installRun.finish({ ok: true });
  await settle();
  assert.equal(api.calls.login, 1);
  const pending = states().at(-1);
  assert.deepEqual(pending.signin, { phase: 'pending' });
  assert.equal(pending.cli.found, true, 'the page sees the new sima-cli');

  api.loginRun.finish({ ok: true });
  await settle();
  assert.deepEqual(states().at(-1).signin, { phase: 'idle' });
});

test('Sign in: sima-cli found on the second look is used without installing', async () => {
  const { webview, api } = openPage({ cli: null });
  api.refresh = async () => {
    api.simaCli = { file: '/usr/local/bin/sima-cli', version: '0.0.40' };
    return api.simaCli;
  };
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  assert.equal(api.calls.install, 0);
  assert.equal(api.calls.login, 1);
});

test('Sign in: an install that needs a password offers the terminal', async () => {
  const { webview, api, states } = openPage({ cli: null });
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  api.installRun.finish({ ok: false, needsTerminal: true, reason: 'Installing the SiMa command-line tools needs your password.' });
  await settle();
  assert.deepEqual(states().at(-1).signin, {
    phase: 'error', reason: 'Installing the SiMa command-line tools needs your password.', needsTerminal: true,
  });
  assert.equal(api.calls.login, 0);
});

test('Sign in: a cancelled install goes back to idle without an error', async () => {
  const { webview, api, states } = openPage({ cli: null });
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  webview.send({ type: 'action', id: 'signinCancel' });
  await settle();
  assert.equal(api.installRun.cancelled, 1);
  api.installRun.finish({ ok: false, cancelled: true });
  await settle();
  assert.deepEqual(states().at(-1).signin, { phase: 'idle' });
  assert.equal(api.calls.login, 0);
});

test('Sign in: a failed login shows the reason; Cancel during the login stops it', async () => {
  const { webview, api, states } = openPage();
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  api.loginRun.finish({ ok: false, reason: 'Login timed out.' });
  await settle();
  assert.deepEqual(states().at(-1).signin, { phase: 'error', reason: 'Login timed out.' });

  // Try again
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  assert.equal(api.calls.login, 2);
  webview.send({ type: 'action', id: 'signinCancel' });
  await settle();
  assert.equal(api.loginRun.cancelled, 1);
  api.loginRun.finish({ ok: false, cancelled: true, reason: 'ignored' });
  await settle();
  assert.deepEqual(states().at(-1).signin, { phase: 'idle' });
});

test('Sign in pressed twice runs one sign-in; Cancel without a sign-in does nothing', async () => {
  const { webview, api } = openPage();
  webview.send({ type: 'action', id: 'signinCancel' });
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  assert.equal(api.calls.login, 1);
  api.loginRun.finish({ ok: true });
  await settle();
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  assert.equal(api.calls.login, 2, 'a new sign-in can start once the first one ended');
});

test('the side bar follows the step the page is on', async () => {
  const { webview, hostStatus } = openPage();
  webview.send({ type: 'hostStatus', value: { active: 2, total: 5 } });
  await settle();
  assert.deepEqual(hostStatus.get(), { kind: 'progress', step: 2, total: 5, version: '', pct: 0 });

  webview.send({ type: 'hostStatus', value: { active: 1, total: 5 } });
  await settle();
  assert.deepEqual(hostStatus.get(), { kind: 'none' }, 'step 1 means not set up yet');
});

test('the download shows its percentage by bytes in the side bar and status bar', async () => {
  const { webview, hostStatus, pulls, layerSizeCalls, fake } = openPage();
  webview.send({ type: 'ready' });
  await flush();
  webview.send({ type: 'hostStatus', value: { active: 3, total: 5 } });
  webview.send({ type: 'action', id: 'pull' });
  await settle();
  assert.equal(pulls.length, 1);
  assert.deepEqual(layerSizeCalls, [IMAGE]);
  assert.ok(pulls[0].options.layerSizes instanceof Promise, 'layer sizes are read while the download runs');

  const { onUpdate } = pulls[0].options;
  onUpdate({ state: 'running', progress: { done: 1, total: 4, bytesDone: 4_200_000_000, bytesTotal: 10_100_000_000 } });
  await settle();
  assert.deepEqual(hostStatus.get(), { kind: 'progress', step: 3, total: 5, version: 'v3.0.0.1', pct: 42, downloading: true });
  assert.equal(fake.statusItems.at(-1).text, '$(loading~spin) SiMa SDK 42%');

  // Before the sizes are known, the percentage counts finished layers.
  onUpdate({ state: 'waiting', progress: { done: 1, total: 4, bytesDone: 0, bytesTotal: 0 } });
  await settle();
  assert.equal(hostStatus.get().pct, 25);
  assert.equal(hostStatus.get().downloading, true);

  onUpdate({ state: 'failed', error: { message: 'network' }, progress: { done: 0, total: 0 } });
  await settle();
  assert.deepEqual(hostStatus.get(), { kind: 'progress', step: 3, total: 5, version: 'v3.0.0.1', pct: 0, failed: true });
  assert.equal(fake.statusItems.at(-1).text, '$(warning) SiMa SDK download failed');
});

test('a running SDK container shows as running, with the version of the selected release', async () => {
  const { webview, hostStatus } = openPage({
    imagePresent: true,
    containers: [{ name: 'neat-sdk', image: IMAGE, state: 'running' }],
  });
  webview.send({ type: 'ready' });
  await flush();
  await settle();
  const status = hostStatus.get();
  assert.equal(status.kind, 'running');
  assert.equal(status.version, 'v3.0.0.1');
  assert.equal(status.container, 'neat-sdk');
  assert.equal(status.platform, '3.0.0');
});

test('errors from a page action are shown under the new page name', async () => {
  const { webview, fake, api } = openPage();
  api.loginQuietly = () => { throw new Error('boom'); };
  webview.send({ type: 'action', id: 'signin' });
  await settle();
  assert.deepEqual(fake.calls.errors.at(-1), ['Studio: Set up SDK: boom']);
});

test('the page gets the Platform version and download size of the release from ghcr.io', async () => {
  const { webview, lastState, layerSizeCalls } = openPage();
  webview.send({ type: 'ready' });
  await flush();
  await flush();
  assert.equal(lastState().release.platform, '3.0.0');
  assert.equal(lastState().release.downloadBytes, 10_100_000_000);
  assert.deepEqual(layerSizeCalls, [IMAGE], 'asked once');
});

test('the download reuses the registry answer for its layer sizes', async () => {
  const { webview, pulls, layerSizeCalls } = openPage();
  webview.send({ type: 'ready' });
  await flush();
  webview.send({ type: 'action', id: 'pull' });
  await settle();
  assert.equal(pulls.length, 1);
  const sizes = await pulls[0].options.layerSizes;
  assert.equal(sizes.get('aaaaaaaaaaaa'), 6_000_000_000);
  assert.deepEqual(layerSizeCalls, [IMAGE]);
});

test('a failed download says where it stopped, with Open setup and Retry; Retry resumes it', async () => {
  const { webview, pulls, fake } = openPage();
  let answer;
  fake.vscode.window.showWarningMessage = async (...args) => { fake.calls.warnings.push(args); return answer; };
  webview.send({ type: 'ready' });
  await flush();
  webview.send({ type: 'action', id: 'pull' });
  await settle();
  answer = 'Retry';
  pulls[0].options.onUpdate({ state: 'failed', error: { message: 'network connection lost.' }, progress: { done: 5, total: 9, bytesDone: 6_161_000_000, bytesTotal: 10_100_000_000 } });
  await settle();
  assert.deepEqual(fake.calls.warnings.at(-1), ['SDK download stopped at 61%: network connection lost.', 'Open setup', 'Retry']);
  assert.equal(pulls.length, 2, 'Retry started the download again');
  assert.equal(pulls[1].options.image, IMAGE);
  assert.equal(pulls[1].options.resource, `ghcr:${IMAGE}`);
});

test('Open setup in the failure notification brings the page to the front', async () => {
  const { webview, pulls, fake, panel } = openPage();
  fake.vscode.window.showWarningMessage = async (...args) => { fake.calls.warnings.push(args); return 'Open setup'; };
  webview.send({ type: 'ready' });
  await flush();
  webview.send({ type: 'action', id: 'pull' });
  await settle();
  pulls[0].options.onUpdate({ state: 'failed', error: {}, progress: { done: 0, total: 0 } });
  await settle();
  assert.deepEqual(fake.calls.warnings.at(-1), ['SDK download stopped at 0%: the download failed.', 'Open setup', 'Retry']);
  assert.equal(panel.revealed, 1);
  assert.equal(pulls.length, 1);
});

test('a finished download says "SiMa SDK v3.0.0.1 downloaded."', async () => {
  const { webview, pulls, fake } = openPage();
  webview.send({ type: 'ready' });
  await flush();
  webview.send({ type: 'action', id: 'pull' });
  await settle();
  pulls[0].options.onUpdate({ state: 'done', progress: { done: 9, total: 9 } });
  await settle();
  assert.deepEqual(fake.calls.info.at(-1), ['SiMa SDK v3.0.0.1 downloaded.']);
});
