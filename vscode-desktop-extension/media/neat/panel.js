// Palette panel script from the SDK extension (src/extension.js getPanelHtml), without the session countdown.
const vscode = acquireVsCodeApi();
window.addEventListener('message', ({ data }) => {
  if (data.command === 'registryState') {
    const release = data.state && data.state.current_state;
    const programLabel = document.getElementById('registry-release');
    programLabel.hidden = release === 'GA';
    programLabel.textContent = 'Release program: ' + (release || 'Unavailable');
    const notice = document.getElementById('registry-program');
    const preview = release === 'Alpha' || release === 'Beta';
    notice.hidden = !preview;
    notice.textContent = preview ? 'The Model Registry is currently in the ' + release + ' program. Features and available models may change before general availability.' : '';
    return;
  }
  if (data.command === 'panelStatus' && data.html) {
    const next = new DOMParser().parseFromString(data.html, 'text/html');
    for (const key of data.section ? [data.section] : ['container', 'samples', 'tutorials', 'auth', 'devkit']) {
      const id = 'status-' + key;
      const current = document.getElementById(id);
      const replacement = next.getElementById(id);
      if (current && replacement) current.replaceWith(replacement);
    }
  }
});
document.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  if (button.id === 'devKitSsh') {
    vscode.postMessage({ command: 'openDevKitSsh', host: button.dataset.host, user: button.dataset.user, port: button.dataset.port });
    return;
  }
  const command = button.dataset.command || button.id;
  if (['cloneSamples', 'installTutorials'].includes(command)) {
    button.disabled = true;
  }
  vscode.postMessage({ command });
});
vscode.postMessage({ command: 'ready' });
