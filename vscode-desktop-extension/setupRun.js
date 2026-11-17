'use strict';

// Runs `sima-cli sdk setup` in the background for the setup page, instead of
// in a terminal. It runs in a pseudo-terminal (sudo needs one), shows each
// output line with the time since start, and answers the prompts setup can
// still show with -n (sudo, SSH passwords) through VS Code input boxes.
// No vscode dependency: prompts go through the ask callback.

const { spawn } = require('child_process');
const { withPty } = require('./hostTerminal');

const MAX_LOG_LINES = 400;
// A partial line that waits for input: sudo, ssh and generic password prompts.
const PASSWORD_PROMPT = /(\[sudo\] password for [^:]+:|password[^:\n]{0,40}:)\s*$/i;
// Anything else that ends like a question and then stays quiet asks for input too.
const OTHER_PROMPT = /(\?|:|\]|\))\s*$/;
const QUIET_BEFORE_ASKING_MS = 2500;

// eslint-disable-next-line no-control-regex
const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]/g;

function clean(text) {
  return text.replace(ANSI, '');
}

/**
 * Starts setup. onUpdate(snapshot) gets { state, log, status, startedAt,
 * exitCode }. ask({ kind, prompt }) resolves with the answer, or undefined to
 * stop setup. Returns { cancel }.
 */
function createSetupRun({ file, args, env, ask, onUpdate }) {
  const startedAt = Date.now();
  const snapshot = { state: 'running', log: [], status: 'Starting setup…', startedAt };
  let partial = '';
  let quietTimer;
  let asking = false;
  let cancelled = false;

  const elapsed = () => {
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  };
  const update = () => onUpdate({ ...snapshot, log: [...snapshot.log] });
  const addLine = (line) => {
    const text = line.trim();
    if (!text) {
      return;
    }
    snapshot.log.push(`[${elapsed()}] ${text}`);
    if (snapshot.log.length > MAX_LOG_LINES) {
      snapshot.log.splice(0, snapshot.log.length - MAX_LOG_LINES);
    }
    snapshot.status = text;
  };

  const command = withPty(file, args);
  const child = spawn(command.file, command.args, { env, stdio: ['pipe', 'pipe', 'pipe'] });

  async function answer(kind, prompt) {
    asking = true;
    snapshot.status = `Waiting for your answer: ${prompt}`;
    update();
    const reply = await ask({ kind, prompt });
    asking = false;
    if (reply === undefined) {
      cancelled = true;
      addLine('Stopped: the question was not answered.');
      child.kill();
      return;
    }
    // A password isn't echoed, so log the prompt here; a typed answer is echoed after its question.
    if (kind === 'password') {
      addLine(`${prompt} (answered)`);
      partial = '';
    }
    child.stdin.write(`${reply}\n`);
    update();
  }

  function onOutput(data) {
    const text = clean(data.toString()).replace(/\r\n/g, '\n');
    // A bare \r rewrites the current line (progress bars): keep its last version.
    const lines = (partial + text).split('\n');
    partial = lines.pop().split('\r').pop();
    lines.forEach((line) => addLine(line.split('\r').pop()));
    clearTimeout(quietTimer);
    if (!asking && PASSWORD_PROMPT.test(partial)) {
      void answer('password', partial.trim());
    } else if (!asking && partial.trim() && OTHER_PROMPT.test(partial)) {
      quietTimer = setTimeout(() => {
        if (!asking && partial.trim()) {
          void answer('text', partial.trim());
        }
      }, QUIET_BEFORE_ASKING_MS);
    }
    update();
  }

  child.stdout.on('data', onOutput);
  child.stderr.on('data', onOutput);
  child.on('error', (error) => {
    addLine(error.message);
    snapshot.state = 'failed';
    update();
  });
  child.on('close', (code) => {
    clearTimeout(quietTimer);
    addLine(partial);
    snapshot.exitCode = typeof code === 'number' ? code : undefined;
    snapshot.state = cancelled ? 'cancelled' : code === 0 ? 'done' : 'failed';
    snapshot.status = snapshot.state === 'done' ? `Setup finished in ${elapsed()}.` : snapshot.status;
    update();
  });
  update();

  return {
    cancel() {
      cancelled = true;
      child.kill();
    },
  };
}

module.exports = { createSetupRun, PASSWORD_PROMPT };
