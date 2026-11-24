#!/usr/bin/env node
// Execute the workflow's actual script against a fake GitHub API. No mutations
// leave this process, including in tests exercising deletion behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const workflow = fs.readFileSync(path.join(__dirname, '../../.github/workflows/cleanup-packages.yml'), 'utf8');
const script = workflow.split('          script: |\n')[1].split('\n').map(line => line.slice(12)).join('\n');
const execute = new (Object.getPrototypeOf(async function() {}).constructor)('github', 'context', 'core', 'process', script);

async function run({dryRun = false, foreign = false, unknown = false, requested = '', branches} = {}) {
  const deleted = [];
  const sha = 'a'.repeat(40);
  const versions = [
    {id: 1, metadata: {container: {tags: ['codex-lost']}}},
    {id: 2, metadata: {container: {tags: ['codex-lost', 'v3.0.0']}}},
    {id: 3, metadata: {container: {tags: ['latest', 'main', 'develop', 'v3.0-latest']}}},
    {id: 4, metadata: {container: {tags: ['codex-live']}}},
    {id: 5, metadata: {container: {tags: [sha, `${sha}-aarch64`, `staged-${sha}`]}}},
  ];
  // The canonical PIB package also holds the pib-sbp image next to each tag, as <tag>-sbp.
  const sbpVersions = [
    {id: 6, metadata: {container: {tags: [`${sha}-sbp`, `staged-${sha}-sbp`, 'latest-sbp']}}},
    {id: 7, metadata: {container: {tags: ['main-sbp']}}},
    {id: 8, metadata: {container: {tags: [`${sha}-aarch64-sbp`]}}},
    {id: 9, metadata: {container: {tags: ['v3.0.0-sbp', 'v3.0-latest-sbp']}}},
    {id: 10, metadata: {container: {tags: ['develop-sbp']}}},
    {id: 11, metadata: {container: {tags: ['codex-live-sbp']}}},
    {id: 12, metadata: {container: {tags: ['codex-lost-sbp']}}},
  ];
  const github = {
    async request(route, args) {
      if (route.startsWith('DELETE')) { deleted.push(args); return {}; }
      if (route.includes('/actions/workflows/')) return {data: {workflow_runs: [{head_branch: 'codex/Lost', head_sha: sha, event: 'push'}]}};
      if (args.package_name === 'sdk-buildcache') throw {status: 404};
      return {data: {repository: unknown ? undefined : {full_name: foreign ? 'other/repo' : 'sima-neat/sdk'}}};
    },
    async paginate(route, args) {
      if (route.endsWith('/branches')) return branches || [{name: 'main'}, {name: 'develop'}, {name: 'codex/Live'}];
      if (args.package_name.endsWith('-codex-lost')) return [{metadata: {container: {tags: [sha]}}}];
      if (args.package_name === 'palette-image-builder') return [...versions, ...sbpVersions];
      return versions;
    },
  };
  await execute(github, {repo: {owner: 'sima-neat', repo: 'sdk'}, eventName: 'schedule'},
    {info() {}, warning() {}}, {env: {DRY_RUN: String(dryRun), REQUESTED_BRANCH: requested}});
  return deleted;
}

test('cleans both deleted branch packages and canonical branch-only versions', async () => {
  const deleted = await run();
  assert.deepEqual(deleted.map(d => [d.package_name, d.package_version_id]), [
    ['sdk-codex-lost', undefined], ['sdk', 1],
    ['palette-image-builder-codex-lost', undefined], ['palette-image-builder', 1],
    ['palette-image-builder', 12],
  ]);
});
test('dry run never mutates packages', async () => assert.deepEqual(await run({dryRun: true}), []));
test('foreign package ownership prevents deletion', async () => assert.deepEqual(await run({foreign: true}), []));
test('unknown ownership requires a workflow commit match and skips canonical cleanup', async () => {
  assert.deepEqual((await run({unknown: true})).map(d => d.package_name),
    ['sdk-codex-lost', 'palette-image-builder-codex-lost']);
});
test('unknown ownership without a workflow commit match prevents deletion', async () => {
  assert.deepEqual(await run({unknown: true, requested: 'codex/Lost'}), []);
});
test('an active branch with a colliding slug preserves its package and alias', async () => {
  const deleted = await run({branches: [{name: 'main'}, {name: 'develop'}, {name: 'codex-lost'}, {name: 'codex/Live'}]});
  assert.deepEqual(deleted, []);
});
test('main never causes wholesale canonical PIB deletion even if absent from branch listing', async () => {
  const deleted = await run({requested: 'main', branches: []});
  assert(!deleted.some(d => d.package_name === 'palette-image-builder' && !d.package_version_id));
});
