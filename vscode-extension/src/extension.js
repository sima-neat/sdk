const vscode = require("vscode");
const { execFile } = require("child_process");
const fs = require("fs");
const https = require("https");
const os = require("os");
const path = require("path");
const { URLSearchParams } = require("url");

const APPS_REPO_URL = "https://github.com/sima-neat/apps";
const SIMA_CLI_DIR = path.join(os.homedir(), ".sima-cli");
const TOKEN_FILE = path.join(SIMA_CLI_DIR, ".tokens.json");
const EXTERNAL_AUTH_FILES = [
  TOKEN_FILE,
  path.join(SIMA_CLI_DIR, ".sima-cli-cookies.txt"),
  path.join(SIMA_CLI_DIR, ".sima-cli-csrf.json")
];
const DEFAULT_DEVKIT_SYNC_USER = "sima";
const DEFAULT_DEVKIT_SYNC_PASSWORD = "edgeai";
const DEFAULT_DEVKIT_SYNC_PORT = "22";
const SDK_IMAGE_DEPS_MANIFEST = "/usr/local/share/sima-sdk/deps/manifest.json";
const SIMA_CLI_CANDIDATE_PATHS = [
  "/opt/sima-cli/venv/bin/sima-cli",
  "/usr/local/bin/sima-cli",
  "/opt/anaconda3/bin/sima-cli"
];
const SIMA_CLI_PYTHON_CANDIDATE_PATHS = [
  "/opt/sima-cli/venv/bin/python",
  "/opt/sima-cli/venv/bin/python3",
  "/opt/anaconda3/bin/python",
  "/opt/anaconda3/bin/python3"
];
let simaCliExecutable = undefined;
let simaCliPythonExecutable = undefined;

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
          } catch (error) {
            showActionError("Failed to clone samples", error);
          } finally {
            await this.refresh();
          }
        } else if (message.command === "installTutorials") {
          try {
            await installTutorials();
          } catch (error) {
            showActionError("Failed to install tutorials", error);
          } finally {
            await this.refresh();
          }
        } else if (message.command === "loginDeveloperPortal") {
          try {
            await loginDeveloperPortal();
          } catch (error) {
            showActionError("Developer Portal login failed", error);
          } finally {
            await this.refresh();
          }
        } else if (message.command === "logoutDeveloperPortal") {
          try {
            await logoutDeveloperPortal();
          } catch (error) {
            showActionError("Developer Portal logout failed", error);
          } finally {
            await this.refresh();
          }
        } else if (message.command === "openDocumentation") {
          await vscode.env.openExternal(vscode.Uri.parse("https://developer.sima.ai/software"));
        } else if (message.command === "openInsight") {
          await openInsight();
        } else if (message.command === "openDevKitSsh") {
          await openDevKitSsh(message.host, message.user, message.port);
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
    const tutorialsState = await getTutorialsState(workspaceRoot);
    const authState = await getDeveloperPortalAuthState();
    const devKitState = await getDevKitSyncState();

    this.webviewView.webview.html = getPanelHtml(logoUri, samplesState, tutorialsState, authState, devKitState);
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
    const relativePath = vscode.workspace.asRelativePath(appsUri, false);
    return {
      disabled: true,
      buttonLabel: "Samples Cloned",
      status: "Samples are available under",
      detail: relativePath,
      detailKind: "path-folder"
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

async function getTutorialsState(workspaceRoot) {
  if (!workspaceRoot) {
    return {
      disabled: true,
      buttonLabel: "Install Tutorials",
      status: "Open an SDK workspace folder to install tutorials.",
      detail: ""
    };
  }

  const tutorialsUri = await findTutorialsUri(workspaceRoot);
  if (tutorialsUri) {
    const relativePath = vscode.workspace.asRelativePath(tutorialsUri, false);
    return {
      disabled: true,
      buttonLabel: "Tutorials Installed",
      status: "Tutorials are available under",
      detail: relativePath,
      detailKind: "path-folder"
    };
  }

  return {
    disabled: false,
    buttonLabel: "Install Tutorials",
    status: "Download Neat tutorials into this workspace.",
    detail: ""
  };
}

async function findTutorialsUri(workspaceRoot) {
  const candidates = [
    ["tutorials"],
    ["tutorial"],
    ["extras", "tutorials"],
    ["neat-extras", "tutorials"],
    ["sima-neat-extras", "tutorials"],
    ["extras", "share", "sima-neat", "tutorials"],
    ["extras", "lib", "sima-neat", "tutorials"]
  ];

  for (const parts of candidates) {
    const uri = vscode.Uri.joinPath(workspaceRoot, ...parts);
    if (await pathExists(uri)) {
      return uri;
    }
  }

  try {
    const entries = await vscode.workspace.fs.readDirectory(workspaceRoot);
    for (const [name, type] of entries) {
      if (type !== vscode.FileType.Directory || !name.toLowerCase().includes("extras")) {
        continue;
      }
      const nestedCandidates = [
        [name, "share", "sima-neat", "tutorials"],
        [name, "lib", "sima-neat", "tutorials"],
        [name, "tutorials"]
      ];
      for (const parts of nestedCandidates) {
        const uri = vscode.Uri.joinPath(workspaceRoot, ...parts);
        if (await pathExists(uri)) {
          return uri;
        }
      }
    }
  } catch {
    return undefined;
  }

  return undefined;
}

async function installTutorials() {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    vscode.window.showWarningMessage("Open an SDK workspace folder before installing tutorials.");
    return;
  }

  const state = await getTutorialsState(workspaceRoot);
  if (state.disabled) {
    vscode.window.showInformationMessage(state.status);
    return;
  }

  const simaCli = await resolveSimaCliExecutable();
  const coreTarget = await resolveCoreTutorialsTarget(workspaceRoot);
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Installing Neat tutorials",
      cancellable: false
    },
    async (progress) => {
      progress.report({ message: `Downloading ${coreTarget} extras package...` });
      await execFilePromise(simaCli, ["neat", "install", coreTarget, "-t", "extras"], {
        cwd: workspaceRoot.fsPath
      });
      progress.report({ message: "Tutorial package installed." });
    }
  );

  const tutorialsUri = await findTutorialsUri(workspaceRoot);
  if (tutorialsUri) {
    vscode.window.showInformationMessage(`Neat tutorials installed under ${vscode.workspace.asRelativePath(tutorialsUri, false)}.`);
  } else {
    vscode.window.showInformationMessage("Neat tutorials package installed.");
  }
}

