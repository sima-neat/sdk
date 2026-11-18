'use strict';

// The "Neat SDK" side bar view and the "SDK" status bar item on this computer
// (hostStatus.js): not set up, setting up (step / download progress / failed), running.

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { ROOT, requireWithVscode } = require('./helpers');
const { createFakeVscode, fakeContext, settle } = require('./fakeVscode');

/** A fresh hostStatus module with its own fake vscode and stubbed Docker calls. */
function load({ remoteName, containers = [], platform = '' } = {}) {
  const fake = createFakeVscode({ remoteName });
  for (const file of ['hostStatus.js', 'sdk.js']) {
    delete require.cache[path.join(ROOT, file)];
  }
  const sdk = requireWithVscode(path.join(ROOT, 'sdk.js'), fake.vscode);
  const platformCalls = [];
  sdk.listAllSdkContainers = async () => containers;
  sdk.platformVersion = async (name) => {
    platformCalls.push(name);
    return platform;
  };
  const hostStatus = requireWithVscode(path.join(ROOT, 'hostStatus.js'), fake.vscode);
  const context = fakeContext(ROOT);
  return { fake, sdk, hostStatus, context, platformCalls };
}

const bodyText = (html) => html
  .replace(/<script[\s\S]*?<\/script>/g, '')
  .replace(/<style[\s\S]*?<\/style>/g, '')
  .replace(/<[^>]+>/g, ' ')
  .replace(/&amp;/g, '&')
  .replace(/\s+/g, ' ')
  .trim();

test('versionFromImage takes the tag of the image', () => {
  const { hostStatus } = load();
  assert.equal(hostStatus.versionFromImage('ghcr.io/sima-neat/sdk:v3.0.0.1'), 'v3.0.0.1');
  assert.equal(hostStatus.versionFromImage('localhost:5000/sdk:main'), 'main');
  assert.equal(hostStatus.versionFromImage('ghcr.io/sima-neat/sdk'), '');
  assert.equal(hostStatus.versionFromImage(undefined), '');
});

test('does nothing in a window attached to the SDK container', async () => {
  const { fake, hostStatus, context } = load({ remoteName: 'attached-container' });
  hostStatus.register(context);
  await settle();
  assert.equal(fake.statusItems.length, 0);
  assert.equal(fake.viewProviders.size, 0);
  assert.equal(context.subscriptions.length, 0);
});

test('registers the side bar view and a hidden status bar item', async () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  await settle();
  assert.ok(fake.viewProviders.has(hostStatus.VIEW_ID));
  assert.equal(hostStatus.VIEW_ID, 'simaNeatTools.host');
  assert.equal(fake.statusItems.length, 1);
  const [item] = fake.statusItems;
  assert.equal(item.name, 'Neat SDK');
  assert.equal(item.visible, false, 'nothing to show before setup starts');
  assert.deepEqual(hostStatus.get(), { kind: 'none' });
  assert.equal(hostStatus.isVisible(), false);
});

test('status bar shows the download percentage and opens setup', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  hostStatus.set({ kind: 'progress', step: 3, total: 5, downloading: true, pct: 42, version: 'v3.0.0.1' });
  const [item] = fake.statusItems;
  assert.equal(item.visible, true);
  assert.equal(item.text, '$(loading~spin) SDK 42%');
  assert.equal(item.tooltip, 'Downloading SDK v3.0.0.1 · click to open setup');
  assert.equal(item.command, 'simaNeat.openSetup');
  assert.equal(item.color, undefined);
});

test('status bar tooltip has no double space when the version is unknown', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  hostStatus.set({ kind: 'progress', downloading: true, pct: 5 });
  assert.equal(fake.statusItems[0].tooltip, 'Downloading SDK · click to open setup');
});

test('status bar warns when the download failed', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  hostStatus.set({ kind: 'progress', failed: true, pct: 17 });
  const [item] = fake.statusItems;
  assert.equal(item.visible, true);
  assert.equal(item.text, '$(warning) SDK download failed');
  assert.equal(item.tooltip, 'Click to open setup');
  assert.equal(item.command, 'simaNeat.openSetup');
  assert.equal(item.backgroundColor.id, 'statusBarItem.warningBackground', 'a warning item, as in frame A3c');
  assert.equal(item.color, undefined);
});

