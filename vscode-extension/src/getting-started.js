const { createLandingPage } = require("./landing-page");
const FIRST_LAUNCH_KEY = "simaNeat.landing.initialized";

async function registerGettingStarted(vscode, context, services) {
  const open = createLandingPage(vscode, context, services);
  context.subscriptions.push(
    vscode.commands.registerCommand("simaNeat.gettingStarted", () => open()),
  );
  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer("simaNeat.landing", {
      deserializeWebviewPanel: (panel) => open(panel),
    }),
  );

  if (
    vscode.env.uiKind !== vscode.UIKind.Web ||
    context.globalState.get(FIRST_LAUNCH_KEY)
  ) {
    return;
  }
  const startup = vscode.workspace
    .getConfiguration("workbench")
    .inspect("startupEditor");
  const hasPreference =
    startup &&
    [
      startup.globalValue,
      startup.workspaceValue,
      startup.workspaceFolderValue,
    ].some((value) => value !== undefined);
  const hasTabs = vscode.window.tabGroups.all.some(
    (group) => group.tabs.length > 0,
  );
  // Existing sessions and explicit startup choices take precedence, permanently.
  if (hasPreference || hasTabs) {
    await context.globalState.update(FIRST_LAUNCH_KEY, true);
    return;
  }
  try {
    await open();
    await context.globalState.update(FIRST_LAUNCH_KEY, true);
  } catch (error) {
    // Leave the first-launch marker unset so the next activation can retry.
    console.warn("Neat: unable to open Getting Started", error);
  }
}

module.exports = { registerGettingStarted };