async function resolveCoreTutorialsTarget(workspaceRoot) {
  const manifestPath = await resolveSdkDepsManifestPath(workspaceRoot);
  if (!manifestPath) {
    return "core";
  }

  try {
    const data = JSON.parse(await fs.promises.readFile(manifestPath, "utf8"));
    const value = data.core;
    const ref = typeof value === "string" ? value : value?.ref;
    if (!ref) {
      return "core";
    }
    return `core@${validateDependencyRef(String(ref), "core")}`;
  } catch (error) {
    throw new Error(`Unable to resolve Neat core tutorial version from ${manifestPath}: ${error.message}`);
  }
}

async function resolveSdkDepsManifestPath(workspaceRoot) {
  const candidates = [
    process.env.SDK_DEPS_MANIFEST,
    SDK_IMAGE_DEPS_MANIFEST,
    workspaceRoot ? path.join(workspaceRoot.fsPath, "deps", "manifest.json") : ""
  ].filter(Boolean);

  for (const candidate of candidates) {
    try {
      await fs.promises.access(candidate, fs.constants.R_OK);
      return candidate;
    } catch {
      // Try the next manifest location.
    }
  }

  return "";
}

function validateDependencyRef(raw, key) {
  const ref = raw.trim();
  if (!ref) {
    throw new Error(`dependency ${key} has an empty ref`);
  }
  if (ref.includes("@") || /\s/.test(ref)) {
    throw new Error(`dependency ${key} ref must not contain '@' or whitespace: ${ref}`);
  }
  if (!ref.includes(":")) {
    if (!/^[A-Za-z0-9._/-]+$/.test(ref)) {
      throw new Error(`dependency ${key} ref must be a git tag/ref like v0.1.0: ${ref}`);
    }
    return ref;
  }

  const parts = ref.split(":");
  if (parts.length !== 2) {
    throw new Error(`dependency ${key} ref must be tag, branch:latest, or branch:githash: ${ref}`);
  }
  const [branch, spec] = parts.map((part) => part.trim());
  if (!branch || !spec) {
    throw new Error(`dependency ${key} ref must include both branch and spec: ${ref}`);
  }
  if (!/^[A-Za-z0-9._/-]+$/.test(branch)) {
    throw new Error(`dependency ${key} branch contains unsupported characters: ${branch}`);
  }
  if (spec !== "latest" && !/^[A-Fa-f0-9]+$/.test(spec)) {
    throw new Error(`dependency ${key} spec must be 'latest' or a git hash: ${spec}`);
  }
  return `${branch}:${spec}`;
}

async function openInsight() {
  const insightUrl = await getInsightWebUiUrl();
  if (!insightUrl) {
    vscode.window.showErrorMessage("Unable to acquire Insight link");
    return;
  }

  await vscode.env.openExternal(vscode.Uri.parse(insightUrl));
}

async function getInsightWebUiUrl() {
  try {
    const stdout = await execFilePromise("neat", ["--json"], {}, { showError: false });
    const status = JSON.parse(stdout);
    return status?.insight?.webUiUrl || "";
  } catch {
    return "";
  }
}

