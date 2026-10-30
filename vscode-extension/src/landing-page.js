const fs = require("fs/promises");
const crypto = require("crypto");
const { createAgentManager } = require("./agents");
const { loadLandingData } = require("./landing-data");
function escape(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
async function landingHtml(vscode, context, webview) {
  const base = vscode.Uri.joinPath(context.extensionUri, "media");
  const asset = (...parts) =>
    escape(
      webview.asWebviewUri(vscode.Uri.joinPath(base, ...parts)).toString(),
    );
  const nonce = crypto.randomBytes(24).toString("hex");
  const body = (
    await fs.readFile(
      vscode.Uri.joinPath(base, "landing", "landing.html").fsPath,
      "utf8",
    )
  ).replace("{{LOGO}}", asset("sima-logo.png"));
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource}; font-src ${webview.cspSource}; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';"><title>Palette SDK</title><link rel="stylesheet" href="${asset("landing", "landing.css")}"></head><body>${body}<script nonce="${nonce}" src="${asset("landing", "landing.js")}"></script></body></html>`;
}
function createLandingPage(vscode, context, services) {
  let panel;
  const agents = createAgentManager(vscode);
  return async function open(restored) {
    if (panel && !restored) {
      panel.reveal();
      return;
    }
    const current =
      restored ||
      vscode.window.createWebviewPanel(
        "simaNeat.landing",
        "Palette SDK",
        vscode.ViewColumn.One,
        {
          enableScripts: true,
          localResourceRoots: [
            vscode.Uri.joinPath(context.extensionUri, "media"),
          ],
          retainContextWhenHidden: true,
        },
      );
    // Restored panels retain the title saved by the previous extension version.
    current.title = "Palette SDK";
    if (restored)
      current.webview.options = {
        enableScripts: true,
        localResourceRoots: [
          vscode.Uri.joinPath(context.extensionUri, "media"),
        ],
      };
    panel = current;
    let disposed = false,
      busy = false;
    const refresh = async () => {
      if (busy || disposed) return;
      busy = true;
      try {
        const value = await (services.loadData || loadLandingData)(
          services.getDevkitConfig,
        );
        if (!disposed)
          await current.webview.postMessage({
            type: "data",
            value: { ...value, modelsEnabled: services.modelsEnabled },
          });
      } catch {
        if (!disposed) await current.webview.postMessage({ type: "error" });
      } finally {
        busy = false;
      }
    };
    const sendAgents = (value) => {
      if (!disposed)
        void current.webview.postMessage({ type: "agents", value });
    };
    const agentChanges = agents.subscribe(sendAgents);
    const sendRegistryState = (value) => {
      if (!disposed) void current.webview.postMessage({type: "registryState", value});
    };
    const registryChanges = services.registryState?.subscribe(sendRegistryState);
    const receive = current.webview.onDidReceiveMessage(async (message) => {
      if (message?.type === "agents-ready") {
        sendAgents(agents.snapshot());
        return;
      }
      if (message?.type === "agent") {
        await agents.action(message.agent, message.action);
        return;
      }
      if (message?.type === "ready" || message?.type === "refresh") {
        sendRegistryState(services.registryState?.snapshot());
        void services.registryState?.refresh();
        await refresh();
        return;
      }
      if (message?.type !== "action") return;
      // Actions carry identifiers only. Never execute commands or open arbitrary
      // URLs supplied by the webview or by device metadata.
      try {
        switch (message.action) {
          case "panel":
            await vscode.commands.executeCommand("simaNeat.showPanel");
            break;
          case "models":
            await vscode.commands.executeCommand("simaNeat.browseModels");
            break;
          case "insight":
            await services.openInsight();
            break;
          case "apps":
            await vscode.env.openExternal(
              vscode.Uri.parse("https://github.com/sima-neat/apps"),
            );
            break;
          case "docs":
            await vscode.env.openExternal(
              vscode.Uri.parse(
                "https://developer.sima.ai/software/getting-started/",
              ),
            );
            break;
        }
      } catch {
        vscode.window.showErrorMessage(
          "Unable to open the requested Neat tool. Please try again.",
        );
      }
    });
    current.onDidDispose(() => {
      disposed = true;
      receive.dispose();
      agentChanges.dispose();
      registryChanges?.dispose();
      if (panel === current) panel = undefined;
    });
    context.subscriptions.push(current);
    try {
      current.webview.html = await landingHtml(
        vscode,
        context,
        current.webview,
      );
    } catch (error) {
      current.dispose();
      throw error;
    }
  };
}
module.exports = { landingHtml, createLandingPage };
