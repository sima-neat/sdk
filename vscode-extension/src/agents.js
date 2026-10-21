// Identifiers and commands come from the publishers' extension manifests.
// Never accept an extension ID, URI, or command supplied by the webview.
const AGENTS = Object.freeze({
  codex: { id: "openai.chatgpt", command: "chatgpt.openSidebar" },
  claude: {
    id: "anthropic.claude-code",
    command: "claude-vscode.sidebar.open",
  },
});
function createAgentManager(vscode) {
  const pending = new Map();
  const reload = new Set();
  const errors = new Map();
  const listeners = new Set();
  const snapshot = () =>
    Object.fromEntries(
      Object.entries(AGENTS).map(([key, agent]) => {
        const installed = Boolean(vscode.extensions.getExtension(agent.id));
        if (installed) reload.delete(key);
        return [
          key,
          {
            busy: pending.has(key),
            status:
              pending.get(key) === "install"
                ? "installing"
                : installed
                  ? "installed"
                  : reload.has(key)
                    ? "reload"
                    : "available",
            error: errors.get(key) || "",
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
    if (pending.has(key)) return;
    const agent = AGENTS[key];
    errors.delete(key);
    pending.set(key, action);
    notify();
    try {
      if (action === "install") {
        if (!vscode.extensions.getExtension(agent.id)) {
          // The editor handles gallery selection, compatibility, and trust UI.
          await vscode.commands.executeCommand(
            "workbench.extensions.installExtension",
            agent.id,
            { enable: true, donotSync: true },
          );
          if (!vscode.extensions.getExtension(agent.id)) reload.add(key);
        }
      } else if (action === "open") {
        const extension = vscode.extensions.getExtension(agent.id);
        if (!extension) throw new Error("Extension unavailable");
        await extension.activate();
        await vscode.commands.executeCommand(agent.command);
      } else if (action === "reload") {
        if (reload.has(key))
          await vscode.commands.executeCommand("workbench.action.reloadWindow");
      } else {
        await vscode.commands.executeCommand(
          "workbench.extensions.action.showExtensionsWithIds",
          [agent.id],
        );
      }
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
      return {
        dispose() {
          listeners.delete(listener);
          changed.dispose();
        },
      };
    },
  };
}
module.exports = { createAgentManager };