async function getDevKitSyncState() {
  const config = await getDevKitSyncConfig();
  const host = config.host;
  if (!host) {
    return {
      host: "",
      user: "",
      port: "",
      online: false,
      buttonLabel: "DevKit Sync",
      status: "DevKit Sync is not enabled, use",
      detail: "sima-cli sdk setup --devkit {ip}",
      detailKind: "command",
      disabled: true
    };
  }

  if (!await canPingHost(host) || !await canSshHost(host, config.user, config.port)) {
    return {
      host,
      user: config.user,
      port: config.port,
      online: false,
      buttonLabel: "DevKit Sync",
      status: `DevKit ${host} is unreachable`,
      detail: "",
      disabled: true
    };
  }

  return {
    host,
    user: config.user,
    port: config.port,
    online: true,
    buttonLabel: "SSH to DevKit",
    status: "DevKit online, click to SSH to the DevKit",
    detail: "",
    disabled: false
  };
}

async function getDevKitSyncConfig() {
  const processConfig = {
    host: (process.env.DEVKIT_SYNC_DEVKIT_IP || "").trim(),
    user: (process.env.DEVKIT_SYNC_DEVKIT_USER || DEFAULT_DEVKIT_SYNC_USER).trim(),
    port: (process.env.DEVKIT_SYNC_DEVKIT_PORT || DEFAULT_DEVKIT_SYNC_PORT).trim()
  };
  if (processConfig.host) {
    return processConfig;
  }

  const persistedConfig = await loadPersistedDevKitSyncConfig();
  if (persistedConfig.host) {
    return persistedConfig;
  }

  return {
    host: "",
    user: DEFAULT_DEVKIT_SYNC_USER,
    port: DEFAULT_DEVKIT_SYNC_PORT
  };
}

async function loadPersistedDevKitSyncConfig() {
  try {
    const stdout = await execFilePromise("bash", [
      "-lc",
      [
        "set -e",
        "[[ -f ~/.devkit-sync.rc ]] && source ~/.devkit-sync.rc",
        "printf '%s\\n' \"${DEVKIT_SYNC_DEVKIT_IP:-}\" \"${DEVKIT_SYNC_DEVKIT_USER:-sima}\" \"${DEVKIT_SYNC_DEVKIT_PORT:-22}\""
      ].join("; ")
    ], {}, { showError: false });
    const [host = "", user = DEFAULT_DEVKIT_SYNC_USER, port = DEFAULT_DEVKIT_SYNC_PORT] = stdout.split(/\r?\n/);
    return {
      host: host.trim(),
      user: user.trim() || DEFAULT_DEVKIT_SYNC_USER,
      port: port.trim() || DEFAULT_DEVKIT_SYNC_PORT
    };
  } catch {
    return {
      host: "",
      user: DEFAULT_DEVKIT_SYNC_USER,
      port: DEFAULT_DEVKIT_SYNC_PORT
    };
  }
}

async function canPingHost(host) {
  const args = process.platform === "darwin"
    ? ["-c", "1", "-W", "1000", host]
    : ["-c", "1", "-W", "1", host];
  try {
    await execFilePromise("ping", args, { timeout: 2500 }, { showError: false });
    return true;
  } catch {
    return false;
  }
}

async function canSshHost(host, user = "sima", port = "22") {
  try {
    await execFilePromise("ssh", [
      "-p", port,
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=3",
      "-o", "StrictHostKeyChecking=no",
      "-o", "UserKnownHostsFile=/dev/null",
      `${user}@${host}`,
      "true"
    ], { timeout: 5000 }, { showError: false });
    return true;
  } catch {
    return await canPasswordSshHost(host, user, port) || await isSshPortReachable(host, port);
  }
}

async function canPasswordSshHost(host, user, port) {
  try {
    await execFilePromise("sshpass", [
      "-p", DEFAULT_DEVKIT_SYNC_PASSWORD,
      "ssh",
      "-p", port,
      "-o", "ConnectTimeout=3",
      "-o", "StrictHostKeyChecking=no",
      "-o", "UserKnownHostsFile=/dev/null",
      `${user}@${host}`,
      "true"
    ], { timeout: 5000 }, { showError: false });
    return true;
  } catch {
    return false;
  }
}

async function isSshPortReachable(host, port) {
  try {
    await execFilePromise("nc", ["-z", "-w", "3", host, port], { timeout: 5000 }, { showError: false });
    return true;
  } catch {
    if (!/^[A-Za-z0-9_.:-]+$/.test(host) || !/^[0-9]+$/.test(port)) {
      return false;
    }
    try {
      await execFilePromise("bash", [
        "-lc",
        `timeout 3 bash -c 'cat < /dev/null > /dev/tcp/${host}/${port}'`
      ], {}, { showError: false });
      return true;
    } catch {
      return false;
    }
  }
}

