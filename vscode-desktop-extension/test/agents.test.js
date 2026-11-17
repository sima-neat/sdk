'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { AGENTS, requireWithVscode } = require('./helpers');

const { isUpToDate } = requireWithVscode(path.join(AGENTS, 'index.js'));

test('a Claude Code registration is up to date only if command, arguments and environment match', () => {
  const wanted = { command: 'node', args: ['/home/me/.sima-neat-vscode/bridge.js'], env: {} };
  const entry = { type: 'stdio', command: 'node', args: ['/home/me/.sima-neat-vscode/bridge.js'], env: {} };
  assert.equal(isUpToDate(entry, wanted), true);
  assert.equal(isUpToDate(undefined, wanted), false, 'not registered');
  assert.equal(isUpToDate({ ...entry, args: ['/old/bridge.js'] }, wanted), false, 'other bridge');
  assert.equal(isUpToDate(entry, { ...wanted, command: '/usr/share/code/code', env: { ELECTRON_RUN_AS_NODE: '1' } }), false, 'other runtime');
  assert.equal(isUpToDate({ ...entry, env: { ELECTRON_RUN_AS_NODE: '1', OTHER: 'x' } }, { ...wanted, env: { ELECTRON_RUN_AS_NODE: '1' } }), true,
    'extra variables the user added are kept');
  const inContainer = { command: '/usr/bin/node', args: ['/home/me/.sima-neat-vscode/bridge.js'], env: { SIMA_NEAT_VSCODE_DIR: '/home/me/.sima-neat-vscode', SIMA_NEAT_CONTAINER: 'sdk' } };
  assert.equal(isUpToDate({ ...inContainer, env: { ...inContainer.env, SIMA_NEAT_CONTAINER: 'old-sdk' } }, inContainer), false, 'other container');
});
