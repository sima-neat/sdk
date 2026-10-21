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
  // The built-in Welcome editor can appear before this extension activates.
  // VS Code exposes it as an unknown tab input. Do not mistake it for restored
  // user work, but preserve typed editors even if their file is named Welcome.
  const welcomeLabel = vscode.l10n.t("Welcome");
  const hasTabs = vscode.window.tabGroups.all.some((group) =>
    group.tabs.some(
      (tab) => tab.input !== undefined || tab.label !== welcomeLabel,
    ),
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
