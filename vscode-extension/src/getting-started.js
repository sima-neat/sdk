const fs = require("fs/promises");
const { createLandingPage } = require("./landing-page");
const FIRST_LAUNCH_KEY = "simaNeat.landing.initialized";

// The extension localization API cannot translate core workbench strings.
// Read the same active core language pack selected by the extension host.
async function workbenchWelcomeLabel(nlsConfig = process.env.VSCODE_NLS_CONFIG) {
  try {
    const config = JSON.parse(nlsConfig || "{}");
    const translationsFile = config.languagePack?.translationsConfigFile ||
      config._translationsConfigFile;
    if (!translationsFile) return "Welcome";
    const translations = JSON.parse(await fs.readFile(translationsFile, "utf8"));
    if (!translations.vscode) return "Welcome";
    const pack = JSON.parse(await fs.readFile(translations.vscode, "utf8"));
    const label = pack.contents?.[
      "vs/workbench/contrib/welcomeGettingStarted/browser/gettingStartedInput"
    ]?.getStarted;
    return typeof label === "string" && label ? label : "Welcome";
  } catch {
    // Missing or corrupt language packs must not prevent extension activation.
    return "Welcome";
  }
}

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
  const welcomeLabel = await workbenchWelcomeLabel();
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

module.exports = { registerGettingStarted, workbenchWelcomeLabel };
