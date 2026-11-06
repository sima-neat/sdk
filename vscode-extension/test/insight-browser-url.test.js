const assert = require('node:assert/strict');
const test = require('node:test');
const { resolveInsightBrowserUrl } = require('../src/insight-browser-url');
const { getInsightUrl, readInsight } = require('../src/landing-data');

function browserVscode(host, calls = []) {
  return {
    UIKind: { Web: 2 },
    Uri: { parse: value => value },
    env: { uiKind: 2, asExternalUri: async value => {
      calls.push(value);
      return `https://${host}/proxy/${new URL(value).port}/`;
    } }
  };
}

for (const host of ['127.0.0.1:10000', 'localhost:10000', '192.168.76.60:10000', 'remote.example:10000', '[2001:db8::1]:10000']) {
  test(`launches directly on the browser hostname ${host}`, async () => {
    const calls = [];
    const url = await resolveInsightBrowserUrl(browserVscode(host, calls),
      'https://10.252.185.1:19900/viewer?src=1#video');
    const expected = new URL(`https://${host}/viewer?src=1#video`);
    expected.port = '19900';
    assert.equal(url, expected.href);
    assert.deepEqual(calls, ['http://127.0.0.1:19900/']);
    assert.doesNotMatch(url, /\/proxy\//);
  });
}

test('native VS Code retains the advertised address without browser resolution', async () => {
  const vscode = browserVscode('sdk.example:10000');
  vscode.env.uiKind = 1;
  vscode.env.asExternalUri = () => { throw new Error('unexpected browser call'); };
  assert.equal(await resolveInsightBrowserUrl(vscode, 'https://10.252.185.1:9900/'),
    'https://10.252.185.1:9900/');
});

const status = { insight: { webUiUrl: 'https://10.252.185.1:9900/' } };
function options(override = '') {
  return {
    reader: async file => {
      if (file.endsWith('/launch-url')) return override;
      if (file.endsWith('/neat-port-map.json')) return JSON.stringify({ mainUI: { host: 19900 } });
      return '';
    },
    env: { CONTAINER_HOST_IP: '10.252.185.1' },
    resolveBrowserUrl: url => resolveInsightBrowserUrl(browserVscode('192.168.76.60:10000'), url)
  };
}

test('launch and landing page use browser host and published port instead of VPN status', async () => {
  assert.equal(await getInsightUrl(status, options()), 'https://192.168.76.60:19900/');
  assert.equal((await readInsight({ ...status, components: { insight: { version: '1.0' } } }, options())).url,
    'https://192.168.76.60:19900/');
  // Platform-only SDKs do not need Core status or a transport host to launch.
  assert.equal(await getInsightUrl({}, { ...options(), env: {} }), 'https://192.168.76.60:19900/');
});

test('explicit gateway override bypasses browser hostname and port rewriting', async () => {
  const override = 'https://arthas.example/session/proxy/9900/?session=abc#viewer';
  const config = options(override);
  config.resolveBrowserUrl = () => { throw new Error('override must remain authoritative'); };
  assert.equal(await getInsightUrl(status, config), override);
});

test('old images without a port map use the status port with the browser hostname', async () => {
  assert.equal(await getInsightUrl(status, { ...options(), reader: async () => '' }),
    'https://192.168.76.60:9900/');
});

test('browser routing failures propagate instead of silently launching a VPN URL', async () => {
  const config = options();
  config.resolveBrowserUrl = () => { throw new Error('browser route unavailable'); };
  await assert.rejects(getInsightUrl(status, config), /browser route unavailable/);
});

test('published HTTP scheme and default ports survive browser resolution', async () => {
  const config = options();
  config.reader = async file => file.endsWith('/neat-port-map.json')
    ? JSON.stringify({ mainUI: { host: 80, scheme: 'http' } }) : '';
  assert.equal(await getInsightUrl(status, config), 'http://192.168.76.60/');
  assert.equal(await resolveInsightBrowserUrl(browserVscode('localhost:10000'), 'https://10.252.185.1/'),
    'https://localhost/');
});
