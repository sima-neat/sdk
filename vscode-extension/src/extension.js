const vscode = require("vscode");
const { execFile } = require("child_process");

const APPS_REPO_URL = "https://github.com/sima-neat/apps";

class NeatPanelProvider {
  constructor(extensionUri) {
    this.extensionUri = extensionUri;
    this.webviewView = undefined;
    this.disposables = [];
  }

  async resolveWebviewView(webviewView) {
    this.webviewView = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "media")]
    };

    this.disposables.push(
      webviewView.webview.onDidReceiveMessage(async (message) => {
        if (message.command === "cloneSamples") {
          try {
            await cloneSamples();
          } finally {
            await this.refresh();
          }
        }
      })
    );

    await this.refresh();
  }

  async refresh() {
    if (!this.webviewView) {
      return;
    }

    const logoUri = this.webviewView.webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "neat-logo.png")
    );
    const workspaceRoot = getWorkspaceRoot();
    const samplesState = await getSamplesState(workspaceRoot);

    this.webviewView.webview.html = getPanelHtml(logoUri, samplesState);
  }

  dispose() {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }
}

function activate(context) {
  const provider = new NeatPanelProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("simaNeat.panel", provider),
    provider
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("simaNeat.showPanel", async () => {
      await vscode.commands.executeCommand("simaNeat.panel.focus");
    })
  );
}

function getWorkspaceRoot() {
  return vscode.workspace.workspaceFolders?.[0]?.uri;
}

async function getSamplesState(workspaceRoot) {
  if (!workspaceRoot) {
    return {
      disabled: true,
      buttonLabel: "Clone Samples",
      status: "Open an SDK workspace folder to clone samples.",
      detail: ""
    };
  }

  const appsUri = vscode.Uri.joinPath(workspaceRoot, "apps");
  const appsGitUri = vscode.Uri.joinPath(appsUri, ".git");

  if (await pathExists(appsGitUri)) {
    return {
      disabled: true,
      buttonLabel: "Samples Cloned",
      status: "Samples repository is available.",
      detail: vscode.workspace.asRelativePath(appsUri, false)
    };
  }

  if (await pathExists(appsUri)) {
    return {
      disabled: true,
      buttonLabel: "Clone Samples",
      status: "An apps directory already exists, but it is not a Git checkout.",
      detail: vscode.workspace.asRelativePath(appsUri, false)
    };
  }

  return {
    disabled: false,
    buttonLabel: "Clone Samples",
    status: "Clone SiMa Neat samples into this workspace.",
    detail: vscode.workspace.asRelativePath(vscode.Uri.joinPath(workspaceRoot, "apps"), false)
  };
}

async function pathExists(uri) {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

async function cloneSamples() {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    vscode.window.showWarningMessage("Open an SDK workspace folder before cloning samples.");
    return;
  }

  const state = await getSamplesState(workspaceRoot);
  if (state.disabled) {
    vscode.window.showInformationMessage(state.status);
    return;
  }

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Cloning SiMa Neat samples",
      cancellable: false
    },
    async (progress) => {
      progress.report({ message: "Starting git clone..." });
      await execFilePromise("git", ["clone", APPS_REPO_URL, "apps"], {
        cwd: workspaceRoot.fsPath
      });
      progress.report({ message: "Samples repository cloned." });
    }
  );

  vscode.window.showInformationMessage("SiMa Neat samples cloned into apps/.");
}

function execFilePromise(file, args, options) {
  return new Promise((resolve, reject) => {
    execFile(file, args, options, (error, stdout, stderr) => {
      if (error) {
        const details = stderr || stdout || error.message;
        reject(new Error(details.trim()));
        return;
      }
      resolve(stdout);
    });
  }).catch((error) => {
    vscode.window.showErrorMessage(`Failed to clone samples: ${error.message}`);
    throw error;
  });
}

function getPanelHtml(logoUri, samplesState) {
  const cloneDisabled = samplesState.disabled ? "disabled" : "";
  const status = escapeHtml(samplesState.status);
  const detail = escapeHtml(samplesState.detail);
  const buttonLabel = escapeHtml(samplesState.buttonLabel);

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${logoUri.scheme}:; script-src 'unsafe-inline'; style-src 'unsafe-inline';">
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
      margin-bottom: 12px;
    }

    .label {
      margin-bottom: 6px;
      color: var(--vscode-foreground);
      font-weight: 600;
    }

    .actions {
      display: grid;
      gap: 8px;
    }

    button {
      width: 100%;
      min-height: 32px;
      border: 0;
      border-radius: 4px;
      padding: 6px 10px;
      color: var(--vscode-button-foreground);
      background: var(--vscode-button-background);
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }

    button:hover:not(:disabled) {
      background: var(--vscode-button-hoverBackground);
    }

    button:disabled {
      opacity: 0.55;
      cursor: default;
    }

    .status {
      margin: 0;
      font-size: 12px;
    }

    .detail {
      margin: 0;
      color: var(--vscode-descriptionForeground);
      font-family: var(--vscode-editor-font-family);
      font-size: 11px;
      overflow-wrap: anywhere;
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
  <div class="message">
    <div class="label">Samples</div>
    <div class="actions">
      <button id="cloneSamples" ${cloneDisabled}>${buttonLabel}</button>
      <p class="status">${status}</p>
      <p class="detail">${detail}</p>
    </div>
  </div>
  <script>
    const vscode = acquireVsCodeApi();
    const cloneButton = document.getElementById("cloneSamples");
    cloneButton?.addEventListener("click", () => {
      cloneButton.disabled = true;
      cloneButton.textContent = "Cloning...";
      vscode.postMessage({ command: "cloneSamples" });
    });
  </script>
</body>
</html>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
};
