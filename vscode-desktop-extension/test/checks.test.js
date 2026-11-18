'use strict';

// "Check this computer" data from sdk.checkPrerequisites (frames A2a–A2e), with a fake
// `docker` on PATH. Runs on Linux, where the extension checks Docker Engine itself.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { ROOT, tempDir } = require('./helpers');

const sdk = require(path.join(ROOT, 'sdk.js'));
const linuxOnly = { skip: process.platform !== 'linux' && 'the Linux checks' };

/** A fake docker answering `--version`, `info` and `version` as given (shell snippets). */
function fakeDocker(t, { version = 'echo "Docker version 29.9.3, build 5457199"', info, platform = 'echo "Docker Engine - Community"' }) {
  const dir = tempDir(t);
  fs.writeFileSync(path.join(dir, 'docker'), `#!/bin/sh
case "$1" in
  --version) ${version};;
  info) ${info};;
  version) ${platform};;
esac
`, { mode: 0o755 });
  const saved = process.env.PATH;
  process.env.PATH = `${dir}${path.delimiter}${saved}`;
  t.after(() => { process.env.PATH = saved; });
}

const byId = (result) => Object.fromEntries(result.items.map((i) => [i.id, i]));

test('all OK: short values, Required and Optional groups', linuxOnly, async (t) => {
  const root = tempDir(t);
  fakeDocker(t, { info: `echo "29.9.3|${root}|Ubuntu 24.04.5 LTS"` });
  const result = await sdk.checkPrerequisites(1);
  const items = byId(result);
  assert.equal(result.status === 'ok' || result.status === 'warn', true);
  assert.equal(result.dockerReady, true);
  assert.deepEqual(result.items.map((i) => [i.id, i.label, i.group]), [
    ['os', 'Host OS', 'required'],
    ['docker', 'Docker', 'required'],
    ['daemon', 'Docker daemon', 'required'],
    ['disk', 'Disk space', 'required'],
    ['ethtool', 'ethtool', 'optional'],
  ]);
  assert.match(items.os.detail, new RegExp(` · ${os.machine()}$`));
  assert.deepEqual(items.docker, { id: 'docker', label: 'Docker', group: 'required', status: 'ok', detail: 'Docker Engine 29.9.3' });
  assert.deepEqual(items.daemon, { id: 'daemon', label: 'Docker daemon', group: 'required', status: 'ok', detail: 'Running' });
  assert.equal(items.disk.status, 'ok');
  assert.match(items.disk.detail, /^\d+ GB free · needs ~1 GB$/);
  assert.equal(items.disk.fix, undefined);
  assert.ok(['Installed', 'Missing'].includes(items.ethtool.detail));
});

test('Docker Desktop shows its version and the engine as major.minor', linuxOnly, async (t) => {
  fakeDocker(t, { info: 'echo "27.3.1|/var/lib/docker|Docker Desktop"', platform: 'echo "Docker Desktop 4.36.0 (175267)"' });
  const items = byId(await sdk.checkPrerequisites(1));
  assert.equal(items.docker.detail, 'Docker Desktop 4.36.0 · Engine 27.3');
});

test('Docker not installed (A2b): the fix links to Docker Desktop; the daemon waits; disk is still checked', linuxOnly, async (t) => {
  fakeDocker(t, { version: 'exit 127', info: 'exit 1' });
  const result = await sdk.checkPrerequisites(1);
  const items = byId(result);
  assert.equal(result.status, 'error');
  assert.equal(result.dockerReady, false);
  assert.deepEqual(items.docker, {
    id: 'docker',
    label: 'Docker',
    group: 'required',
    status: 'error',
    detail: 'Not installed',
    fix: {
      text: 'Docker runs the SDK container on this computer. Install Docker Desktop, start it once, then Check again.',
      link: { label: 'Install Docker Desktop', url: 'https://docs.docker.com/desktop/' },
    },
  });
  assert.deepEqual(items.daemon, { id: 'daemon', label: 'Docker daemon', group: 'required', status: 'skip', detail: 'Checked after Docker is installed' });
  assert.match(items.disk.detail, /GB free · needs ~1 GB$/);
});

test('Docker daemon not running (A2c): the Linux fix starts it with systemctl', linuxOnly, async (t) => {
  fakeDocker(t, { info: 'echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock." >&2; exit 1' });
  const result = await sdk.checkPrerequisites(1);
  const items = byId(result);
  assert.equal(result.dockerReady, false);
  assert.equal(items.docker.detail, 'Docker 29.9.3', 'the client version while the engine is down');
  assert.deepEqual(items.daemon, {
    id: 'daemon',
    label: 'Docker daemon',
    group: 'required',
    status: 'error',
    detail: 'Not running',
    fix: { text: 'Docker is installed but not running. Start it with `sudo systemctl start docker`, then Check again.' },
  });
});

test('Docker not allowed for this user: the fix adds the user to the docker group', linuxOnly, async (t) => {
  fakeDocker(t, { info: 'echo "permission denied while trying to connect to the Docker daemon socket" >&2; exit 1' });
  const items = byId(await sdk.checkPrerequisites(1));
  assert.equal(items.daemon.status, 'error');
  assert.equal(items.daemon.detail, 'Not allowed for your user');
  assert.equal(items.daemon.fix.text, 'Your user isn’t allowed to use Docker. Run `sudo usermod -aG docker $USER`, then log out and back in.');
});

test('not enough disk space (A2d) is an error with how much to free', linuxOnly, async (t) => {
  const root = tempDir(t);
  fakeDocker(t, { info: `echo "29.9.3|${root}|Ubuntu 24.04.5 LTS"` });
  const free = Math.round((fs.statfsSync(root).bavail * fs.statfsSync(root).bsize) / 1e9);
  const required = free + 7;
  const result = await sdk.checkPrerequisites(required);
  const { disk } = byId(result);
  assert.equal(result.status, 'error');
  assert.equal(disk.status, 'error');
  assert.equal(disk.detail, `${free} GB free · needs ~${required} GB`);
  assert.deepEqual(disk.fix, { text: 'Free up about 7 GB, then Check again.' });
});
