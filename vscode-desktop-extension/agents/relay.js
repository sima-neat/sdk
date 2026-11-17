'use strict';

// Runs inside a Neat SDK container, started by a VS Code window with
//   docker exec -i <container> node ~/.sima-neat-vscode/relay.js <window pid>
// It serves that window's agent tools on a Unix socket in the container's own
// filesystem (~/.sima-neat-vscode/<pid>.sock), where bridge.js finds it, and
// passes each HTTP request to the window over this process's stdin/stdout.
// That works wherever docker exec works (Linux, Docker Desktop on macOS and
// Windows), with no network setup and nothing in the shared workspace.
//
// Lines on stdout, to the window:
//   {"type":"ready"}
//   {"type":"request","id":1,"method":"POST","path":"/mcp","headers":{...},"body":"..."}
// Lines on stdin, from the window:
//   {"type":"window","data":{...}}   written to windows/<pid>.json for bridge.js
//   {"type":"response","id":1,"status":200,"headers":{...},"body":"..."}
// The relay exits when stdin closes: the window closed or docker exec ended.
// Node.js only, no dependencies.

const fs = require('fs');
const path = require('path');
const http = require('http');
const readline = require('readline');

const DIR = __dirname;
const PID = String(process.argv[2] || '').replace(/[^0-9]/g, '');
const SOCKET_NAME = `${PID}.sock`;
const SOCKET = path.join(DIR, SOCKET_NAME);
const WINDOW_FILE = path.join(DIR, 'windows', `${PID}.json`);
const ANSWER_TIMEOUT_MS = 120000;
const MAX_BODY_BYTES = 1024 * 1024;

if (!PID) {
  process.stderr.write('usage: relay.js <window pid>\n');
  process.exit(2);
}

const pending = new Map();
let nextId = 1;

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function cleanUp() {
  fs.rmSync(SOCKET, { force: true });
  fs.rmSync(WINDOW_FILE, { force: true });
}

function finish(res, status, headers, body) {
  if (!res.headersSent) {
    res.writeHead(status, { ...headers, 'Content-Length': Buffer.byteLength(body) });
    res.end(body);
  }
}

const server = http.createServer((req, res) => {
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
  req.on('end', () => {
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      finish(res, 504, { 'Content-Type': 'text/plain' }, 'VS Code did not answer in time.');
    }, ANSWER_TIMEOUT_MS);
    pending.set(id, { res, timer });
    send({ type: 'request', id, method: req.method, path: req.url, headers: req.headers, body: Buffer.concat(chunks).toString('utf8') });
  });
});

function writeWindowFile(data) {
  fs.mkdirSync(path.dirname(WINDOW_FILE), { recursive: true, mode: 0o700 });
  fs.writeFileSync(WINDOW_FILE, `${JSON.stringify({ ...data, socket: SOCKET_NAME }, null, 2)}\n`, { mode: 0o600 });
  fs.chmodSync(WINDOW_FILE, 0o600);
}

const input = readline.createInterface({ input: process.stdin });
input.on('line', (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    return;
  }
  if (message.type === 'window' && message.data) {
    writeWindowFile(message.data);
  } else if (message.type === 'response') {
    const entry = pending.get(message.id);
    if (entry) {
      pending.delete(message.id);
      clearTimeout(entry.timer);
      finish(entry.res, message.status || 500, message.headers || {}, message.body || '');
    }
  }
});
input.on('close', () => {
  cleanUp();
  process.exit(0);
});
for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
  process.on(signal, () => {
    cleanUp();
    process.exit(0);
  });
}

fs.rmSync(SOCKET, { force: true }); // Left over from a relay that was killed.
server.listen(SOCKET, () => {
  fs.chmodSync(SOCKET, 0o600);
  send({ type: 'ready' });
});
server.on('error', (error) => {
  process.stderr.write(`relay: ${error.message}\n`);
  cleanUp();
  process.exit(1);
});
