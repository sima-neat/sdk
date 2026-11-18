'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { AGENTS, tempDir, sampleTools, toolsFile, rpc, callTool, run, askBridge, textOf } = require('./helpers');
const { startMcpServer } = require(path.join(AGENTS, 'mcpServer.js'));

const BRIDGE = path.join(AGENTS, 'bridge.js');

function stateDir(t, { tools } = {}) {
  const dir = tempDir(t);
  fs.mkdirSync(path.join(dir, 'windows'));
  if (tools) {
    fs.writeFileSync(path.join(dir, 'tools.json'), toolsFile(tools));
  }
  return dir;
}

const writeWindow = (dir, data) => fs.writeFileSync(path.join(dir, 'windows', `${data.pid}.json`), JSON.stringify(data));

test('without tools.json or a window: no tools, and calls say VS Code is not open', async (t) => {
  const dir = stateDir(t);
  const { answers } = await askBridge(BRIDGE, [rpc(1, 'initialize', { protocolVersion: '2025-03-26' }), rpc(2, 'tools/list'), callTool(3, 'open_insight')],
    { env: { SIMA_NEAT_VSCODE_DIR: dir } });
  assert.equal(answers.get(1).result.protocolVersion, '2025-03-26');
  assert.deepEqual(answers.get(2).result.tools, []);
  assert.equal(answers.get(3).result.isError, true);
  assert.match(textOf(answers.get(3)), /No VS Code window with SiMa Neat Studio is open/);
});

test('lists tools from tools.json and passes calls to a live window', async (t) => {
  const tools = sampleTools();
  const dir = stateDir(t, { tools });
  const server = await startMcpServer({ tools, serverInfo: { name: 'test', version: '1' } });
  t.after(() => server.close());
  writeWindow(dir, { pid: 999999999, port: 1, token: 'x', focusedAt: 9 }); // Gone: its process isn't running.
  writeWindow(dir, { pid: process.ppid, port: 1, token: 'x', focusedAt: 8 }); // Running, but nothing listens.
  writeWindow(dir, { pid: process.pid, port: server.port, token: server.token, focusedAt: 1 });

  const { answers, stderr } = await askBridge(BRIDGE, [
    rpc(1, 'initialize', { protocolVersion: '2025-06-18' }),
    { jsonrpc: '2.0', method: 'notifications/initialized' },
    rpc(2, 'tools/list'),
    callTool(3, 'open_insight'),
    callTool(4, 'broken'),
    callTool(5, 'nope'),
  ], { env: { SIMA_NEAT_VSCODE_DIR: dir } });

  assert.equal(stderr, '');
  assert.equal(answers.size, 5);
  assert.equal(answers.get(1).result.instructions, 'Test instructions.');
  assert.deepEqual(answers.get(2).result.tools.map((tool) => tool.name), ['open_insight', 'broken']);
  assert.equal(textOf(answers.get(3)), 'Opened Insight #1');
  assert.equal(answers.get(4).result.isError, true);
  assert.equal(textOf(answers.get(4)), 'kaboom');
  assert.equal(answers.get(5).error.code, -32602);
});

test('in a container, uses only windows attached to that container', async (t) => {
  const dir = stateDir(t, { tools: sampleTools() });
  writeWindow(dir, { pid: 1, socket: '1.sock', token: 'x', container: 'other-container', focusedAt: 9 });
  const { answers } = await askBridge(BRIDGE, [callTool(1, 'open_insight')],
    { env: { SIMA_NEAT_VSCODE_DIR: dir, SIMA_NEAT_CONTAINER: 'my-container' } });
  assert.match(textOf(answers.get(1)), /attached to this SDK container \(my-container\)/);
});

test('picks the named window, then the folder match, then the latest focus', async (t) => {
  const dir = stateDir(t);
  const projects = path.join(dir, 'projects');
  fs.mkdirSync(path.join(projects, 'app'), { recursive: true });
  // Both are running processes: this test and its parent.
  writeWindow(dir, { pid: process.pid, port: 1, token: 'x', folders: [projects], focusedAt: 1 });
  writeWindow(dir, { pid: process.ppid, port: 1, token: 'x', folders: [dir], focusedAt: 5 });
  const order = async (cwd, named = '') => {
    const script = `console.log(require(${JSON.stringify(BRIDGE)}).windowsInOrder().map((w) => w.pid).join(','))`;
    const { stdout } = await run(process.execPath, ['-e', script], { cwd, env: { ...process.env, SIMA_NEAT_VSCODE_DIR: dir, SIMA_NEAT_VSCODE_WINDOW: named } });
    return stdout.trim();
  };
  const [mine, parent] = [String(process.pid), String(process.ppid)];
  assert.equal(await order(path.dirname(dir)), `${parent},${mine}`, 'no folder matches: latest focus');
  assert.equal(await order(path.join(projects, 'app')), `${mine},${parent}`, 'deepest folder match');
  assert.equal(await order(path.join(projects, 'app'), parent), `${parent},${mine}`, 'named window');
});
