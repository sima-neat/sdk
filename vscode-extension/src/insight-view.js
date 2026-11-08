const { normalizeHttpUrl } = require("./insight-launcher");

function escapeAttribute(value) {
  return value.replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
}

function insightHtml(url) {
  const origin = escapeAttribute(new URL(url).origin);
  return `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src ${origin}; style-src 'unsafe-inline';">
<title>Insight</title>
<style>html,body{width:100%;height:100%;margin:0;overflow:hidden}iframe{width:100%;height:100%;border:0;display:block}</style>
</head><body><iframe title="Insight" src="${escapeAttribute(url)}" allow="camera ${origin}; autoplay; fullscreen; clipboard-read; clipboard-write" sandbox="allow-scripts allow-forms allow-same-origin allow-downloads allow-modals allow-popups"></iframe></body></html>`;
}

function createInsightView(vscode, context, resolveUrl) {
  let panel;
  let currentUrl;
  const options = { enableScripts: true, enableForms: true, localResourceRoots: [] };

  async function open(restoredPanel) {
    let url;
    try {
      url = normalizeHttpUrl(await resolveUrl());
    } catch {
      // The status command can be unavailable while SDK services start.
    }
    if (!url) {
      restoredPanel?.dispose();
      vscode.window.showErrorMessage("Unable to acquire Insight link");
      return;
    }

    if (!panel) {
      panel = restoredPanel || vscode.window.createWebviewPanel(
        "simaNeat.insight", "Insight", vscode.ViewColumn.Active,
        { ...options, retainContextWhenHidden: true }
      );
      panel.title = "Insight";
      panel.webview.options = options;
      panel.onDidDispose(() => { panel = undefined; currentUrl = undefined; });
    } else if (restoredPanel && restoredPanel !== panel) {
      restoredPanel.dispose();
    }
    // Use the browser-facing launch URL directly. code-server's HTTP port
    // proxy cannot forward the HTTPS Insight service. Do not reset a live
    // viewer when users return through either launch button.
    if (currentUrl !== url) {
      panel.webview.html = insightHtml(url);
      currentUrl = url;
    }
    if (!restoredPanel) panel.reveal(vscode.ViewColumn.Active);
  }

  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer("simaNeat.insight", {
      deserializeWebviewPanel: restoredPanel => open(restoredPanel)
    }),
    { dispose: () => panel?.dispose() }
  );
  return { open };
}

module.exports = { createInsightView };
