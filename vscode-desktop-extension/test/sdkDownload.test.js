'use strict';

// What the Set up SDK page needs from sdk.js for "v3.0.0.1 · 42% · 4.2 of 10.1 GB"
// and "Platform 3.0.0": layer sizes from ghcr.io, byte progress of the download,
// and the Platform version label of a container.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { ROOT, tempDir } = require('./helpers');
const { stubHttpsGet } = require('./fakeHttp');

const sdk = require(path.join(ROOT, 'sdk.js'));

const LAYER_A = `sha256:${'a'.repeat(12)}${'0'.repeat(52)}`;
const LAYER_B = `sha256:${'b'.repeat(12)}${'0'.repeat(52)}`;

/** Puts executable scripts on PATH for this test. */
function fakeBin(t, scripts) {
  const dir = tempDir(t);
  for (const [name, body] of Object.entries(scripts)) {
    const file = path.join(dir, name);
    fs.writeFileSync(file, `#!/bin/sh\n${body}\n`, { mode: 0o755 });
  }
  const savedPath = process.env.PATH;
  process.env.PATH = `${dir}${path.delimiter}${savedPath}`;
  t.after(() => { process.env.PATH = savedPath; });
  return dir;
}

test('imageLayerSizes reads the layers of the image for this computer', async (t) => {
  const arch = process.arch === 'arm64' ? 'arm64' : 'amd64';
  const other = arch === 'arm64' ? 'amd64' : 'arm64';
  const requests = stubHttpsGet(t, (url) => {
    if (url === 'https://ghcr.io/token?scope=repository:sima-neat/sdk:pull') {
      return { body: { token: 'anon-token' } };
    }
    if (url === 'https://ghcr.io/v2/sima-neat/sdk/manifests/v3.0.0.1') {
      return {
        body: {
          manifests: [
            { digest: 'sha256:other', platform: { os: 'linux', architecture: other } },
            { digest: 'sha256:mine', platform: { os: 'linux', architecture: arch } },
          ],
        },
      };
    }
    if (url === 'https://ghcr.io/v2/sima-neat/sdk/manifests/sha256:mine') {
      return { body: { layers: [{ digest: LAYER_A, size: 4_200_000_000 }, { digest: LAYER_B, size: '5900000000' }] } };
    }
    throw new Error(`unexpected ${url}`);
  });

  const sizes = await sdk.imageLayerSizes('ghcr.io/sima-neat/sdk:v3.0.0.1');
  assert.deepEqual([...sizes], [['aaaaaaaaaaaa', 4_200_000_000], ['bbbbbbbbbbbb', 5_900_000_000]]);

  // The manifests are read with the anonymous token and the manifest media types.
  const manifestRequests = requests.filter((r) => r.url.includes('/manifests/'));
  assert.equal(manifestRequests.length, 2);
  for (const { headers } of manifestRequests) {
    assert.equal(headers.Authorization, 'Bearer anon-token');
    assert.match(headers.Accept, /application\/vnd\.oci\.image\.index\.v1\+json/);
    assert.match(headers.Accept, /application\/vnd\.docker\.distribution\.manifest\.v2\+json/);
    assert.equal(headers['User-Agent'], 'sima-neat-desktop');
  }
});

test('imageLayerSizes takes a single-platform manifest as it is', async (t) => {
  stubHttpsGet(t, (url) => {
    if (url.startsWith('https://ghcr.io/token')) {
      return { body: { token: 'x' } };
    }
    return { body: { layers: [{ digest: LAYER_A, size: 10 }, { digest: LAYER_B }] } };
  });
  const sizes = await sdk.imageLayerSizes('ghcr.io/sima-neat/sdk@sha256:abc');
  assert.deepEqual([...sizes], [['aaaaaaaaaaaa', 10], ['bbbbbbbbbbbb', 0]]);
});

test('imageLayerSizes falls back to the first manifest when no entry matches this computer', async (t) => {
  const asked = [];
  stubHttpsGet(t, (url) => {
    asked.push(url);
    if (url.startsWith('https://ghcr.io/token')) {
      return { body: { token: 'x' } };
    }
    if (url.endsWith('/manifests/main')) {
      return { body: { manifests: [{ digest: 'sha256:first', platform: { os: 'windows', architecture: 'amd64' } }] } };
    }
    return { body: { layers: [] } };
  });
  const sizes = await sdk.imageLayerSizes('ghcr.io/sima-neat/sdk:main');
  assert.equal(sizes.size, 0);
  assert.ok(asked.includes('https://ghcr.io/v2/sima-neat/sdk/manifests/sha256:first'));
});

test('imageLayerSizes keeps the registry headers across a redirect', async (t) => {
  const requests = stubHttpsGet(t, (url) => {
    if (url.startsWith('https://ghcr.io/token')) {
      return { body: { token: 'tok' } };
    }
    if (url === 'https://ghcr.io/v2/sima-neat/sdk/manifests/v1') {
      return { status: 307, headers: { location: '/v2/moved/manifests/v1' } };
    }
    return { body: { layers: [{ digest: LAYER_A, size: 7 }] } };
  });
  const sizes = await sdk.imageLayerSizes('ghcr.io/sima-neat/sdk:v1');
  assert.deepEqual([...sizes], [['aaaaaaaaaaaa', 7]]);
  const moved = requests.find((r) => r.url === 'https://ghcr.io/v2/moved/manifests/v1');
  assert.ok(moved, 'followed the redirect');
  assert.equal(moved.headers.Authorization, 'Bearer tok');
});