async function openDevKitSsh(host, user, port) {
  const config = await getDevKitSyncConfig();
  const targetHost = String(host || config.host || "").trim();
  const targetUser = String(user || config.user || DEFAULT_DEVKIT_SYNC_USER).trim();
  const targetPort = String(port || config.port || DEFAULT_DEVKIT_SYNC_PORT).trim();
  if (!targetHost) {
    vscode.window.showErrorMessage("DevKit Sync is not enabled");
    return;
  }

  const terminal = vscode.window.createTerminal(`DevKit ${targetHost}`);
  terminal.show();
  terminal.sendText(`ssh -p ${shellQuote(targetPort)} ${shellQuote(`${targetUser}@${targetHost}`)}`);
  vscode.window.showInformationMessage(`Use password '${DEFAULT_DEVKIT_SYNC_PASSWORD}' if prompted.`);
}

async function loginDeveloperPortal() {
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Signing in to SiMa Developer Portal",
      cancellable: true
    },
    async (progress, cancellationToken) => {
      progress.report({ message: "Loading Auth0 configuration..." });
      const authConfig = await loadAuthConfig();

      progress.report({ message: "Requesting device authorization..." });
      const deviceCode = await requestDeviceCode(authConfig);
      const verificationUri = deviceCode.verification_uri_complete
        || `${deviceCode.verification_uri}?user_code=${encodeURIComponent(deviceCode.user_code)}`;

      await vscode.env.openExternal(vscode.Uri.parse(verificationUri));
      progress.report({
        message: `Authorize in your browser. Code: ${deviceCode.user_code}`
      });

      const tokens = await pollForDeveloperPortalToken(
        authConfig,
        deviceCode.device_code,
        Number(deviceCode.interval || 5),
        Number(deviceCode.expires_in || 900),
        progress,
        cancellationToken
      );

      await saveDeveloperPortalTokens(tokens);
      const authState = await getDeveloperPortalAuthState();
      vscode.window.showInformationMessage(`Signed in to SiMa Developer Portal${authState.displayName ? ` as ${authState.displayName}` : ""}.`);
    }
  );
}

async function logoutDeveloperPortal() {
  try {
    await execFilePromise("sima-cli", ["logout"], {}, { showError: false });
  } catch {
    for (const file of EXTERNAL_AUTH_FILES) {
      try {
        await fs.promises.rm(file, { force: true });
      } catch {
        // Best-effort logout fallback.
      }
    }
  }

  vscode.window.showInformationMessage("Signed out of SiMa Developer Portal.");
}

async function loadAuthConfig() {
  const script = [
    "import json",
    "from sima_cli.auth.auth0 import get_auth_config",
    "print(json.dumps(get_auth_config()))"
  ].join("; ");

  const stdout = await execPythonSnippet(script);
  const authConfig = JSON.parse(stdout);
  const missing = ["CLIENT_ID", "AUDIENCE", "SCOPES", "DEVICE_CODE_URL", "TOKEN_URL"]
    .filter((key) => !authConfig[key]);
  if (missing.length > 0) {
    throw new Error(`Missing Auth0 configuration: ${missing.join(", ")}`);
  }
  return authConfig;
}

async function execPythonSnippet(script) {
  const candidates = [];
  const simaPython = await resolveSimaCliPythonExecutable();
  if (simaPython && !candidates.includes(simaPython)) {
    candidates.push(simaPython);
  }
  for (const candidate of SIMA_CLI_PYTHON_CANDIDATE_PATHS) {
    if (!candidates.includes(candidate)) {
      candidates.push(candidate);
    }
  }
  candidates.push("python3");

  const errors = [];
  for (const pythonExecutable of candidates) {
    try {
      return await execFilePromise(pythonExecutable, ["-c", script], {}, { showError: false });
    } catch (error) {
      errors.push(`${pythonExecutable}: ${error.message}`);
    }
  }

  throw new Error(`Unable to load sima-cli Python modules. ${errors.join("; ")}`);
}

async function resolveSimaCliExecutable() {
  if (simaCliExecutable !== undefined) {
    return simaCliExecutable;
  }

  const candidates = [...SIMA_CLI_CANDIDATE_PATHS];
  try {
    const pathFromShell = (await execFilePromise(
      "bash",
      ["-lc", "command -v sima-cli || true"],
      {},
      { showError: false }
    )).trim();
    if (pathFromShell) {
      candidates.push(pathFromShell);
    }
  } catch {
    // Keep the static candidates.
  }

  for (const candidate of [...new Set(candidates)]) {
    try {
      await fs.promises.access(candidate, fs.constants.X_OK);
      simaCliExecutable = candidate;
      return simaCliExecutable;
    } catch {
      // Try the next candidate.
    }
  }

  simaCliExecutable = "sima-cli";
  return simaCliExecutable;
}

