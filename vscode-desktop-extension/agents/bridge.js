'use strict';

// sima-neat-vscode: the MCP server agents start (stdio), which passes tool
// calls to a VS Code window. Each VS Code window with SiMa Neat Studio runs a
// small HTTP MCP server and writes a discovery file; this bridge picks the
// window to use for each call:
//   1. the one named by SIMA_NEAT_VSCODE_WINDOW (set in that window's terminals);
//   2. else the one whose workspace folder contains the agent's working folder;
//   3. else the one focused most recently.
// Inside an SDK container the bridge runs from the container's own
// ~/.sima-neat-vscode (SIMA_NEAT_VSCODE_DIR) and only uses windows attached to
// its own container (SIMA_NEAT_CONTAINER). The container can't reach the
// host's 127.0.0.1, so each such window runs relay.js there, which serves a
// Unix socket in that folder and passes requests to the window over docker exec.
// The extension copies this file to ~/.sima-neat-vscode/bridge.js, so agent
// configuration keeps working across extension updates. Node.js only, no
// dependencies. Never write anything but MCP messages to stdout.

const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const readline = require('readline');

const STATE_DIR = process.env.SIMA_NEAT_VSCODE_DIR || path.join(os.homedir(), '.sima-neat-vscode');
const WINDOWS_DIR = path.join(STATE_DIR, 'windows');
const TOOLS_FILE = path.join(STATE_DIR, 'tools.json');
const CALL_TIMEOUT_MS = 120000;
const CONTAINER = process.env.SIMA_NEAT_CONTAINER || '';
const NO_WINDOW = CONTAINER
  ? `No VS Code window with SiMa Neat Studio is attached to this SDK container (${CONTAINER}). Ask the user to open the SDK in VS Code, then try again.`
  : 'No VS Code window with SiMa Neat Studio is open. Ask the user to open VS Code, then try again.';

function log(message) {
  process.stderr.write(`[sima-neat-vscode] ${message}\n`);
}

function write(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return undefined;
  }
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

function contains(folder, file) {
  const relative = path.relative(folder, file);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

/** Open windows, best first. */
function windowsInOrder() {
  let names = [];
  try {
    names = fs.readdirSync(WINDOWS_DIR).filter((name) => name.endsWith('.json'));
  } catch {
    return [];
  }
  const windows = names
    .map((name) => readJson(path.join(WINDOWS_DIR, name)))
    .filter((win) => win && win.token && (win.socket || win.port))
    .filter((win) => !CONTAINER || win.container === CONTAINER)
    // A window across a container boundary has a process ID from the host:
    // can't check it from here, so a gone window shows as a missing socket.
    .filter((win) => win.socket || isAlive(win.pid));
  const cwd = process.cwd();
  const named = Number(process.env.SIMA_NEAT_VSCODE_WINDOW);
  const folderMatch = (win) => Math.max(0, ...(win.folders || []).filter((folder) => contains(folder, cwd)).map((folder) => folder.length));
  return windows.sort((a, b) =>
    (b.pid === named) - (a.pid === named)
    || folderMatch(b) - folderMatch(a)
    || (b.focusedAt || 0) - (a.focusedAt || 0));
}

function post(win, message) {
  const body = JSON.stringify(message);
  return new Promise((resolve, reject) => {
    const where = win.socket
      ? { socketPath: path.join(STATE_DIR, win.socket), host: 'localhost' }
      : { host: '127.0.0.1', port: win.port };
    const req = http.request({
      ...where,
      path: '/mcp',
      method: 'POST',
      timeout: CALL_TIMEOUT_MS,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
        Authorization: `Bearer ${win.token}`,
        'Content-Length': Buffer.byteLength(body),
      },
    }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        if (res.statusCode === 202 || !text) {
          resolve(undefined);
          return;
        }
        try {
          resolve(JSON.parse(text));
        } catch {
          reject(new Error(`VS Code answered ${res.statusCode}: ${text.slice(0, 200)}`));
        }
      });
    });
    req.on('timeout', () => req.destroy(new Error('VS Code did not answer in time.')));
    req.on('error', reject);
    req.end(body);
  });
}

/** Sends to the best window; moves on to the next one if a window is gone. */
async function forward(message) {
  const windows = windowsInOrder();
  let lastError;
  for (const win of windows) {
    try {
      return await post(win, message);
    } catch (error) {
      lastError = error;
      if (!['ECONNREFUSED', 'ECONNRESET', 'ENOENT'].includes(error.code)) {
        break;
      }
    }
  }
  throw lastError || new Error(NO_WINDOW);
}

function toolError(id, text) {
  return { jsonrpc: '2.0', id, result: { content: [{ type: 'text', text }], isError: true } };
}

async function handle(message) {
  const { id, method, params = {} } = message;
  if (id === undefined || id === null) {
    return undefined;
  }
  const known = readJson(TOOLS_FILE) || {};
  switch (method) {
    case 'initialize':
      return {
        jsonrpc: '2.0',
        id,
        result: {
          protocolVersion: params.protocolVersion || '2025-06-18',
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: 'sima-neat-vscode', version: known.version || '0.0.0' },
          instructions: known.instructions,
        },
      };
    case 'ping':
      return { jsonrpc: '2.0', id, result: {} };
    case 'tools/list':
      // The extension writes its tools here, so agents see them even when
      // VS Code starts after the agent.
      if (Array.isArray(known.tools)) {
        return { jsonrpc: '2.0', id, result: { tools: known.tools } };
      }
      return forward(message).catch(() => ({ jsonrpc: '2.0', id, result: { tools: [] } }));
    case 'tools/call':
      return forward(message).catch((error) => toolError(id, error.message === NO_WINDOW ? NO_WINDOW : `Couldn't reach VS Code: ${error.message}`));
    default:
      return forward(message).catch(() => ({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } }));
  }
}

function main() {
  const pending = new Set();
  const input = readline.createInterface({ input: process.stdin });
  input.on('line', (line) => {
    if (!line.trim()) {
      return;
    }
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      write({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } });
      return;
    }
    const task = handle(message)
      .then((response) => response && write(response))
      .catch((error) => log(error.stack || error.message))
      .finally(() => pending.delete(task));
    pending.add(task);
  });
  input.on('close', async () => {
    await Promise.all([...pending]);
    process.exit(0);
  });
}

if (require.main === module) {
  main();
}

module.exports = { windowsInOrder, handle };
