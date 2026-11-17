'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('http');
const path = require('path');
const { AGENTS, sampleTools, rpc, callTool } = require('./helpers');
const { createResponder, startMcpServer, PROTOCOL_VERSIONS } = require(path.join(AGENTS, 'mcpServer.js'));

const TOKEN = 'secret-token';

function responder(calls = [], onCall) {
  return createResponder({ tools: sampleTools(calls), serverInfo: { name: 'test', version: '1' }, instructions: 'Hi.', token: TOKEN, onCall });
}

const goodHeaders = { host: '127.0.0.1:1234', authorization: `Bearer ${TOKEN}` };
const post = (respond, body, headers = goodHeaders, extra = {}) =>
  respond({ method: 'POST', path: '/mcp', headers, body: typeof body === 'string' ? body : JSON.stringify(body), ...extra });

test('rejects requests that are not from a local agent', async () => {
  const respond = responder();
  const body = rpc(1, 'ping');
  assert.equal((await post(respond, body, { ...goodHeaders, host: 'evil.example:1234' })).status, 403);
  assert.equal((await post(respond, body, { ...goodHeaders, origin: 'http://evil.example' })).status, 403);
  assert.equal((await post(respond, body, { host: 'localhost' })).status, 401);
  assert.equal((await post(respond, body, { ...goodHeaders, authorization: 'Bearer wrong' })).status, 401);
  assert.equal((await post(respond, body, goodHeaders, { path: '/other' })).status, 404);
  const get = await post(respond, '', goodHeaders, { method: 'GET' });
  assert.equal(get.status, 405);
  assert.equal(get.headers.Allow, 'POST');
  assert.equal((await post(respond, '{not json')).status, 400);
  assert.equal((await post(respond, 'x'.repeat(1024 * 1024 + 1))).status, 413);
});

test('answers initialize with a supported protocol version', async () => {
  const respond = responder();
  for (const version of PROTOCOL_VERSIONS) {
    const answer = JSON.parse((await post(respond, rpc(1, 'initialize', { protocolVersion: version }))).body);
    assert.equal(answer.result.protocolVersion, version);
    assert.equal(answer.result.instructions, 'Hi.');
  }
  const unknown = JSON.parse((await post(respond, rpc(2, 'initialize', { protocolVersion: '1999-01-01' }))).body);
  assert.equal(unknown.result.protocolVersion, PROTOCOL_VERSIONS[0]);
});

test('accepts notifications with 202 and no body', async () => {
  const answer = await post(responder(), { jsonrpc: '2.0', method: 'notifications/initialized' });
  assert.equal(answer.status, 202);
  assert.equal(answer.body, '');
});

test('lists and calls tools', async () => {
  const calls = [];
  const logged = [];
  const respond = responder(calls, (name, args, outcome) => logged.push([name, Boolean(outcome.isError)]));
  const list = JSON.parse((await post(respond, rpc(1, 'tools/list'))).body);
  assert.deepEqual(list.result.tools.map((tool) => tool.name), ['open_insight', 'broken']);
  assert.equal(list.result.tools[0].run, undefined);

  const ok = JSON.parse((await post(respond, callTool(2, 'open_insight'))).body);
  assert.deepEqual(ok.result, { content: [{ type: 'text', text: 'Opened Insight #1' }], isError: false });

  const failed = JSON.parse((await post(respond, callTool(3, 'broken'))).body);
  assert.deepEqual(failed.result, { content: [{ type: 'text', text: 'kaboom' }], isError: true });

  const unknown = JSON.parse((await post(respond, callTool(4, 'nope'))).body);
  assert.equal(unknown.error.code, -32602);

  assert.deepEqual(logged, [['open_insight', false], ['broken', true]]);
});

test('answers batches, without answers for notifications', async () => {
  const answer = await post(responder(), [rpc(1, 'ping'), { jsonrpc: '2.0', method: 'notifications/initialized' }, rpc(2, 'nope')]);
  const answers = JSON.parse(answer.body);
  assert.equal(answers.length, 2);
  assert.deepEqual(answers[0], { jsonrpc: '2.0', id: 1, result: {} });
  assert.equal(answers[1].error.code, -32601);
});

test('serves over HTTP on 127.0.0.1', async (t) => {
  const server = await startMcpServer({ tools: sampleTools(), serverInfo: { name: 'test', version: '1' } });
  t.after(() => server.close());
  assert.equal(server.url, `http://127.0.0.1:${server.port}/mcp`);
  const status = (headers) => new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: server.port, path: '/mcp', method: 'POST', headers }, (res) => {
      res.resume();
      resolve(res.statusCode);
    });
    req.on('error', reject);
    req.end(JSON.stringify(rpc(1, 'ping')));
  });
  assert.equal(await status({}), 401);
  assert.equal(await status({ Authorization: `Bearer ${server.token}` }), 200);
});
