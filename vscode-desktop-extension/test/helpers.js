'use strict';

// Shared by the tests. Node.js only: run with `npm test`.

const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');
const { spawn } = require('child_process');

const ROOT = path.join(__dirname, '..');
const AGENTS = path.join(ROOT, 'agents');

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sima-neat-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

/** A tool list with one tool that works and one that throws. */
function sampleTools(calls = []) {
  return [
    {
      name: 'open_insight',
      description: 'Opens Insight.',
      inputSchema: { type: 'object', properties: {} },
      run: async (args) => {
        calls.push(args);
        return { text: `Opened Insight #${calls.length}` };
      },
    },
    {
      name: 'broken',
      description: 'Always fails.',
      inputSchema: { type: 'object', properties: {} },
      run: async () => { throw new Error('kaboom'); },
    },
  ];
}

/** tools.json, as the extension writes it for the bridge. */
function toolsFile(tools) {
  return JSON.stringify({
    version: 'test',
    instructions: 'Test instructions.',
    tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
  });
}

const rpc = (id, method, params) => ({ jsonrpc: '2.0', id, method, ...(params ? { params } : {}) });
const callTool = (id, name) => rpc(id, 'tools/call', { name, arguments: {} });

/**
 * Runs a process, writes `input` to its stdin, and resolves with
 * { code, stdout, stderr }.
 */
function run(command, args, { input = '', env, cwd } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { env: env || process.env, cwd });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (data) => { stdout += data; });
    child.stderr.on('data', (data) => { stderr += data; });
    child.on('error', reject);
    child.on('close', (code) => resolve({ code, stdout, stderr }));
    child.stdin.on('error', () => undefined); // It may exit without reading its input.
    child.stdin.end(input);
  });
}

/** Sends MCP messages to a bridge.js and resolves with its answers, by id. */
async function askBridge(bridgeFile, messages, { env = {}, cwd = os.tmpdir(), command = [process.execPath] } = {}) {
  const input = messages.map((message) => JSON.stringify(message)).join('\n') + '\n';
  const { stdout, stderr } = await run(command[0], [...command.slice(1), bridgeFile], {
    input,
    cwd,
    env: { ...process.env, SIMA_NEAT_VSCODE_WINDOW: '', ...env },
  });
  const answers = new Map();
  for (const line of stdout.split('\n').filter(Boolean)) {
    const answer = JSON.parse(line);
    answers.set(answer.id, answer);
  }
  return { answers, stderr };
}

/** The text a tools/call answer carries. */
const textOf = (answer) => answer.result.content.map((item) => item.text).join('\n');

/**
 * Requires a module of the extension with a stand-in for the `vscode` module,
 * for the parts that can be tested without VS Code.
 */
function requireWithVscode(file, vscode = {}) {
  const original = Module._load;
  Module._load = function load(request, ...rest) {
    return request === 'vscode' ? vscode : original.call(this, request, ...rest);
  };
  try {
    return require(file);
  } finally {
    Module._load = original;
  }
}

module.exports = { ROOT, AGENTS, tempDir, sampleTools, toolsFile, rpc, callTool, run, askBridge, textOf, requireWithVscode };