async function resolveSimaCliPythonExecutable() {
  if (simaCliPythonExecutable !== undefined) {
    return simaCliPythonExecutable;
  }

  simaCliPythonExecutable = "";

  for (const candidate of SIMA_CLI_PYTHON_CANDIDATE_PATHS) {
    try {
      await fs.promises.access(candidate, fs.constants.X_OK);
      simaCliPythonExecutable = candidate;
      return simaCliPythonExecutable;
    } catch {
      // Try the next candidate.
    }
  }

  const simaCliPaths = [...SIMA_CLI_CANDIDATE_PATHS, await resolveSimaCliExecutable()];

  for (const simaCliPath of [...new Set(simaCliPaths)]) {
    try {
      const scriptText = await fs.promises.readFile(simaCliPath, "utf8");
      const firstLine = scriptText.split(/\r?\n/, 1)[0] || "";
      const shebang = firstLine.startsWith("#!") ? firstLine.slice(2).trim() : "";
      const executable = resolvePythonFromShebang(shebang);
      if (executable) {
        simaCliPythonExecutable = executable;
        return simaCliPythonExecutable;
      }
    } catch {
      // Try the next candidate.
    }
  }

  return simaCliPythonExecutable;
}

function resolvePythonFromShebang(shebang) {
  if (!shebang || !shebang.includes("python")) {
    return "";
  }

  const parts = shebang.split(/\s+/).filter(Boolean);
  if (parts[0] === "/usr/bin/env" && parts[1]?.includes("python")) {
    return parts[1];
  }
  if (parts[0]?.includes("python")) {
    return parts[0];
  }
  return "";
}

async function requestDeviceCode(authConfig) {
  return postForm(authConfig.DEVICE_CODE_URL, {
    client_id: authConfig.CLIENT_ID,
    scope: authConfig.SCOPES,
    audience: authConfig.AUDIENCE
  });
}

async function pollForDeveloperPortalToken(authConfig, deviceCode, intervalSeconds, expiresInSeconds, progress, cancellationToken) {
  let interval = Math.max(intervalSeconds, 1);
  const deadline = Date.now() + Math.max(expiresInSeconds, 60) * 1000;

  while (Date.now() < deadline) {
    if (cancellationToken.isCancellationRequested) {
      throw new Error("Developer Portal sign-in cancelled.");
    }

    await sleep(interval * 1000);
    const result = await postForm(authConfig.TOKEN_URL, {
      grant_type: "urn:ietf:params:oauth:grant-type:device_code",
      device_code: deviceCode,
      client_id: authConfig.CLIENT_ID
    }, { allowOAuthPending: true });

    if (!result.error) {
      return {
        ...result,
        timestamp: Math.floor(Date.now() / 1000)
      };
    }

    if (result.error === "authorization_pending") {
      progress.report({ message: "Waiting for browser authorization..." });
    } else if (result.error === "slow_down") {
      interval += 5;
      progress.report({ message: "Waiting for Auth0 rate limit..." });
    } else if (result.error === "expired_token") {
      throw new Error("Developer Portal sign-in expired. Start login again.");
    } else {
      throw new Error(result.error_description || result.error);
    }
  }

  throw new Error("Developer Portal sign-in expired. Start login again.");
}

async function saveDeveloperPortalTokens(tokens) {
  await fs.promises.mkdir(SIMA_CLI_DIR, { recursive: true });
  await fs.promises.writeFile(TOKEN_FILE, `${JSON.stringify(tokens, null, 2)}\n`, { mode: 0o600 });
}

async function getDeveloperPortalAuthState() {
  const tokens = await readDeveloperPortalTokens();
  if (!tokens?.access_token) {
    return {
      signedIn: false,
      buttonLabel: "Login",
      command: "loginDeveloperPortal",
      status: "Sign in to download models and other assets from SiMa Developer Portal.",
      detail: ""
    };
  }

  const claims = decodeJwtPayload(tokens.id_token || tokens.access_token);
  const displayName = claims.name || claims.nickname || extractEmail(claims) || "";
  const email = extractEmail(claims);
  const expired = !isTokenValid(tokens);

  return {
    signedIn: !expired,
    buttonLabel: expired ? "Login" : "Logout",
    command: expired ? "loginDeveloperPortal" : "logoutDeveloperPortal",
    status: expired ? "Developer Portal session expired." : "Signed in to SiMa Developer Portal.",
    detail: [displayName, email && email !== displayName ? email : ""].filter(Boolean).join(" - "),
    displayName
  };
}

