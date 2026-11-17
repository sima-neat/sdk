'use strict';

// Pages ported from the SDK's own VS Code extension (sima-neat/sdk,
// vscode-extension/, at a1c4c02): Getting Started, the Palette panel, Insight
// in a tab, and the Models browser. That extension runs inside the container;
// these run on this computer and reach the container through ../container.js.
// See NOTICE.md for what changed.

const vscode = require('vscode');
const services = require('./services');
const { RegistryState } = require('./registry-state');
const { createLandingPage, VIEW_TYPE: LANDING_VIEW_TYPE } = require('./landing-page');
const { PalettePanelProvider, VIEW_ID: PANEL_VIEW_ID } = require('./palette-panel');
const { createInsightView } = require('./insight-view');
const { registerModels } = require('./model-registry');

function noContainerState(buttonLabel) {
  return { disabled: true, buttonLabel, status: 'Start the SDK container to check this.', detail: '' };
}

/** Wraps a container probe so the panel says what's missing instead of a generic error. */
function needsContainer(probe, buttonLabel) {
  return async () => {
    try {
      return await probe();
    } catch (error) {
      if (error.code === 'NO_CONTAINER') {
        return noContainerState(buttonLabel);
      }
      throw error;
    }
  };
}

function register(context, api) {
  const registryState = new RegistryState();
  context.subscriptions.push(registryState);
  registryState.start();

  const insightView = createInsightView(vscode, context, services.getInsightWebUiUrl);
  const openInsight = (options) => insightView.open(undefined, options);

  registerModels(vscode, context, {
    resolveCli: () => {
      const cli = api.getSimaCli();
      return cli && cli.file;
    },
    getWorkspace: () => services.hostWorkspace(),
    displayPath: services.displayPath,
    getState: () => registryState.refresh(),
  });

  const openGettingStarted = createLandingPage(vscode, context, {
    loadData: services.loadGettingStartedData,
    getAppsState: services.getSamplesState,
    cloneApps: services.cloneSamples,
    openDevKitShell: services.openDevKitShell,
    openInsight,
    registryState,
    modelsEnabled: true,
  });

  const panel = new PalettePanelProvider(vscode, context, {
    ...services,
    openInsight,
    getContainerState: async () => {
      const target = await services.requireContainer().catch(() => undefined);
      return { status: target ? `SDK container: ${target.name}` : 'No SDK container is running. Start one from Neat Setup.' };
    },
    getDevKitSyncState: needsContainer(services.getDevKitSyncState, 'DevKit Sync'),
    getAuthState: async () => {
      const login = api.readLoginState().external;
      return login.loggedIn
        ? {
          signedIn: true,
          buttonLabel: 'Logout',
          command: 'logoutDeveloperPortal',
          status: 'Signed in to SiMa Developer Portal.',
          detail: login.user || '',
        }
        : {
          signedIn: false,
          buttonLabel: 'Login',
          command: 'loginDeveloperPortal',
          status: 'Sign in to download models and other assets from SiMa Developer Portal.',
          detail: '',
          disabled: !api.getSimaCli(),
        };
    },
  });
  panel.updateRegistryState(registryState.snapshot());

  context.subscriptions.push(
    registryState.subscribe((state) => panel.updateRegistryState(state)),
    vscode.window.registerWebviewViewProvider(PANEL_VIEW_ID, panel),
    panel,
    // Login changes and sima-cli installs show up in the panel while it's open.
    api.onDidChange(() => panel.webviewView && panel.webviewView.visible && panel.refresh()),
    vscode.window.registerWebviewPanelSerializer(LANDING_VIEW_TYPE, {
      deserializeWebviewPanel: (restored) => openGettingStarted(restored),
    }),
    vscode.commands.registerCommand('simaNeat.openGettingStarted', () => openGettingStarted()),
    vscode.commands.registerCommand('simaNeat.openPalettePanel', () => vscode.commands.executeCommand(`${PANEL_VIEW_ID}.focus`)),
    vscode.commands.registerCommand('simaNeat.openInsight', async () => {
      try {
        await openInsight();
      } catch (error) {
        vscode.window.showErrorMessage(error.message);
      }
    }),
  );
  return { openInsight };
}

module.exports = { register };
