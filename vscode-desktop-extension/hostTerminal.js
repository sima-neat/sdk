'use strict';

// Terminals that always run on this computer. In a remote window, such as one
// attached to the SDK container, VS Code starts ordinary terminals on the
// remote side. This extension's commands (sima-cli, Docker, SDK setup) belong
// on the host, so in remote windows they run in a pseudoterminal backed by a
// local process.

const vscode = require('vscode');
const { spawn } = require('child_process');

function isRemoteWindow() {
  return Boolean(vscode.env.remoteName);
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

/**
 * Wraps a command in `script`, which gives it a real pseudo-terminal: sudo and
 * ssh read passwords from one, and `docker exec -it` needs one. Windows has no
 * equivalent, so commands there run with plain pipes.
 */
function withPty(file, args, dimensions) {
  if (process.platform === 'linux') {
    // A new pseudo-terminal starts at 0x0; give it the panel's size so output wraps correctly.
    const size = dimensions ? `stty cols ${dimensions.columns} rows ${dimensions.rows} 2>/dev/null; ` : '';
    return { file: 'script', args: ['-qefc', `${size}exec ${[file, ...args].map(shellQuote).join(' ')}`, '/dev/null'], pty: true };
  }
  if (process.platform === 'darwin') {
    return { file: 'script', args: ['-q', '/dev/null', file, ...args], pty: true };
  }
  return { file, args, pty: false };
}

/**
 * Opens a terminal that runs `file args` on this computer and closes when it
 * exits, reporting the exit code as the terminal's exit status.
 */
function createHostTerminal({ name, file, args, env = {}, cwd }) {
  const writeEmitter = new vscode.EventEmitter();
  const closeEmitter = new vscode.EventEmitter();
  let child;
  let usesPty = false;

  const pseudoterminal = {
    onDidWrite: writeEmitter.event,
    onDidClose: closeEmitter.event,
    open(dimensions) {
      const command = withPty(file, args, dimensions);
      usesPty = command.pty;
      const size = dimensions ? { COLUMNS: String(dimensions.columns), LINES: String(dimensions.rows) } : {};
      child = spawn(command.file, command.args, {
        cwd,
        env: { ...process.env, TERM: 'xterm-256color', ...size, ...env },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      // A pseudo-terminal already sends \r\n; plain pipes send bare \n.
      const show = (data) => writeEmitter.fire(usesPty ? data.toString() : data.toString().replace(/\r?\n/g, '\r\n'));
      child.stdout.on('data', show);
      child.stderr.on('data', show);
      child.on('error', (error) => {
        writeEmitter.fire(`\r\n${error.message}\r\n`);
        closeEmitter.fire(1);
      });
      child.on('close', (code) => closeEmitter.fire(typeof code === 'number' ? code : 1));
    },
    handleInput(data) {
      if (child && child.stdin.writable) {
        // Through a pseudo-terminal, Enter (\r) and Ctrl+C behave as in a normal shell.
        child.stdin.write(usesPty ? data : data.replace(/\r/g, '\n'));
      }
    },
    close() {
      if (child && child.exitCode === null) {
        child.kill();
      }
    },
  };
  return vscode.window.createTerminal({ name, pty: pseudoterminal });
}

module.exports = { isRemoteWindow, createHostTerminal, withPty };
