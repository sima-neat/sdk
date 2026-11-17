'use strict';

// The relay that serves agent tools inside an SDK container (agents/relay.js),
// started and restarted by agents/containerLink.js over `docker exec`.
//
// The first test needs no Docker: a fake `docker` runs the "container"
// commands on this computer, with HOME in a temporary folder.
// The second runs against a real, running SDK container, only when you name
// one; it uses its own folder there (~/.sima-neat-vscode-test), so a VS Code
// window attached to that container keeps working:
//   SIMA_NEAT_TEST_CONTAINER=<container name> [SIMA_NEAT_TEST_USER=<user>] npm test

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { AGENTS, tempDir, sampleTools, toolsFile, rpc, callTool, run, askBridge, textOf } = require('./helpers');
const { createResponder } = require(path.join(AGENTS, 'mcpServer.js'));
const { startContainerLink } = require(path.join(AGENTS, 'containerLink.js'));

const TOKEN = 't'.repeat(48);
const WINDOW_PID = 4242;

const FAKE_DOCKER = `#!/bin/sh
# Fake docker for tests: runs "docker exec [-i] [-u user] [-e K=V]... <container> <command>..." here.
[ "$1" = exec ] || { echo "fake docker: only exec" >&2; exit 1; }
shift
while [ $# -gt 0 ]; do
  case "$1" in
    -i) shift ;;
    -u) shift 2 ;;
    -e) export "$2"; shift 2 ;;
    *) break ;;
  esac
done
shift
exec "$@"
`;

async function until(check, what, timeoutMs = 15000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (await check()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${what}`);
}

const mode = (file) => (fs.statSync(file).mode & 0o777).toString(8);

function files(tools) {
  const read = (name) => fs.readFileSync(path.join(AGENTS, name), 'utf8');
  return { 'relay.js': read('relay.js'), 'bridge.js': read('bridge.js'), 'tools.json': toolsFile(tools) };
}

test('relay over docker exec: install, calls, restart, close', { skip: process.platform === 'win32' && 'needs a POSIX shell', timeout: 60000 }, async (t) => {
  const home = tempDir(t);
  const bin = path.join(home, 'bin');
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'docker'), FAKE_DOCKER, { mode: 0o755 });
  const saved = { HOME: process.env.HOME, PATH: process.env.PATH };
  process.env.HOME = home;
  process.env.PATH = [bin, path.dirname(process.execPath), process.env.PATH].join(path.delimiter);

  const calls = [];
  const tools = sampleTools(calls);
  const logs = [];
  const link = await startContainerLink({
    target: { name: 'sdk', user: os.userInfo().username },
    respond: createResponder({ tools, serverInfo: { name: 'test', version: '1' }, token: TOKEN }),
    files: files(tools),
    windowPid: WINDOW_PID,
    log: (line) => logs.push(line),
  });
  let disposed = false;
  t.after(() => {
    if (!disposed) {
      link.dispose();
    }
    Object.assign(process.env, saved);
  });

  const dir = path.join(home, '.sima-neat-vscode');
  const socket = path.join(dir, `${WINDOW_PID}.sock`);
  const windowFile = path.join(dir, 'windows', `${WINDOW_PID}.json`);
  assert.equal(link.dir, dir);
  const running = () => logs.filter((line) => line === 'Relay running in container sdk.').length;
  await until(() => running() === 1, 'the relay to start');
  link.update({ pid: WINDOW_PID, token: TOKEN, container: 'sdk', focusedAt: Date.now(), folders: ['/workspace'] });
  await until(() => fs.existsSync(windowFile), 'the window file');

  assert.equal(mode(dir), '700');
  assert.equal(mode(path.join(dir, 'bridge.js')), '600');
  assert.equal(mode(windowFile), '600');
  assert.equal(mode(socket), '600');
  assert.equal(JSON.parse(fs.readFileSync(windowFile, 'utf8')).socket, `${WINDOW_PID}.sock`);

  const bridge = (messages) => askBridge(path.join(dir, 'bridge.js'), messages,
    { env: { SIMA_NEAT_VSCODE_DIR: dir, SIMA_NEAT_CONTAINER: 'sdk' } });

  let { answers } = await bridge([rpc(1, 'initialize', { protocolVersion: '2025-06-18' }), rpc(2, 'tools/list'), callTool(3, 'open_insight'), callTool(4, 'open_insight')]);
  assert.equal(answers.get(2).result.tools.length, 2);
  assert.deepEqual([textOf(answers.get(3)), textOf(answers.get(4))].sort(), ['Opened Insight #1', 'Opened Insight #2']);

  // The relay stops (say the container restarted): the window starts it again.
  await run('pkill', ['-f', `${dir}/[r]elay[.]js`]);
  await until(() => running() === 2, 'the relay to restart');
  assert.ok(logs.some((line) => /stopped .*restarting in 2 s/.test(line)), logs.join('\n'));
  await until(() => fs.existsSync(windowFile), 'the window file after the restart');
  ({ answers } = await bridge([callTool(5, 'open_insight')]));
  assert.equal(textOf(answers.get(5)), 'Opened Insight #3');

  // The window closes: the relay removes its socket and window file.
  link.dispose();
  disposed = true;
  await until(() => !fs.existsSync(socket) && !fs.existsSync(windowFile), 'the relay to clean up');
  ({ answers } = await bridge([callTool(6, 'open_insight')]));
  assert.match(textOf(answers.get(6)), /attached to this SDK container \(sdk\)/);
  assert.equal(calls.length, 3);
});

const CONTAINER = process.env.SIMA_NEAT_TEST_CONTAINER;

test('relay in a real SDK container', { skip: !CONTAINER && 'set SIMA_NEAT_TEST_CONTAINER to run it', timeout: 60000 }, async (t) => {
  const user = process.env.SIMA_NEAT_TEST_USER || os.userInfo().username;
  const target = { name: CONTAINER, user };
  const dirName = '.sima-neat-vscode-test';
  const calls = [];
  const tools = sampleTools(calls);
  const logs = [];
  const link = await startContainerLink({
    target,
    respond: createResponder({ tools, serverInfo: { name: 'test', version: '1' }, token: TOKEN }),
    files: files(tools),
    windowPid: WINDOW_PID,
    log: (line) => logs.push(line),
    dirName,
  });
  t.after(async () => {
    link.dispose();
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await run('docker', ['exec', '-u', user, CONTAINER, 'rm', '-rf', link.dir]);
  });
  assert.equal(path.posix.basename(link.dir), dirName);
  await until(() => logs.includes(`Relay running in container ${CONTAINER}.`), 'the relay to start');
  link.update({ pid: WINDOW_PID, token: TOKEN, container: CONTAINER, focusedAt: Date.now(), folders: ['/workspace'] });

  const bridge = (messages) => askBridge(`${link.dir}/bridge.js`, messages, {
    command: ['docker', 'exec', '-i', '-u', user, '-e', `SIMA_NEAT_VSCODE_DIR=${link.dir}`, '-e', `SIMA_NEAT_CONTAINER=${CONTAINER}`, CONTAINER, link.node],
  });
  await until(async () => {
    const { answers } = await bridge([callTool(1, 'open_insight')]);
    return !answers.get(1).result.isError;
  }, 'a call through the container');
  const { answers } = await bridge([rpc(2, 'tools/list'), callTool(3, 'open_insight'), callTool(4, 'open_insight')]);
  assert.equal(answers.get(2).result.tools.length, 2);
  assert.equal(answers.get(3).result.isError, false);
  assert.equal(answers.get(4).result.isError, false);
  assert.equal(calls.length, 3);
});
