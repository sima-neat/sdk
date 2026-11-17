'use strict';

// A minimal MCP server (Streamable HTTP transport, JSON responses only) that
// offers tools to coding agents. It listens on 127.0.0.1 and requires a bearer
// token. No vscode dependency: tools are plain objects.
//
// A tool is { name, description, inputSchema, run(args) }, where run resolves
// with { text, isError } or throws (reported to the agent as a tool error).

const http = require('http');
const crypto = require('crypto');

const PROTOCOL_VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05'];
const MAX_BODY_BYTES = 1024 * 1024;

const RPC = {
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
};

function rpcError(id, code, message) {
  return { jsonrpc: '2.0', id: id === undefined ? null : id, error: { code, message } };
}

function rpcResult(id, result) {
  return { jsonrpc: '2.0', id, result };
}

/**
 * Handles one JSON-RPC message. Resolves with the response, or undefined for
 * a notification.
 */
async function handleMessage(message, { tools, serverInfo, instructions, onCall }) {
  if (!message || typeof message !== 'object' || message.jsonrpc !== '2.0' || typeof message.method !== 'string') {
    return rpcError(message && message.id, RPC.INVALID_REQUEST, 'Invalid JSON-RPC request');
  }
  const isNotification = message.id === undefined || message.id === null;
  if (isNotification) {
    // notifications/initialized, notifications/cancelled: nothing to do.
    return undefined;
  }
  const { id, method, params = {} } = message;
  switch (method) {
    case 'initialize': {
      const requested = params.protocolVersion;
      return rpcResult(id, {
        protocolVersion: PROTOCOL_VERSIONS.includes(requested) ? requested : PROTOCOL_VERSIONS[0],
        capabilities: { tools: { listChanged: false } },
        serverInfo,
        instructions,
      });
    }
    case 'ping':
      return rpcResult(id, {});
    case 'tools/list':
      return rpcResult(id, { tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })) });
    case 'tools/call': {
      const tool = tools.find((candidate) => candidate.name === params.name);
      if (!tool) {
        return rpcError(id, RPC.INVALID_PARAMS, `Unknown tool: ${params.name}`);
      }
      let outcome;
      try {
        outcome = await tool.run(params.arguments || {});
      } catch (error) {
        outcome = { text: error && error.message ? error.message : String(error), isError: true };
      }
      if (onCall) {
        onCall(tool.name, params.arguments || {}, outcome);
      }
      return rpcResult(id, { content: [{ type: 'text', text: outcome.text }], isError: Boolean(outcome.isError) });
    }
    default:
      return rpcError(id, RPC.METHOD_NOT_FOUND, `Method not found: ${method}`);
  }
}

function tokenMatches(header, token) {
  const match = /^Bearer\s+(.+)$/i.exec(header || '');
  if (!match) {
    return false;
  }
  const given = Buffer.from(match[1].trim());
  const expected = Buffer.from(token);
  return given.length === expected.length && crypto.timingSafeEqual(given, expected);
}

function reply(status, body, headers = {}) {
  const text = body === undefined ? '' : JSON.stringify(body);
  return { status, headers: text ? { 'Content-Type': 'application/json', ...headers } : headers, body: text };
}

/**
 * Answers one HTTP request, given as { method, path, headers, body } with
 * lower-case header names and the body as a string. Resolves with
 * { status, headers, body }. Used by the 127.0.0.1 listener and by the relay
 * that serves an SDK container over docker exec.
 */
function createResponder({ tools, serverInfo, instructions, onCall, token }) {
  return async ({ method, path, headers = {}, body = '' }) => {
    // Only local agents: reject other host names (DNS rebinding) and browsers.
    const host = (headers.host || '').replace(/:\d+$/, '');
    if (!['127.0.0.1', 'localhost'].includes(host) || headers.origin) {
      return reply(403, rpcError(null, RPC.INVALID_REQUEST, 'Forbidden'));
    }
    if (!tokenMatches(headers.authorization, token)) {
      return reply(401, rpcError(null, RPC.INVALID_REQUEST, 'Unauthorized'), { 'WWW-Authenticate': 'Bearer' });
    }
    if ((path || '').split('?')[0] !== '/mcp') {
      return reply(404, rpcError(null, RPC.INVALID_REQUEST, 'Not found'));
    }
    if (method !== 'POST') {
      // No server-initiated stream and no sessions.
      return reply(405, undefined, { Allow: 'POST' });
    }
    if (Buffer.byteLength(body) > MAX_BODY_BYTES) {
      return reply(413, rpcError(null, RPC.INVALID_REQUEST, 'Request too large'));
    }
    let message;
    try {
      message = JSON.parse(body);
    } catch {
      return reply(400, rpcError(null, RPC.PARSE_ERROR, 'Parse error'));
    }
    const options = { tools, serverInfo, instructions, onCall };
    const responses = Array.isArray(message)
      ? (await Promise.all(message.map((item) => handleMessage(item, options)))).filter(Boolean)
      : [await handleMessage(message, options)].filter(Boolean);
    if (responses.length === 0) {
      return reply(202);
    }
    return reply(200, Array.isArray(message) ? responses : responses[0]);
  };
}

/** Serves a responder over node's http. */
function httpHandler(respond) {
  return (req, res) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', async () => {
      const answer = await respond({
        method: req.method,
        path: req.url,
        headers: req.headers,
        body: Buffer.concat(chunks).toString('utf8'),
      });
      res.writeHead(answer.status, { ...answer.headers, 'Content-Length': Buffer.byteLength(answer.body) });
      res.end(answer.body);
    });
  };
}

/**
 * Starts the server on a free port of 127.0.0.1. Resolves with
 * { port, token, url, respond, close() }; respond can serve other transports.
 */
function startMcpServer({ tools, serverInfo, instructions, onCall, token = crypto.randomBytes(24).toString('hex') }) {
  const respond = createResponder({ tools, serverInfo, instructions, onCall, token });
  const server = http.createServer(httpHandler(respond));
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        port,
        token,
        url: `http://127.0.0.1:${port}/mcp`,
        respond,
        close: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

module.exports = { startMcpServer, createResponder, httpHandler, handleMessage, PROTOCOL_VERSIONS };
