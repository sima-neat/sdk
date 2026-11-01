// Identifiers and commands come from the publishers' extension manifests.
// Never accept an extension ID, URI, or command supplied by the webview.
const AGENTS = Object.freeze({
  codex: { id: "openai.chatgpt", command: "chatgpt.openSidebar" },
  claude: {
    id: "anthropic.claude-code",
    command: "claude-vscode.sidebar.open",
  },
});
function createAgentManager(vscode, catalog) {
  const compatible = () => catalog?.snapshot() || { available: false, error: "Component compatibility is unavailable" };
  const matches = (key, extension) => Boolean(extension) && compatible().available &&
    extension.packageJSON?.version === compatible().components[key].version;
  const pending = new Map();
  const reload = new Set();
  const errors = new Map();
  const listeners = new Set();
  const snapshot = () =>
    Object.fromEntries(
      Object.entries(AGENTS).map(([key, agent]) => {
        const extension = vscode.extensions.getExtension(agent.id);
        const installed = matches(key, extension);
        const state = compatible();
        if (installed) reload.delete(key);
        return [
          key,
          {
            busy: pending.has(key),
            version: state.components?.[key]?.version,
            installedVersion: extension?.packageJSON?.version,
            blocked: !state.available,
            status:
              pending.get(key) === "install"
                ? "installing"
                : state.loading
                  ? "checking"
                : !state.available
                  ? "blocked"
                : installed
                  ? "installed"
                  : reload.has(key)
                    ? "reload"
                    : "available",
            error: errors.get(key) || (!state.available ? state.error : ""),
          },
        ];
      }),
    );
  const notify = () => {
    for (const listener of listeners) listener(snapshot());
  };
  async function action(key, action) {
    if (
      !Object.hasOwn(AGENTS, key) ||
      !["install", "open", "reload", "manage"].includes(action)
    )
      return;
    // Management remains available while a large gallery download is pending.
    if (action === "manage") {
      try {
        await vscode.commands.executeCommand(
          "workbench.extensions.action.showExtensionsWithIds", [AGENTS[key].id],
        );
        errors.delete(key);
      } catch {
        errors.set(key, "Unable to open Extensions. Please try again.");
      } finally {
        notify();
      }
      return;
    }
    if (pending.has(key)) return;
    const agent = AGENTS[key];
    errors.delete(key);
    pending.set(key, action);
    notify();
    try {
      if (action !== "reload") {
        await catalog?.refresh();
        if (!compatible().available) throw Error("No qualified SDK component mapping");
      }
      if (action === "install") {
        if (!matches(key, vscode.extensions.getExtension(agent.id))) {
          // Local VSIX installation pins the exact version and suppresses automatic gallery upgrades.
          const prepared = await catalog.artifact(key);
          await vscode.commands.executeCommand(
            "workbench.extensions.installExtension",
            vscode.Uri.file(prepared.file),
            { enable: true, donotSync: true },
          );
          if (!matches(key, vscode.extensions.getExtension(agent.id))) {
            await catalog.verifyInstalled(prepared.target);
            reload.add(key);
          }
        }
      } else if (action === "open") {
        const extension = vscode.extensions.getExtension(agent.id);
        if (!matches(key, extension)) throw new Error("Install the qualified extension version first");
        await extension.activate();
        await vscode.commands.executeCommand(agent.command);
      } else if (action === "reload") {
        if (reload.has(key))
          await vscode.commands.executeCommand("workbench.action.reloadWindow");
      }
      // A concurrent Manage failure must not survive a successful operation.
      errors.delete(key);
    } catch {
      errors.set(
        key,
        action === "install"
          ? "Installation did not finish. Check your connection and editor notifications, then retry or use Manage in Extensions."
          : "Unable to open the extension. Check that it is enabled in Extensions, or reload the editor and try again.",
      );
    } finally {
      pending.delete(key);
      notify();
    }
  }
  return {
    snapshot,
    action,
    subscribe(listener) {
      listeners.add(listener);
      const changed = vscode.extensions.onDidChange(() => listener(snapshot()));
      const componentChanges = catalog?.subscribe(() => listener(snapshot()));
      return {
        dispose() {
          listeners.delete(listener);
          changed.dispose();
          componentChanges?.dispose();
        },
      };
    },
  };
}
module.exports = { createAgentManager };
