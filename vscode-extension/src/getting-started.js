const GETTING_STARTED_URL = "https://developer.sima.ai/software/getting-started/";
const FIRST_LAUNCH_KEY = "simaNeat.gettingStarted.initialized";

async function registerGettingStarted(vscode, context) {
  const open = () => vscode.commands.executeCommand("simpleBrowser.show", GETTING_STARTED_URL);
  context.subscriptions.push(vscode.commands.registerCommand("simaNeat.gettingStarted", open));

  if (vscode.env.uiKind !== vscode.UIKind.Web || context.globalState.get(FIRST_LAUNCH_KEY)) {
    return;
  }
  const startup = vscode.workspace.getConfiguration("workbench").inspect("startupEditor");
  const hasPreference = startup && [startup.globalValue, startup.workspaceValue, startup.workspaceFolderValue]
    .some(value => value !== undefined);
  const hasTabs = vscode.window.tabGroups.all.some(group => group.tabs.length > 0);
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

module.exports = { registerGettingStarted, GETTING_STARTED_URL };
