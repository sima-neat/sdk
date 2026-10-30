const test = require('node:test');
const assert = require('node:assert/strict');
const {STATE_URL, parseState, fetchState, RegistryState} = require('../src/registry-state');
const alpha = {current_state:'Alpha', default_branch:'develop'};
const ga = {current_state:'GA', default_branch:'main'};

test('release contract accepts the enums and rejects invalid or partial documents', () => {
  for (const current_state of ['GA', 'Beta', 'Alpha']) {
    for (const default_branch of ['develop', 'main']) {
      assert.deepEqual(parseState({current_state, default_branch}), {current_state, default_branch});
    }
  }
  for (const value of [null, [], {}, {...alpha,current_state:'<script>'}, {...alpha,default_branch:'other'}]) {
    assert.throws(() => parseState(value));
  }
});
test('fetch uses the production endpoint and rejects HTTP, JSON and oversized responses', async () => {
  assert.deepEqual(await fetchState(async (url, options) => {
    assert.equal(url, STATE_URL);
    assert.equal(url, 'https://artifacts.neat.sima.ai/models/state.json');
    assert.equal(options.redirect, 'error');
    assert.ok(options.signal);
    return new Response(JSON.stringify(alpha));
  }), alpha);
  for (const response of [new Response('', {status:403}), new Response('broken'), new Response('x'.repeat(4097))]) {
    await assert.rejects(fetchState(async () => response));
  }
});
test('refresh deduplicates requests, picks up changes and retains last valid state on failure', async () => {
  let next = alpha, calls = 0;
  const state = new RegistryState(async () => { calls++; return next; });
  assert.equal(state.snapshot().current_state, null);
  assert.equal(state.snapshot().default_branch, 'develop');
  const updates = [];
  const subscription = state.subscribe(value => updates.push(value));
  await Promise.all([state.refresh(), state.refresh()]);
  assert.equal(calls, 1);
  assert.deepEqual(state.snapshot(), alpha);
  next = ga;
  assert.deepEqual(await state.refresh(), ga);
  next = {};
  assert.deepEqual(await state.refresh(), ga);
  assert.equal(updates.length, 2);
  subscription.dispose();
  state.dispose();
  await state.refresh();
  assert.equal(calls, 3);
});
test('initial outage leaves the release unknown, and disposed pending requests cannot update views', async () => {
  const failed = new RegistryState(async () => {throw Error('offline');});
  assert.equal((await failed.refresh()).current_state, null);
  failed.dispose();
  let finish;
  const state = new RegistryState(() => new Promise(resolve => {finish = resolve;}));
  state.subscribe(() => assert.fail('disposed listener'));
  const pending = state.refresh();
  await Promise.resolve();
  state.dispose();
  finish(ga);
  await pending;
  assert.equal(state.snapshot().current_state, null);
});
