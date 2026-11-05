const assert = require('node:assert/strict');
const test = require('node:test');
const { createInsightView } = require('../src/insight-view');

function fixture() {
  const panels = [], errors = [], subscriptions = [];
  let serializer, url = 'https://sdk.example:9900/viewer?src=1&name="test"#video';
  function makePanel() {
    let dispose;
    const panel = {
      webview: { html: '', options: {} }, reveals: 0,
      reveal() { this.reveals++; },
      onDidDispose(fn) { dispose = fn; },
      dispose() { this.disposed = true; dispose?.(); }
    };
    panels.push(panel);
    return panel;
  }
  const vscode = {
    ViewColumn: { Active: -1 },
    window: {
      createWebviewPanel(type, title, column, options) {
        const panel = makePanel();
        Object.assign(panel, { type, title, column, options });
        return panel;
      },
      registerWebviewPanelSerializer(type, value) { serializer = value; return { dispose() {} }; },
      showErrorMessage(message) { errors.push(message); }
    }
  };
  const view = createInsightView(vscode, { subscriptions }, async () => url);
  return { view, panels, errors, subscriptions, makePanel, setUrl(value) { url = value; }, restore(panel) { return serializer.deserializeWebviewPanel(panel); } };
}

test('launches a direct HTTPS editor tab and preserves its live view across concurrent launches', async () => {
  const f = fixture();
  await Promise.all([f.view.open(), f.view.open()]);
  assert.equal(f.panels.length, 1);
  const p = f.panels[0];
  assert.equal(p.type, 'simaNeat.insight');
  assert.equal(p.title, 'Insight');
  assert.match(p.webview.html, /allow="camera https:\/\/sdk.example:9900;/);
  assert.equal(p.options.retainContextWhenHidden, true);
  assert.match(p.webview.html, /frame-src https:\/\/sdk.example:9900/);
  assert.match(p.webview.html, /src="https:\/\/sdk.example:9900\/viewer\?src=1&amp;name=%22test%22#video"/);
  assert.doesNotMatch(p.webview.html, /palette-insight-direct|\/proxy\//);
  p.webview.html = 'live viewer state';
  await f.view.open();
  assert.equal(p.webview.html, 'live viewer state');
  assert.equal(p.reveals, 3);
});

test('updates a changed host launch URL, then allows closing and reopening', async () => {
  const f = fixture();
  await f.view.open();
  f.setUrl('https://arthas.example/session/proxy/9900/?session=abc#viewer');
  await f.view.open();
  assert.match(f.panels[0].webview.html, /session\/proxy\/9900\/\?session=abc#viewer/);
  f.panels[0].dispose();
  await f.view.open();
  assert.equal(f.panels.length, 2);
});

test('restores the editor tab using the current service URL and disposes on shutdown', async () => {
  const f = fixture();
  const panel = f.makePanel();
  await f.restore(panel);
  assert.equal(f.panels.length, 1);
  assert.match(panel.webview.html, /title="Insight"/);
  assert.equal(panel.webview.options.enableScripts, true);
  f.subscriptions.at(-1).dispose();
  assert.equal(panel.disposed, true);
});

test('rejects absent and non-HTTP launch URLs without opening an editor', async () => {
  const f = fixture();
  for (const url of ['', 'javascript:alert(1)', 'file:///etc/passwd']) {
    f.setUrl(url);
    await f.view.open();
  }
  assert.equal(f.panels.length, 0);
  assert.equal(f.errors.length, 3);
});