async function readDeveloperPortalTokens() {
  try {
    return JSON.parse(await fs.promises.readFile(TOKEN_FILE, "utf8"));
  } catch {
    return undefined;
  }
}

function isTokenValid(tokens) {
  const issuedAt = Number(tokens?.timestamp || 0);
  const expiresIn = Number(tokens?.expires_in || 0);
  return issuedAt > 0 && expiresIn > 0 && (Date.now() / 1000 - issuedAt) < (expiresIn - 60);
}

function decodeJwtPayload(token) {
  try {
    const parts = String(token || "").split(".");
    if (parts.length !== 3) {
      return {};
    }
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload + "=".repeat((4 - payload.length % 4) % 4);
    return JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
  } catch {
    return {};
  }
}

function extractEmail(claims) {
  if (claims.email) {
    return claims.email;
  }
  for (const value of Object.values(claims)) {
    if (value && typeof value === "object" && typeof value.email === "string") {
      return value.email;
    }
  }
  return "";
}

function postForm(url, data, options = {}) {
  return new Promise((resolve, reject) => {
    const body = new URLSearchParams(data).toString();
    const request = https.request(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": Buffer.byteLength(body)
      }
    }, (response) => {
      let responseBody = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        responseBody += chunk;
      });
      response.on("end", () => {
        let payload;
        try {
          payload = JSON.parse(responseBody);
        } catch {
          reject(new Error(responseBody || `HTTP ${response.statusCode}`));
          return;
        }

        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(payload);
        } else if (options.allowOAuthPending && payload.error) {
          resolve(payload);
        } else {
          reject(new Error(payload.error_description || payload.error || `HTTP ${response.statusCode}`));
        }
      });
    });

    request.on("error", reject);
    request.write(body);
    request.end();
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function showActionError(prefix, error) {
  vscode.window.showErrorMessage(`${prefix}: ${error?.message || error}`);
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function execFilePromise(file, args, options, behavior = {}) {
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
    if (behavior.showError !== false) {
      vscode.window.showErrorMessage(error.message);
    }
    throw error;
  });
}

