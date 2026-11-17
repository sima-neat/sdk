const STATE_URL = 'https://artifacts.neat.sima.ai/models/state.json';
const FALLBACK_STATE = Object.freeze({current_state: null, default_branch: 'develop'});

function parseState(value) {
  if (!value || Array.isArray(value) ||
      !['GA', 'Beta', 'Alpha'].includes(value.current_state) ||
      !['develop', 'main'].includes(value.default_branch)) {
    throw new Error('Invalid registry release state');
  }
  return Object.freeze({current_state: value.current_state, default_branch: value.default_branch});
}

async function fetchState(fetcher = fetch) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetcher(STATE_URL, {signal: controller.signal,
      redirect: 'error', headers: {'Cache-Control': 'no-cache', Accept: 'application/json'}});
    if (!response.ok) throw new Error(`Registry state HTTP ${response.status}`);
    let size = 0;
    const chunks = [];
    for await (const chunk of response.body) {
      size += chunk.length;
      if (size > 4096) throw new Error('Registry state exceeds 4096 bytes');
      chunks.push(Buffer.from(chunk));
    }
    return parseState(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  } finally {
    controller.abort();
    clearTimeout(timeout);
  }
}

class RegistryState {
  constructor(load = fetchState) {
    this.load = load;
    this.value = FALLBACK_STATE;
    this.listeners = new Set();
  }
  snapshot() { return this.value; }
  subscribe(listener) {
    this.listeners.add(listener);
    return {dispose: () => this.listeners.delete(listener)};
  }
  refresh() {
    if (this.disposed) return Promise.resolve(this.value);
    if (this.pending) return this.pending;
    this.pending = Promise.resolve().then(() => this.load()).then(parseState).then(value => {
      if (!this.disposed) {
        this.value = value;
        for (const listener of this.listeners) listener(value);
      }
    }).catch(() => {
      // Keep the last validated state during outages; never invent a release label.
    }).then(() => this.value).finally(() => { this.pending = undefined; });
    return this.pending;
  }
  start() {
    if (this.timer || this.disposed) return;
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), 60000);
    this.timer.unref?.();
  }
  dispose() {
    this.disposed = true;
    clearInterval(this.timer);
    this.listeners.clear();
  }
}
module.exports = {STATE_URL, FALLBACK_STATE, parseState, fetchState, RegistryState};