test('status bar stays hidden on a setup step without a download', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  hostStatus.set({ kind: 'progress', step: 2, total: 5 });
  assert.equal(fake.statusItems[0].visible, false);
});

test('status bar shows a running SDK with its Platform version from the container label', async () => {
  const { fake, hostStatus, context, platformCalls } = load({ platform: '3.0.0' });
  hostStatus.register(context);
  hostStatus.set({ kind: 'running', version: 'v3.0.0.1', container: 'neat-sdk' });
  const [item] = fake.statusItems;
  assert.equal(item.text, '$(vm) Neat SDK: running');
  assert.equal(item.command, 'simaNeat.openSdkInVsCode');
  assert.equal(item.tooltip, 'SDK v3.0.0.1 · container neat-sdk', 'Platform is not known yet');
  await settle();
  assert.equal(item.tooltip, 'SDK v3.0.0.1 · container neat-sdk · Platform 3.0.0');
  assert.equal(hostStatus.get().platform, '3.0.0');

  // The label is read once per container.
  hostStatus.set({ kind: 'progress', step: 2, total: 5 });
  hostStatus.set({ kind: 'running', version: 'v3.0.0.1', container: 'neat-sdk' });
  await settle();
  assert.deepEqual(platformCalls, ['neat-sdk']);
  assert.equal(hostStatus.get().platform, '3.0.0');
});

test('a Platform version that arrives late does not overwrite another status', async () => {
  const { hostStatus, context } = load({ platform: '3.0.0' });
  hostStatus.register(context);
  hostStatus.set({ kind: 'running', version: 'v3.0.0.1', container: 'neat-sdk' });
  hostStatus.set({ kind: 'progress', step: 1, total: 5 });
  await settle();
  assert.deepEqual(hostStatus.get(), { kind: 'progress', step: 1, total: 5 });
});

test('on start, finds an SDK container that is already running', async () => {
  const { fake, hostStatus, context } = load({
    containers: [
      { name: 'neat-sdk', image: 'ghcr.io/sima-neat/sdk:v3.0.0.1', state: 'running' },
      { name: 'old', image: 'ghcr.io/sima-neat/sdk:v2.0.0', state: 'exited' },
    ],
  });
  hostStatus.register(context);
  await settle();
  assert.equal(hostStatus.get().kind, 'running');
  assert.equal(hostStatus.get().version, 'v3.0.0.1');
  assert.equal(hostStatus.get().container, 'neat-sdk');
  assert.equal(fake.statusItems[0].text, '$(vm) Neat SDK: running');
});

test('on start, keeps "not set up" when no SDK container runs or Docker fails', async () => {
  const stopped = load({ containers: [{ name: 'neat-sdk', image: 'ghcr.io/sima-neat/sdk:v3.0.0.1', state: 'exited' }] });
  stopped.hostStatus.register(stopped.context);
  await settle();
  assert.deepEqual(stopped.hostStatus.get(), { kind: 'none' });

  const broken = load();
  broken.sdk.listAllSdkContainers = async () => { throw new Error('docker: not found'); };
  broken.hostStatus.register(broken.context);
  await settle();
  assert.deepEqual(broken.hostStatus.get(), { kind: 'none' });
});

test('side bar view: not set up', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);
  assert.equal(hostStatus.isVisible(), true);
  const text = bodyText(view.webview.html);
  assert.equal(text, 'Neat SDK SDK not set up Sign in, check this computer and download the SDK. About 15 minutes, mostly download. Set up SDK Catalog, Devices and Insight are inside the SDK. Repair SiMa Neat Studio…');
  assert.match(view.webview.html, /class="dot" style="background:var\(--vscode-descriptionForeground\)"/);
  assert.match(view.webview.html, /codicon-chevron-down/);
  assert.match(view.webview.html, /id: 'setup'/);
  assert.doesNotMatch(view.webview.html, /class="bar"/);
  assert.match(view.webview.html, /Content-Security-Policy/);
});