function getPanelHtml(logoUri, samplesState, tutorialsState, authState, devKitState) {
  const cloneDisabled = samplesState.disabled ? "disabled" : "";
  const status = escapeHtml(samplesState.status);
  const samplesDetail = formatSamplesDetail(samplesState);
  const samplesStatusLine = samplesState.detailKind ? `<p class="status">${status}${samplesDetail}</p>` : "";
  const buttonLabel = escapeHtml(samplesState.buttonLabel);
  const tutorialsDisabled = tutorialsState.disabled ? "disabled" : "";
  const tutorialsStatus = escapeHtml(tutorialsState.status);
  const tutorialsDetail = formatSamplesDetail(tutorialsState);
  const tutorialsStatusLine = tutorialsState.detailKind ? `<p class="status">${tutorialsStatus}${tutorialsDetail}</p>` : "";
  const tutorialsButtonDescription = tutorialsState.detailKind ? "" : tutorialsStatus;
  const tutorialsButtonLabel = escapeHtml(tutorialsState.buttonLabel);
  const tutorialsIcon = tutorialsState.disabled ? "ok" : "book";
  const authStatus = escapeHtml(authState.status);
  const authDetail = escapeHtml(authState.detail);
  const authButtonLabel = escapeHtml(authState.buttonLabel);
  const authCommand = escapeHtml(authState.command);
  const authIcon = authState.signedIn ? "lock" : "out";
  const cloneIcon = samplesState.disabled ? "ok" : "repo";
  const devKitDisabled = devKitState.disabled ? "disabled" : "";
  const devKitButtonLabel = escapeHtml(devKitState.buttonLabel);
  const devKitStatus = escapeHtml(devKitState.status);
  const devKitDetail = formatDevKitDetail(devKitState);
  const devKitHost = escapeHtml(devKitState.host);
  const devKitUser = escapeHtml(devKitState.user);
  const devKitPort = escapeHtml(devKitState.port);
  const devKitIcon = devKitState.online ? "terminal" : "offline";

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${logoUri.scheme}:; script-src 'unsafe-inline'; style-src 'unsafe-inline';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {
      margin: 0;
      padding: 16px;
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      font-family: var(--vscode-font-family);
    }

    .masthead {
      display: grid;
      grid-template-columns: 56px 1fr;
      gap: 12px;
      align-items: center;
      margin-bottom: 16px;
    }

    .logo {
      display: block;
      width: 56px;
      height: auto;
    }

    .title {
      margin: 0 0 3px;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0;
    }

    p {
      margin: 0 0 14px;
      line-height: 1.45;
      color: var(--vscode-descriptionForeground);
    }

    .subtitle {
      margin: 0;
      font-size: 12px;
    }

    .panel-section {
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      padding: 12px;
      background: var(--vscode-editor-background);
      margin-bottom: 12px;
    }

    .section-title {
      margin-bottom: 8px;
      color: var(--vscode-foreground);
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
    }

    .stack {
      display: grid;
      gap: 8px;
    }

    .quick-links {
      display: grid;
      gap: 8px;
      margin-bottom: 12px;
    }

    button {
      width: 100%;
      min-height: 34px;
      border: 0;
      border-radius: 4px;
      padding: 7px 10px;
      color: var(--vscode-button-foreground);
      background: var(--vscode-button-background);
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }

    .action-button {
      display: grid;
      grid-template-columns: 26px 1fr auto;
      gap: 9px;
      align-items: center;
      min-height: 48px;
      border: 1px solid var(--vscode-panel-border);
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      text-align: left;
      padding: 8px;
    }

    .action-button:hover:not(:disabled) {
      background: var(--vscode-list-hoverBackground);
    }

    .icon-badge {
      display: grid;
      width: 26px;
      height: 26px;
      place-items: center;
      border-radius: 5px;
      color: var(--vscode-button-foreground);
      background: var(--vscode-button-background);
      font-size: 13px;
      font-weight: 700;
      line-height: 1;
    }

    .icon-badge.secondary {
      color: var(--vscode-button-secondaryForeground);
      background: var(--vscode-button-secondaryBackground);
    }

    .icon-badge.teal {
      color: #ffffff;
      background: #008c95;
    }

    .badge-icon {
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .github-icon {
      fill: currentColor;
      stroke: none;
    }

    .action-copy {
      min-width: 0;
    }

    .action-title {
      display: block;
      margin-bottom: 2px;
      color: var(--vscode-foreground);
      font-size: 12px;
      font-weight: 700;
      line-height: 1.25;
    }

    .action-description {
      display: block;
      color: var(--vscode-descriptionForeground);
      font-size: 11px;
      font-weight: 400;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }

    .external-mark {
      color: var(--vscode-descriptionForeground);
      font-size: 14px;
    }

    button:hover:not(:disabled) {
      background: var(--vscode-button-hoverBackground);
    }

    button:disabled {
      opacity: 0.55;
      cursor: default;
    }

    button.secondary {
      border: 1px solid var(--vscode-button-border, transparent);
      color: var(--vscode-button-secondaryForeground);
      background: var(--vscode-button-secondaryBackground);
    }

    button.secondary:hover:not(:disabled) {
      background: var(--vscode-button-secondaryHoverBackground);
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

    code {
      border: 1px solid var(--vscode-panel-border);
      border-radius: 4px;
      padding: 1px 4px;
      color: var(--vscode-textPreformat-foreground);
      background: var(--vscode-textCodeBlock-background);
      font-family: var(--vscode-editor-font-family);
      font-size: 11px;
    }

    .inline-detail {
      display: inline;
    }
  </style>
</head>
<body>
  <div class="masthead">
    <img class="logo" src="${logoUri}" alt="SiMa.ai">
    <div>
      <h1 class="title">Palette Neat</h1>
      <p class="subtitle">Build, inspect, and manage SDK workspaces.</p>
    </div>
  </div>
  <div class="quick-links">
    ${actionButton("openDocumentation", "docs", "Documentation", "developer.sima.ai/software", true)}
    ${actionButton("openInsight", "eye", "Insight", "Open detected Insight web UI", true)}
  </div>
  <div class="panel-section">
    <div class="section-title">DevKit Sync</div>
    <div class="stack">
      <button id="devKitSsh" class="action-button ${devKitState.online ? "" : "secondary"}" data-host="${devKitHost}" data-user="${devKitUser}" data-port="${devKitPort}" ${devKitDisabled}>
        <span class="icon-badge ${devKitState.online ? "" : "secondary"}" aria-hidden="true">${iconText(devKitIcon)}</span>
        <span class="action-copy">
          <span class="action-title">${devKitButtonLabel}</span>
          <span class="action-description">${devKitStatus}${devKitDetail}</span>
        </span>
      </button>
    </div>
  </div>
  <div class="panel-section">
    <div class="section-title">Developer Portal</div>
    <div class="stack">
      <button id="developerPortalAuth" class="action-button ${authState.signedIn ? "secondary" : ""}" data-command="${authCommand}">
        <span class="icon-badge ${authState.signedIn ? "secondary" : ""}" aria-hidden="true">${iconText(authIcon)}</span>
        <span class="action-copy">
          <span class="action-title">${authButtonLabel}</span>
          <span class="action-description">${authStatus}</span>
        </span>
      </button>
      <p class="detail">${authDetail}</p>
    </div>
  </div>
  <div class="panel-section">
    <div class="section-title">Tutorials</div>
    <div class="stack">
      <button id="installTutorials" class="action-button" ${tutorialsDisabled}>
        <span class="icon-badge teal" aria-hidden="true">${iconText(tutorialsIcon)}</span>
        <span class="action-copy">
          <span class="action-title">${tutorialsButtonLabel}</span>
          ${tutorialsButtonDescription ? `<span class="action-description">${tutorialsButtonDescription}</span>` : ""}
        </span>
      </button>
      ${tutorialsStatusLine}
    </div>
  </div>
  <div class="panel-section">
    <div class="section-title">Samples</div>
    <div class="stack">
      <button id="cloneSamples" class="action-button" ${cloneDisabled}>
        <span class="icon-badge teal" aria-hidden="true">${iconText(cloneIcon)}</span>
        <span class="action-copy">
          <span class="action-title">${buttonLabel}</span>
          <span class="action-description">${status}</span>
        </span>
      </button>
      ${samplesStatusLine}
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
    const tutorialsButton = document.getElementById("installTutorials");
    tutorialsButton?.addEventListener("click", () => {
      tutorialsButton.disabled = true;
      vscode.postMessage({ command: "installTutorials" });
    });
    const authButton = document.getElementById("developerPortalAuth");
    authButton?.addEventListener("click", () => {
      authButton.disabled = true;
      authButton.textContent = authButton.dataset.command === "logoutDeveloperPortal" ? "Signing out..." : "Signing in...";
      vscode.postMessage({ command: authButton.dataset.command });
    });
    const devKitButton = document.getElementById("devKitSsh");
    devKitButton?.addEventListener("click", () => {
      vscode.postMessage({
        command: "openDevKitSsh",
        host: devKitButton.dataset.host,
        user: devKitButton.dataset.user,
        port: devKitButton.dataset.port
      });
    });
    document.querySelectorAll(".quick-links .action-button[data-command]").forEach((button) => {
      button.addEventListener("click", () => {
        vscode.postMessage({ command: button.dataset.command });
      });
    });
  </script>
</body>
</html>`;
}

function actionButton(command, icon, title, description, external) {
  return `<button class="action-button" data-command="${escapeHtml(command)}">
    <span class="icon-badge" aria-hidden="true">${iconText(icon)}</span>
    <span class="action-copy">
      <span class="action-title">${escapeHtml(title)}</span>
      <span class="action-description">${escapeHtml(description)}</span>
    </span>
    ${external ? '<span class="external-mark" aria-hidden="true">></span>' : ""}
  </button>`;
}

function iconText(name) {
  const icons = {
    docs: "D",
    eye: "I",
    lock: '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path></svg>',
    out: "Out",
    ok: "OK",
    book: '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H7a3 3 0 0 0-3 3V5.5Z"></path><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path></svg>',
    repo: '<svg class="badge-icon github-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5a9.5 9.5 0 0 0-3 18.51c.47.08.64-.2.64-.45v-1.65c-2.6.57-3.15-1.1-3.15-1.1-.43-1.08-1.05-1.37-1.05-1.37-.86-.59.07-.58.07-.58.95.07 1.45.98 1.45.98.84 1.44 2.2 1.02 2.74.78.08-.61.33-1.02.6-1.26-2.08-.24-4.27-1.04-4.27-4.64 0-1.02.37-1.86.97-2.52-.1-.24-.42-1.2.09-2.48 0 0 .79-.25 2.6.96a9 9 0 0 1 4.73 0c1.8-1.21 2.6-.96 2.6-.96.51 1.28.19 2.24.09 2.48.6.66.97 1.5.97 2.52 0 3.61-2.2 4.4-4.29 4.63.34.29.64.86.64 1.74v2.58c0 .25.17.54.65.45A9.5 9.5 0 0 0 12 2.5Z"></path></svg>',
    terminal: '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1.5"></rect><path d="M4 9h3M4 15h3M17 9h3M17 15h3M9 4v3M15 4v3M9 17v3M15 17v3"></path></svg>',
    offline: "!"
  };
  return icons[name] || "";
}

function formatSamplesDetail(samplesState) {
  const detail = escapeHtml(samplesState.detail);
  if (!detail) {
    return "";
  }
  if (samplesState.detailKind === "path-folder") {
    return ` <span class="inline-detail"><code>${detail}</code> folder</span>`;
  }
  return ` <span class="inline-detail">${detail}</span>`;
}

function formatDevKitDetail(devKitState) {
  const detail = escapeHtml(devKitState.detail);
  if (!detail) {
    return "";
  }
  if (devKitState.detailKind === "command") {
    return ` <code>${detail}</code> to setup DevKit Sync`;
  }
  return ` ${detail}`;
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