test('imageLayerSizes returns nothing for images outside ghcr.io, without network', async (t) => {
  const requests = stubHttpsGet(t, () => { throw new Error('no network expected'); });
  assert.equal((await sdk.imageLayerSizes('docker.io/library/ubuntu:24.04')).size, 0);
  assert.equal((await sdk.imageLayerSizes('')).size, 0);
  assert.equal((await sdk.imageLayerSizes(undefined)).size, 0);
  assert.equal(requests.length, 0);
});

test('imageLayerSizes fails when the registry refuses', async (t) => {
  stubHttpsGet(t, (url) => (url.startsWith('https://ghcr.io/token') ? { body: { token: 'x' } } : { status: 404 }));
  await assert.rejects(sdk.imageLayerSizes('ghcr.io/sima-neat/sdk:nope'), /returned HTTP 404/);
});

test('platformVersion reads the Platform label of a container', async (t) => {
  const dir = tempDir(t);
  const argsFile = path.join(dir, 'args');
  fakeBin(t, { docker: `printf '%s\\n' "$@" > '${argsFile}'\necho "3.0.0"` });
  assert.equal(await sdk.platformVersion('neat-sdk'), '3.0.0');
  assert.deepEqual(fs.readFileSync(argsFile, 'utf8').trim().split('\n'), [
    'inspect', '--format', '{{index .Config.Labels "com.sima.sdk.platform.version"}}', 'neat-sdk',
  ]);
});

test('platformVersion is empty when the container has no Platform label', async (t) => {
  fakeBin(t, { docker: 'echo "<no value>"' });
  assert.equal(await sdk.platformVersion('neat-sdk'), '');
});

test('platformVersion is empty when the container does not exist', async (t) => {
  fakeBin(t, { docker: 'echo "Error: No such object" >&2; exit 1' });
  assert.equal(await sdk.platformVersion('missing'), '');
});

/** Runs createPull with a fake sima-cli that prints `lines`, and collects the snapshots. */
function runPull(t, { lines, layerSizes }) {
  const bin = fakeBin(t, {
    // inspectImage after the pull: the image is there.
    docker: 'echo "sha256:0123456789ab|2026-11-18T00:00:00Z|10100000000"',
  });
  const simaCli = path.join(bin, 'sima-cli');
  fs.writeFileSync(simaCli, `#!/bin/sh\n${lines.map((l) => `echo '${l}'`).join('\n')}\n`, { mode: 0o755 });
  const snapshots = [];
  return new Promise((resolve) => {
    sdk.createPull({
      simaCliFile: simaCli,
      env: process.env,
      resource: 'ghcr:sima-neat/sdk:v3.0.0.1',
      image: 'ghcr.io/sima-neat/sdk:v3.0.0.1',
      maxRetries: 0,
      layerSizes,
      onUpdate: (snapshot) => {
        snapshots.push(snapshot);
        if (snapshot.state === 'done' || snapshot.state === 'failed') {
          resolve(snapshots);
        }
      },
    });
  });
}

test('createPull counts downloaded bytes from the layer sizes', async (t) => {
  let release;
  const sizes = new Promise((resolve) => { release = resolve; });
  const pull = runPull(t, {
    layerSizes: sizes,
    lines: [
      'aaaaaaaaaaaa: Pulling fs layer',
      'bbbbbbbbbbbb: Pulling fs layer',
      'cccccccccccc: Pulling fs layer',
      'aaaaaaaaaaaa: Downloading  1.2GB/4.2GB',
      'aaaaaaaaaaaa: Download complete',
      'bbbbbbbbbbbb: Verifying Checksum',
      'cccccccccccc: Already exists',
    ],
  });
  release(new Map([['aaaaaaaaaaaa', 4_200_000_000], ['bbbbbbbbbbbb', 5_000_000_000], ['cccccccccccc', 900_000_000]]));
  const snapshots = await pull;
  const last = snapshots[snapshots.length - 1];
  assert.equal(last.state, 'done');
  assert.deepEqual(last.progress, { done: 1, total: 3, bytesDone: 10_100_000_000, bytesTotal: 10_100_000_000, speed: 0, secondsLeft: undefined });

  // Midway: only the first layer's bytes count after its download completes.
  const midway = snapshots.find((s) => s.statusLine === 'aaaaaaaaaaaa: Download complete');
  assert.equal(midway.progress.bytesTotal, 10_100_000_000);
  assert.equal(midway.progress.bytesDone, 4_200_000_000);
  const downloading = snapshots.find((s) => s.statusLine.startsWith('aaaaaaaaaaaa: Downloading'));
  assert.equal(downloading.progress.bytesDone, 1_200_000_000, 'a layer still downloading counts what it has so far');
});