test('side bar view: a setup step, a download with its bar, a failed download', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);

  hostStatus.set({ kind: 'progress', step: 2, total: 5 });
  let text = bodyText(view.webview.html);
  assert.match(text, /^Neat SDK Setting up Step 2 of 5 Continue setup /);
  assert.match(view.webview.html, /var\(--vscode-editorWarning-foreground\)/);

  hostStatus.set({ kind: 'progress', step: 3, total: 5, downloading: true, pct: 42, version: 'v3.0.0.1' });
  text = bodyText(view.webview.html);
  assert.match(text, /Setting up Downloading SDK v3\.0\.0\.1 · 42% Continue setup/);
  assert.match(view.webview.html, /<div class="bar"><div style="width:42%"><\/div><\/div>/);

  hostStatus.set({ kind: 'progress', step: 3, total: 5, failed: true, pct: 17 });
  text = bodyText(view.webview.html);
  assert.match(text, /Setting up SDK download failed at 17% Continue setup/);
  assert.doesNotMatch(view.webview.html, /class="bar"/);
});

test('side bar view: running SDK opens SiMa Neat Studio', async () => {
  const { fake, hostStatus, context } = load({ platform: '3.0.0' });
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);
  hostStatus.set({ kind: 'running', version: 'v3.0.0.1', container: 'neat-sdk' });
  await settle();
  const text = bodyText(view.webview.html);
  assert.match(text, /^Neat SDK SDK running · v3\.0\.0\.1 Container neat-sdk · Platform 3\.0\.0 Open SiMa Neat Studio /);
  assert.match(view.webview.html, /var\(--vscode-testing-iconPassed\)/);
  assert.match(view.webview.html, /id: 'open'/);
});

test('side bar view escapes text from Docker', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);
  hostStatus.set({ kind: 'running', version: '<b>v1</b>', container: 'a"&b' });
  assert.match(view.webview.html, /SDK running · &lt;b&gt;v1&lt;\/b&gt;/);
  assert.match(view.webview.html, /Container a&quot;&amp;b/);
  assert.doesNotMatch(view.webview.html, /<b>v1<\/b>/);
});

test('side bar view: the button runs the command for the state', async () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);
  view.webview.send({ type: 'action', id: 'setup' });
  view.webview.send({ type: 'action', id: 'open' });
  view.webview.send({ type: 'other' });
  await settle();
  assert.deepEqual(fake.calls.commands, [['simaNeat.openSetup'], ['simaNeat.openSdkInVsCode']]);
});

test('side bar view: the "Neat SDK" header collapses and expands the section', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);
  view.webview.send({ type: 'toggle' });
  assert.match(view.webview.html, /aria-expanded="false"/);
  assert.match(view.webview.html, /codicon-chevron-right/);
  assert.match(view.webview.html, /<div class="wrap" hidden>/);
  view.webview.send({ type: 'toggle' });
  assert.match(view.webview.html, /aria-expanded="true"/);
  assert.match(view.webview.html, /codicon-chevron-down/);
  assert.match(view.webview.html, /<div class="wrap">/);
});

test('side bar view stops updating once VS Code closes it', () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);
  const before = view.webview.html;
  view.dispose();
  assert.equal(hostStatus.isVisible(), false);
  hostStatus.set({ kind: 'progress', step: 4, total: 5 });
  assert.equal(view.webview.html, before);
});

test('side bar view: Repair SiMa Neat Studio… runs the repair command', async () => {
  const { fake, hostStatus, context } = load();
  hostStatus.register(context);
  const view = fake.resolveView(hostStatus.VIEW_ID);
  assert.match(view.webview.html, /<a href="#" class="repair" id="repair" title="Reinstalls sima-cli and recreates the SDK container\. Your workspace folder is kept\."><i class="codicon codicon-tools"><\/i>Repair SiMa Neat Studio…<\/a>/);
  view.webview.send({ type: 'repair' });
  await settle();
  assert.deepEqual(fake.calls.commands, [['simaNeat.repair']]);
});
