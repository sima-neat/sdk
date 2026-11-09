const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const { createComponentService, resolveComponents } = require('../../scripts/sdk-component-service');
const { ComponentCatalog } = require('../../vscode-extension/src/components');
const fixture = require('../../components.json');
const source = require('node:fs').readFileSync(path.join(__dirname, '../../scripts/sdk-components.js'), 'utf8');
const upstreamVersion = { status: 0, stdout: '4.144.0 hash with Code 1.144.0' };

test('shell resolver uses the actual SDK catalog rules and installed profile', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'sdk-resolver-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const profile = path.join(root, 'extensions.json');
  let options;
  const service = createComponentService({ extensionsDir: root, spawn: () => upstreamVersion,
    Catalog: class extends ComponentCatalog {
      constructor(context, detected) {
        options = detected;
        super({ ...context, globalStorageUri: { fsPath: path.join(root, 'cache') } }, {
          ...detected, releaseText: 'SDK Release = 3.0.0.1',
          fetchCatalog: async () => structuredClone(fixture), execute: async () => ({ stdout: 'codex-cli 0.153.4' }),
        });
      }
    } });
  assert.equal(options.profileFile, profile);
  const resolved = await resolveComponents(service);
  assert.equal(resolved.schema_version, 1);
  assert.equal(resolved.sdk_release, '3.0.0.1');
  assert.equal(resolved.extensions['anthropic.claude-code'], fixture.sdks['3.0.0'].components.claude.version);
  assert.equal(resolved.code_server, '4.144.0');
  await assert.rejects(service.verifyInstalled(fixture.sdks['3.0.0'].components.claude), /pin/);
  const claude = fixture.sdks['3.0.0'].components.claude;
  await fs.writeFile(profile, JSON.stringify([{ identifier: { id: claude.id }, version: claude.version, metadata: { pinned: true } }]));
  await service.verifyInstalled(claude);
});

test('resolver propagates unknown, revoked, candidate and engine policy failures', async () => {
  for (const error of ['No compatible component mapping', 'components are revoked', 'components are candidate', 'engine pair has not been qualified']) {
    await assert.rejects(resolveComponents({ refresh: async () => ({ available: false, error }) }), { message: error });
  }
  assert.throws(() => createComponentService({ spawn: () => ({ status: 1 }) }), /detect code-server/);
  assert.throws(() => createComponentService({ spawn: () => ({ status: 0, stdout: '4.144.0' }) }), /detect VS Code/);
});

async function run(args, { state, failure = false } = {}) {
  const output = [], diagnostics = [], calls = [];
  const process = { argv: ['node', 'sdk-components', ...args], stderr: { write: x => diagnostics.push(x) } };
  await vm.runInNewContext(source, { process, console: { log: x => output.push(JSON.parse(x)) }, require: name => {
    if (name === '/usr/local/lib/sima-sdk/component-service.js') return {
      createComponentService: () => ({}), resolveComponents: async () => {
        if (failure) throw Error('No qualified mapping');
        return state;
      },
    };
    if (name === 'node:child_process') return { spawnSync: (file, args) => {
      calls.push({ file, args });
      return { status: failure ? 1 : 0, stdout: 'installer details', stderr: '' };
    } };
    return require(name);
  } });
  return { output: JSON.parse(JSON.stringify(output)), diagnostics, calls: JSON.parse(JSON.stringify(calls)), code: process.exitCode };
}
test('resolve is structured and a policy failure is nonzero JSON', async () => {
  const state = { schema_version: 1, available: true, extensions: { 'anthropic.claude-code': '2.1.316' } };
  assert.deepEqual((await run(['resolve', '--json'], { state })).output, [state]);
  const blocked = await run(['resolve', '--json'], { failure: true });
  assert.equal(blocked.code, 1);
  assert.equal(blocked.output[0].available, false);
  assert.match(blocked.output[0].error, /qualified/);
});
test('install requires an expected exact managed version and delegates to the enforcing wrapper', async () => {
  const args = ['install', '--json', '--extension', 'anthropic.claude-code@2.1.316', '--extensions-dir', '/home/alice/extensions'];
  const result = await run(args);
  assert.equal(result.output[0].installed, true);
  assert.deepEqual(result.calls[0], { file: '/opt/code-server/bin/code-server', args: ['--extensions-dir', args[5], '--install-extension', args[3], '--force'] });
  assert.deepEqual(result.diagnostics, ['installer details']);
  const failed = await run(args, { failure: true });
  assert.equal(failed.code, 1);
  assert.equal(failed.output[0].installed, undefined);
  for (const invalid of ['anthropic.claude-code', 'anthropic.claude-code@latest', 'other.extension@1.2.3']) {
    const blocked = await run(['install', '--json', '--extension', invalid, '--extensions-dir', '/home/alice/extensions']);
    assert.equal(blocked.code, 1);
    assert.equal(blocked.calls.length, 0);
  }
});
