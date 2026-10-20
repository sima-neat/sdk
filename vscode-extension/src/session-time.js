const fs = require('fs');

function parseDeadline(text) {
  const data = JSON.parse(text);
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Expected an object');
  if (data.expiresAt === null) return null;
  if (typeof data.expiresAt !== 'string' || !/^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(data.expiresAt)) {
    throw new Error('expiresAt must be an ISO timestamp with timezone, or null');
  }
  const deadline = Date.parse(data.expiresAt);
  if (!Number.isFinite(deadline)) throw new Error('Invalid expiresAt');
  return deadline;
}

function parseSession(text) {
  const deadline = parseDeadline(text);
  if (deadline === null) return null;
  const { display = 'auto', blink = false, blinkColor = 'red' } = JSON.parse(text);
  if (!['auto', 'quiet', 'warning', 'urgent'].includes(display)) {
    throw new Error('display must be auto, quiet, warning, or urgent');
  }
  if (typeof blink !== 'boolean') throw new Error('blink must be a boolean');
  if (!['red', 'amber'].includes(blinkColor)) throw new Error('blinkColor must be red or amber');
  return { deadline, display, blink, blinkColor };
}

function describe(deadline, now = Date.now(), display = 'auto') {
  if (deadline === null) return null;
  const seconds = Math.max(0, Math.ceil((deadline - now) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  const time = `${hours ? `${hours}:` : ''}${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  const expiration = new Date(deadline).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
  const severity = display === 'quiet' ? 'normal' : display === 'warning' ? 'warning' : display === 'urgent' ? 'error' : seconds <= 60 ? 'error' : seconds <= 300 ? 'warning' : 'normal';
  return {
    display,
    expiration,
    text: display === 'quiet' ? `${seconds ? 'Expires' : 'Expired'} ${expiration}` : seconds ? `${time} remaining` : 'Environment time has expired',
    detail: seconds ? 'Save your work before your environment session ends.' : 'Save your work now. Access may end at any moment.',
    severity,
    seconds
  };
}

class SessionTime {
  constructor(vscode, file, onChange) {
    this.vscode = vscode;
    this.file = file;
    this.onChange = onChange;
    this.session = null;
    this.notified = new Set();
    this.item = vscode.window.createStatusBarItem('simaNeat.sessionTime', vscode.StatusBarAlignment.Left, 10000);
    this.item.name = 'Neat environment time';
    this.item.command = 'simaNeat.showPanel';
    this.output = vscode.window.createOutputChannel('Neat Session Time');
    this.timer = setInterval(() => this.poll(), 1000);
    this.poll();
  }

  async poll() {
    if (this.busy || this.disposed) return;
    this.busy = true;
    try {
      let session;
      try {
        const text = await fs.promises.readFile(this.file, 'utf8');
        if (Buffer.byteLength(text) > 4096) throw new Error('Session file exceeds 4 KiB');
        session = parseSession(text);
        this.lastError = undefined;
      } catch (error) {
        if (error.code === 'ENOENT') session = null;
        else {
          if (this.lastError !== error.message) this.output.appendLine(`Cannot read session deadline: ${error.message}; retaining last valid deadline.`);
          this.lastError = error.message;
          session = this.session;
        }
      }
      if (this.disposed) return;
      if (session?.deadline !== this.session?.deadline || session?.display !== this.session?.display) this.notified.clear();
      if (JSON.stringify(session) !== JSON.stringify(this.session)) this.blinkOn = false;
      this.session = session;
      const state = session ? describe(session.deadline, Date.now(), session.display) : null;
      this.onChange(state);
      if (!state) { this.item.hide(); return; }
      this.item.text = `$(clock) Neat: ${state.text}`;
      this.item.tooltip = `${state.detail}\nSession ends: ${state.expiration}`;
      // Alternate only the highlight, never hide the text or change its width.
      // One second on / one second off; quiet mode always stays unhighlighted.
      this.blinkOn = session.blink ? !this.blinkOn : true;
      const highlight = session.blink ? (session.blinkColor === 'red' ? 'error' : 'warning') : state.severity;
      this.item.backgroundColor = state.severity === 'normal' || !this.blinkOn ? undefined : new this.vscode.ThemeColor(`statusBarItem.${highlight}Background`);
      this.item.show();
      const stage = state.display === 'quiet' ? 'normal' : state.display === 'auto' && state.seconds === 0 ? 'expired' : state.severity;
      if (stage !== 'normal' && !this.notified.has(stage)) {
        this.notified.add(stage);
        const message = `Neat: ${state.text}. ${state.detail}`;
        if (stage === 'expired' || stage === 'error') this.vscode.window.showErrorMessage(message);
        else this.vscode.window.showWarningMessage(message);
      }
    } finally { this.busy = false; }
  }

  dispose() {
    this.disposed = true;
    clearInterval(this.timer);
    this.item.dispose();
    this.output.dispose();
  }
}
module.exports = { SessionTime, parseDeadline, parseSession, describe };
