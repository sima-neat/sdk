'use strict';

// Serves a window's agent tools inside its Neat SDK container, through
// relay.js running there over docker exec (see relay.js). No vscode
// dependency: requests go to respond(), the same one the 127.0.0.1 server uses.

const { spawn } = require('child_process');
const readline = require('readline');

const DIR_NAME = '.sima-neat-vscode';

// Writes the files it gets as JSON on stdin into ~/<folder name given as its
// argument> in the container, readable only by the user, and prints that folder.
const INSTALL_JS = "const fs=require('fs'),p=require('path'),d=p.join(require('os').homedir(),process.argv[1]);"
  + "let s='';process.stdin.on('data',c=>{s+=c}).on('end',()=>{const files=JSON.parse(s);"
  + "fs.mkdirSync(p.join(d,'windows'),{recursive:true,mode:0o700});fs.chmodSync(d,0o700);"
  + "for(const[n,t]of Object.entries(files)){fs.writeFileSync(p.join(d,n),t,{mode:0o600});fs.chmodSync(p.join(d,n),0o600)}"
  + 'process.stdout.write(d)})';

// Node.js in the container: the image's, else VS Code Server's, which is
// there whenever a window is attached.
const FIND_NODE = 'command -v node || ls -1d "$HOME"/.vscode-server/bin/*/node 2>/dev/null | tail -n 1';

// Waits before restarting a relay that stopped: the container may be restarting.
const RESTART_DELAYS_MS = [2000, 5000, 15000, 30000, 60000];

function dockerExec(target, args, { input, timeout = 15000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn('docker', ['exec', '-i', '-u', target.user, target.name, ...args], { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => child.kill('SIGKILL'), timeout);
    child.stdout.on('data', (data) => { stdout += data; });
    child.stderr.on('data', (data) => { stderr += data; });
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error((stderr || stdout || `docker exec exited with ${code}`).trim()));
      }
    });
    // The command may exit without reading its input; 'close' reports how it ended.
    child.stdin.on('error', () => undefined);
    child.stdin.end(input || '');
  });
}

/**
 * Installs the relay and bridge in the container and starts the relay.
 * files: { 'relay.js': text, 'bridge.js': text, 'tools.json': text }.
 * dirName: the folder in the container user's home (tests use their own).
 * Resolves with { dir, node, update(windowData), dispose() } once the files
 * are installed; the relay keeps running (and restarting) until dispose().
 */
async function startContainerLink({ target, respond, files, windowPid, log, dirName = DIR_NAME }) {
  const node = (await dockerExec(target, ['sh', '-c', FIND_NODE])).trim();
  if (!node) {
    throw new Error(`no Node.js in container ${target.name}`);
  }
  const install = () => dockerExec(target, [node, '-e', INSTALL_JS, dirName], { input: JSON.stringify(files) });
  const dir = (await install()).trim();

  let child;
  let windowData;
  let disposed = false;
  let failures = 0;
  let restartTimer;

  const write = (message) => {
    if (child && child.stdin.writable) {
      child.stdin.write(`${JSON.stringify(message)}\n`);
    }
  };

  const handle = async (message) => {
    if (message.type === 'ready') {
      failures = 0;
      log(`Relay running in container ${target.name}.`);
      return;
    }
    if (message.type !== 'request') {
      return;
    }
    let answer;
    try {
      answer = await respond(message);
    } catch (error) {
      answer = { status: 500, headers: { 'Content-Type': 'text/plain' }, body: error.message };
    }
    write({ type: 'response', id: message.id, ...answer });
  };

  const start = () => {
    child = spawn('docker', ['exec', '-i', '-u', target.user, target.name, node, `${dir}/relay.js`, String(windowPid)],
      { stdio: ['pipe', 'pipe', 'pipe'] });
    const current = child;
    readline.createInterface({ input: current.stdout }).on('line', (line) => {
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        return;
      }
      handle(message).catch((error) => log(`Relay request failed: ${error.message}`));
    });
    readline.createInterface({ input: current.stderr }).on('line', (line) => log(`Relay: ${line}`));
    current.stdin.on('error', () => undefined); // The relay went away; 'close' handles it.
    current.on('error', (error) => log(`Relay couldn't start: ${error.message}`));
    current.on('close', (code) => {
      if (disposed || current !== child) {
        return;
      }
      const delay = RESTART_DELAYS_MS[Math.min(failures, RESTART_DELAYS_MS.length - 1)];
      failures += 1;
      log(`Relay in container ${target.name} stopped (exit code ${code}); restarting in ${delay / 1000} s.`);
      restartTimer = setTimeout(async () => {
        try {
          await install(); // A recreated container has lost the files.
        } catch (error) {
          log(`Reinstalling the relay failed: ${error.message}`);
        }
        if (!disposed) {
          start();
        }
      }, delay);
    });
    if (windowData) {
      write({ type: 'window', data: windowData });
    }
  };

  start();

  return {
    dir,
    node,
    update(data) {
      windowData = data;
      write({ type: 'window', data });
    },
    dispose() {
      disposed = true;
      clearTimeout(restartTimer);
      if (child) {
        child.stdin.end(); // The relay removes its socket and window file, then exits.
        const exiting = child;
        setTimeout(() => exiting.kill(), 2000).unref();
      }
    },
  };
}

module.exports = { startContainerLink, dockerExec };