test('createPull without layer sizes reports zero bytes and counts layers', async (t) => {
  const snapshots = await runPull(t, {
    lines: ['aaaaaaaaaaaa: Pulling fs layer', 'aaaaaaaaaaaa: Pull complete'],
  });
  const last = snapshots[snapshots.length - 1];
  assert.deepEqual(last.progress, { done: 1, total: 1, bytesDone: 0, bytesTotal: 0, speed: 0, secondsLeft: undefined });
});

test('createPull keeps going when the layer sizes cannot be read', async (t) => {
  const snapshots = await runPull(t, {
    layerSizes: Promise.reject(new Error('ghcr.io unreachable')),
    lines: ['aaaaaaaaaaaa: Pull complete'],
  });
  const last = snapshots[snapshots.length - 1];
  assert.equal(last.state, 'done');
  assert.equal(last.progress.bytesTotal, 0);
});

test('createPull ignores layer sizes that are not a Map', async (t) => {
  const snapshots = await runPull(t, {
    layerSizes: Promise.resolve({ aaaaaaaaaaaa: 5 }),
    lines: ['aaaaaaaaaaaa: Pull complete'],
  });
  assert.equal(snapshots[snapshots.length - 1].progress.bytesTotal, 0);
});

test('parseBytes reads the sizes docker prints', () => {
  assert.equal(sdk.parseBytes('1.2GB'), 1_200_000_000);
  assert.equal(sdk.parseBytes('45.6 MB'), 45_600_000);
  assert.equal(sdk.parseBytes('512kB'), 512_000);
  assert.equal(sdk.parseBytes('12B'), 12);
  assert.equal(sdk.parseBytes('lots'), 0);
});

test('registryImage also reads the Platform label from the image config', async (t) => {
  stubHttpsGet(t, (url) => {
    if (url.startsWith('https://ghcr.io/token')) return { body: { token: 'x' } };
    if (url.endsWith('/manifests/v3.0.0.1')) return { body: { config: { digest: 'sha256:cfg' }, layers: [{ digest: LAYER_A, size: 5 }] } };
    if (url.endsWith('/blobs/sha256:cfg')) return { body: { config: { Labels: { 'com.sima.sdk.platform.version': '3.0.0' } } } };
    throw new Error(`unexpected ${url}`);
  });
  const info = await sdk.registryImage('ghcr.io/sima-neat/sdk:v3.0.0.1');
  assert.equal(info.platform, '3.0.0');
  assert.deepEqual([...info.layers], [['aaaaaaaaaaaa', 5]]);
});

test('registryImage keeps the sizes when the config cannot be read', async (t) => {
  stubHttpsGet(t, (url) => {
    if (url.startsWith('https://ghcr.io/token')) return { body: { token: 'x' } };
    if (url.includes('/manifests/')) return { body: { config: { digest: 'sha256:cfg' }, layers: [{ digest: LAYER_A, size: 5 }] } };
    return { status: 500 };
  });
  const info = await sdk.registryImage('ghcr.io/sima-neat/sdk:v1');
  assert.equal(info.platform, '');
  assert.equal(info.layers.size, 1);
});

test('createPull reports speed and time left from the bytes of the last seconds', async (t) => {
  const bin = fakeBin(t, { docker: 'echo "sha256:0123456789ab|2026-11-18T00:00:00Z|10100000000"' });
  const simaCli = path.join(bin, 'sima-cli');
  // 1.1 s apart: 100 MB, then 300 MB, … of a 1 GB layer.
  fs.writeFileSync(simaCli, `#!/bin/sh
for n in 100 300 500 700; do echo "aaaaaaaaaaaa: Downloading  [==>  ]  \${n}MB/1GB"; sleep 1.1; done
echo "aaaaaaaaaaaa: Pull complete"
`, { mode: 0o755 });
  const snapshots = await new Promise((resolve) => {
    const seen = [];
    sdk.createPull({
      simaCliFile: simaCli, env: process.env, resource: 'r', image: 'i', maxRetries: 0,
      layerSizes: Promise.resolve(new Map([['aaaaaaaaaaaa', 1_000_000_000]])),
      onUpdate: (s) => { seen.push(s); if (s.state === 'done') resolve(seen); },
    });
  });
  const withSpeed = snapshots.filter((s) => s.progress.speed);
  assert.ok(withSpeed.length > 0, 'speed appears after a few seconds');
  const last = withSpeed.find((s) => s.statusLine.includes('700MB'));
  assert.equal(last.progress.bytesDone, 700_000_000);
  // ~600 MB in ~3.3 s ≈ 180 MB/s; ~300 MB left ≈ 2 s.
  assert.ok(last.progress.speed > 120e6 && last.progress.speed < 260e6, `speed ${last.progress.speed}`);
  assert.ok(last.progress.secondsLeft >= 1 && last.progress.secondsLeft <= 3, `left ${last.progress.secondsLeft}`);
  const early = snapshots.find((s) => s.progress.bytesDone === 100_000_000);
  assert.equal(early.progress.speed, 0, 'no speed in the first seconds');
  assert.equal(snapshots.at(-1).progress.speed, 0, 'no speed once done');
});
