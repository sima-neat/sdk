'use strict';

// Insight in an editor tab (insight-view.js in the SDK extension). On this
// computer Insight is the port Docker publishes, on localhost. A bar above it
// opens the same page in the browser, for when the editor can't show it (for
// example if the SDK's certificate isn't trusted here).

const crypto = require('crypto');
const { normalizeHttpUrl } = require('./insight-launcher');

const VIEW_TYPE = 'simaNeatTools.insight';

function escapeAttribute(value) {
  return value.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
}

function insightHtml(url) {
  const origin = escapeAttribute(new URL(url).origin);
  const nonce = crypto.randomBytes(16).toString('base64');
  return `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src ${origin}; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<title>Insight</title>
<style>
html,body{width:100%;height:100%;margin:0;overflow:hidden;display:flex;flex-direction:column}
.bar{display:flex;gap:8px;align-items:center;padding:4px 8px;font:12px var(--vscode-font-family);color:var(--vscode-descriptionForeground);border-bottom:1px solid var(--vscode-panel-border)}
.bar span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar button{border:0;border-radius:2px;padding:2px 8px;color:var(--vscode-button-secondaryForeground);background:var(--vscode-button-secondaryBackground);font:inherit;cursor:pointer}
iframe{flex:1;width:100%;border:0;display:block}
</style>
</head><body>
<div class="bar"><span>${escapeAttribute(url)}</span><button id="reload">Reload</button><button id="browser">Open in browser</button></div>
<iframe id="insight" title="Insight" src="${escapeAttribute(url)}" allow="camera ${origin}; autoplay; fullscreen; clipboard-read; clipboard-write" sandbox="allow-scripts allow-forms allow-same-origin allow-downloads allow-modals allow-popups"></iframe>
<script nonce="${nonce}">
const vscode = acquireVsCodeApi();
document.getElementById('browser').addEventListener('click', () => vscode.postMessage({ command: 'openInBrowser' }));
document.getElementById('reload').addEventListener('click', () => { const frame = document.getElementById('insight'); frame.src = frame.src; });
</script>
</body></html>`;
}

function createInsightView(vscode, context, resolveUrl) {
  let panel;
  let currentUrl;
  const options = { enableScripts: true, enableForms: true, localResourceRoots: [] };

  /** Resolves with { url } once the tab shows Insight, or { error } if it can't. */
  async function open(restoredPanel, { showErrors = true } = {}) {
    let url;
    let reason;
    try {
      url = normalizeHttpUrl(await resolveUrl());
    } catch (error) {
      // The status command can be unavailable while SDK services start.
      reason = error.message;
    }
    if (!url) {
      if (restoredPanel) {
        restoredPanel.dispose();
      }
      const error = reason || 'Unable to acquire Insight link';
      if (showErrors) {
        vscode.window.showErrorMessage(error);
      }
      return { error };
    }

    if (!panel) {
      panel = restoredPanel || vscode.window.createWebviewPanel(VIEW_TYPE, 'Insight', vscode.ViewColumn.Active,
        { ...options, retainContextWhenHidden: true });
      panel.title = 'Insight';
      panel.webview.options = options;
      panel.webview.onDidReceiveMessage((message) => {
        if (message.command === 'openInBrowser' && currentUrl) {
          vscode.env.openExternal(vscode.Uri.parse(currentUrl));
        }
      });
      panel.onDidDispose(() => {
        panel = undefined;
        currentUrl = undefined;
      });
    } else if (restoredPanel && restoredPanel !== panel) {
      restoredPanel.dispose();
    }
    // Do not reset a live viewer when users return through either launch button.
    if (currentUrl !== url) {
      panel.webview.html = insightHtml(url);
      currentUrl = url;
    }
    if (!restoredPanel) {
      panel.reveal(vscode.ViewColumn.Active);
    }
    return { url };
  }

  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, { deserializeWebviewPanel: (restoredPanel) => open(restoredPanel) }),
    { dispose: () => panel && panel.dispose() },
  );
  return { open };
}

module.exports = { VIEW_TYPE, createInsightView };
