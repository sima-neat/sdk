const vscode = require("vscode");

class NeatPanelProvider {
  constructor(extensionUri) {
    this.extensionUri = extensionUri;
  }

  resolveWebviewView(webviewView) {
    webviewView.webview.options = {
      enableScripts: false,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "media")]
    };

    const logoUri = webviewView.webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "neat-logo.png")
    );

    webviewView.webview.html = getPanelHtml(logoUri);
  }
}

function activate(context) {
  const provider = new NeatPanelProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("simaNeat.panel", provider)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("simaNeat.showPanel", async () => {
      await vscode.commands.executeCommand("simaNeat.panel.focus");
    })
  );
}

function getPanelHtml(logoUri) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${logoUri.scheme}:; style-src 'unsafe-inline';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {
      margin: 0;
      padding: 20px;
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      font-family: var(--vscode-font-family);
    }

    .logo {
      display: block;
      width: min(180px, 100%);
      height: auto;
      margin-bottom: 20px;
    }

    h1 {
      margin: 0 0 8px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }

    p {
      margin: 0 0 14px;
      line-height: 1.45;
      color: var(--vscode-descriptionForeground);
    }

    .message {
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      padding: 12px;
      background: var(--vscode-editor-background);
    }

    .label {
      margin-bottom: 6px;
      color: var(--vscode-foreground);
      font-weight: 600;
    }
  </style>
</head>
<body>
  <img class="logo" src="${logoUri}" alt="SiMa.ai">
  <h1>SiMa Neat SDK</h1>
  <p>Workspace tools for building, running, and inspecting Neat applications.</p>
  <div class="message">
    <div class="label">Experimental panel</div>
    <p>This extension is running inside the SDK workspace. Future actions can surface DevKit status, Code UI links, logs, and Neat Insight controls here.</p>
  </div>
</body>
</html>`;
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
};
