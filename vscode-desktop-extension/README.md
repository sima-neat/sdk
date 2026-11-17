# SiMa Neat Tools

A small VS Code extension that installs `sima-cli`, the SiMa.ai developer CLI, and makes it available in VS Code terminals.

## Features

- **Status bar item.** Shows **Install sima-cli** when it is missing. Once it's installed, it shows `sima-cli <version>` with your login state: `$(account)` when you're logged in, **Log in** when you're not.
  - **Click it** for a menu: log in or out, open a sima-cli terminal, check, or install/update.
  - **Hover over it** to see who you're logged in as, with one-click **Log in** / **Log out** links.
  - It updates by itself when you log in or out from any terminal, because it watches `~/.sima-cli`.
- **Login and logout**, matching sima-cli's two kinds of login:
  - **Developer Portal** (`sima-cli login`): a browser device-code flow. It runs in a terminal so you can open the link and see the code.
  - **Internal, for SiMa employees** (`sima-cli --internal login`): paste an Artifactory identity token. These actions are hidden unless the `simaNeat.showInternalLogin` setting is on or an internal login already exists. The menu also shows when the internal token has expired.
  - Logout runs `sima-cli logout` (or `sima-cli --internal logout`) in the background.
- **Startup prompt.** Offers to install `sima-cli` when it is missing. Turn this off with the `simaNeat.promptToInstall` setting.
- **Commands** (Command Palette, `SiMa Neat:` prefix): `Open Neat Setup`, `Open SDK in VS Code`, `Connect Claude Code to VS Code`, `Disconnect Claude Code from VS Code`, `Show Agent Tool Log`, `Show sima-cli Menu`, `Log In to Developer Portal`, `Log Out of Developer Portal`, `Log In (Internal)`, `Log Out (Internal)`, `Install or Update sima-cli`, `Check sima-cli`, `Open sima-cli Terminal`.
- **Terminal PATH.** The installer only adds `sima-cli` to `PATH` in a shell profile file, which VS Code terminals don't always read (for example `.bash_profile` in the Neat SDK container). When `sima-cli` is installed but not on `PATH`, the extension adds its folder to `PATH` for new integrated terminals.

## SiMa Neat Setup page

A step-by-step page for installing the Neat SDK on this computer. It opens the first time the extension starts. Open it again any time from the status bar menu or with **SiMa Neat: Open Neat Setup**.

1. **sima-cli:** install or update it.
2. **Log in** to the Developer Portal. Recommended; the Model Compiler and Model Zoo downloads need it.
3. **Check this computer:**
   - the host OS;
   - Docker is installed, running, and usable by your user;
   - free disk space;
   - `ethtool`.

   Each problem comes with a fix.
4. **Download the SDK image.** Pick a version: the latest release, `main`, `develop` or a release branch. The list comes from GitHub releases and the Neat artifacts server, and each version's image comes from its package metadata, the same way `sima-cli neat install sdk@<version>` does it.
   - The download runs `sima-cli install ghcr:<image>` with live progress.
   - Network errors are retried automatically (`simaNeat.sdk.pullRetries`, default 4) with increasing waits. Each retry continues from the layers already downloaded.
   - You can cancel and resume. The download keeps going if you close the page. After a restart, an unfinished download is offered for resume.
   - Problems a retry can't fix are reported with a fix and not retried: Docker not running, no Docker permission, a full disk, an unknown version. If sima-cli needs to ask something, like GitHub authorization, the page offers to run the download in a terminal.
5. **Configure:** DevKit pairing and IP, Model Compiler, coding agent extensions, Edgematic Studio, and the workspace folder. Answers are saved as `simaNeat.sdk.*` settings.
6. **Start the SDK:** shows the exact `sima-cli sdk setup -n -y …` command and runs it on the page, with a live status line and a log that shows the time since start for each line. `-n` makes setup take its defaults instead of asking, and `-y` lets it continue past failed host checks (sima-cli's firewall check fails wherever `ufw` is installed, even inactive). The Model Compiler and Edgematic Studio choices are always passed explicitly, so `-y` doesn't install them. If setup exits with an error, the page shows it as failed, even when the previous container is still running. If it needs your sudo password (to share the workspace with a DevKit), a password box opens at the top of VS Code; the password goes straight to sudo and isn't logged. **Stop** ends it, and **Run in a terminal instead** runs the same command in a terminal. If an SDK container already exists, it warns that setup recreates it.
7. **Ready:**
   - **Open in VS Code** switches this VS Code into the SDK container. See below. When setup succeeds, this happens automatically (`simaNeat.sdk.openAfterSetup`).
   - **Open browser IDE** opens the SDK's browser IDE and copies its password to the clipboard.
   - **Open SDK shell** runs `sima-cli sdk neat`.
   - **Run diagnostics** runs `sima-cli sdk doctor`.

**Start over**, at the bottom of the page, removes what setup installed so you can begin again at step 1. Choose any of: the SDK containers, the SDK images (downloaded again in step 4), this extension's settings and progress together with Dev Containers' saved settings for SDK containers, your sima-cli login, and sima-cli itself (`~/.sima-cli`). A confirmation lists exactly what will go. Your workspace folder is always kept. Only Neat SDK containers and images are touched; `sima-cli sdk remove` would also delete every other unused Docker image.

## Neat SDK pages

The pages of SiMa's own SDK extension, brought to your desktop VS Code. They show the running SDK container: the one this window is attached to, else the one you last opened in VS Code, else the first running one. They work in any window, with or without attaching.

- **Getting Started** (**SiMa Neat: Getting Started**): the SDK version and the CPU and memory available to it, the DevKit's model, software version and connection (**Connect** opens `dk shell`), and tabs for Apps (clone `sima-neat/apps` into the workspace), Models, Insight, coding agents (Codex, Claude Code) and docs.
- **Palette panel**, in the activity bar: Getting Started, Open SDK in VS Code, docs, Insight, the Model Registry, DevKit Sync status and SSH, Developer Portal login, tutorials, and samples.
- **Insight** (**SiMa Neat: Open Insight**) in an editor tab, at `https://localhost:<port>` as Docker publishes it, with **Open in browser** if it doesn't load.
- **Browse Models** (**SiMa Neat: Browse Models**): search the Model Registry, open model cards, download prebuilt builds or copy model sources. It uses sima-cli on this computer; files go into `<workspace>/models`, which the container sees as `/workspace/models`.

They read container data with `docker exec`: `/etc/sdk-release`, `neat --json`, DevKit Sync settings, and DevKit checks over SSH from inside the container. See `neat/NOTICE.md` in the extension folder for what was ported and what changed.

## Open SDK in VS Code

The SDK's compilers, PyNeat and the `dk` DevKit commands only exist inside the SDK container. **Open SDK in VS Code** connects this desktop VS Code to that container with Microsoft's Dev Containers extension ("Attach to Running Container") and opens `/workspace`. It's the same folder as your workspace folder on this computer, and the paired DevKit mounts it too, so build outputs and results show up everywhere without copying.

It's on the setup page, in the status bar menu, and in the Command Palette (**SiMa Neat: Open SDK in VS Code**). Each time, it:

1. Makes sure Dev Containers is installed. VS Code installs it together with this extension, which lists it in `extensionPack`; if you removed it since, it's installed again here without asking.
2. Starts the container if it's stopped, with `docker start` like sima-cli does. It never lets Dev Containers create the container: only `sima-cli sdk setup` sets up the SDK's network, ports and DevKit pairing correctly.
3. Prepares the container for VS Code:
   - It saves Dev Containers settings for the container: open `/workspace`, install the extensions in `simaNeat.sdk.containerExtensions` while attaching (default: Claude Code; remove it from the list to skip it), and don't forward ports Docker already publishes on this computer. Settings you added to that file yourself are kept.
   - Only if `simaNeat.sdk.installSdkExtension` is on: it installs the SDK image's own Neat extension into the container's VS Code Server, with the image's `sima-install-neat-extension`. It's off by default because this extension already shows the same pages. Recreating the container with setup removes the container's VS Code Server, so this runs on every open.
4. Opens the container in this window if it's empty, otherwise in a new window. With several SDK containers, it asks which one and remembers your choice.

The first time, Dev Containers asks you to confirm that you trust the container ("Attaching to a container may execute arbitrary code"). Click **Got It**. It's Dev Containers' own one-time security question and is never asked again in that VS Code profile; Settings Sync carries the answer to your other machines. Extensions can't answer it for you.

While the SDK opens, an item on the right of the status bar shows each step: starting the container, preparing VS Code, connecting, then in the SDK window installing Claude Code, connecting it to VS Code (see Coding agents below), opening it, and finally "Neat SDK: ready". (While Dev Containers connects the new window, its own "Connecting to Dev Container" notice shows instead: no extension runs in that window yet.)

When the SDK window opens, Welcome pages are closed (VS Code's and Claude Code's first-run walkthrough) and SiMa Getting Started opens instead, unless the window already has editors open. It also gets a terminal in `/workspace` at the bottom (it runs in the container, so `dk` and the toolchain work there) and Claude Code on the right, without asking. On a first attach it waits for Dev Containers to finish installing Claude Code. Turn this off with `simaNeat.sdk.windowLayout`.

When VS Code opens an empty window and an SDK container exists, the extension offers to open it (`simaNeat.sdk.openOnStartup`: `ask`, `always` or `never`).

Inside the SDK window, this extension keeps running on your computer, not in the container. Its terminals (sima-cli install and login, the setup page, the SDK shell) run on your computer too, even though the window's own terminals run in the container. The status bar shows your login on this computer; the container has its own sima-cli login.

Dev Containers is only available in Microsoft's VS Code builds. In VSCodium and other builds, use the browser IDE.

## Coding agents in VS Code (prototype)

Coding agents can act in your VS Code window through tools this extension serves. For now there's one: **`open_insight`**, which opens Insight in an editor tab, the same as **SiMa Neat: Open Insight**. Ask Claude "open Insight", or let it open Insight after starting a pipeline.

- **Claude Code connects by itself.** When Claude Code is on this computer, as the `claude` command or the Claude Code extension, the extension registers its tools with it without asking. It checks at startup and right after an extension is installed, and the status bar shows the progress. It runs `claude mcp add --scope user sima-neat-vscode …`, so every Claude Code session on this computer gets the tools, in a terminal and in the Claude Code extension. Sessions that are already running pick them up after a restart. It registers again only if the registration is missing or outdated.
- **Claude Code in the SDK container** (the one in the SDK window's side bar) is connected too. The container can't reach this computer's `127.0.0.1`, so a window attached to an SDK container keeps a small relay running inside it over `docker exec`. The relay and the bridge are installed in the container's `~/.sima-neat-vscode` (not in your workspace). The relay serves the tools on a socket there, readable only by you, and passes each request to the window over `docker exec`'s input and output. This works the same with Docker on Linux, macOS and Windows. The relay stops when the window closes, and the window restarts it if it stops early, for example when the container restarts. Before the SDK window opens Claude Code, the extension registers the bridge with the container's Claude Code (with `docker exec`, using the `claude` that comes with the Claude Code extension), so Claude's first session already has the tools. That bridge only uses windows attached to its own container.
- **To stop it,** run **SiMa Neat: Disconnect Claude Code from VS Code** (also in the status bar menu). That removes the registration and turns off `simaNeat.agents.connectClaudeCode`, so it isn't added again. **Connect Claude Code to VS Code** turns it back on.
- **How it works:** each VS Code window serves its tools as an MCP server on `127.0.0.1`, on a random port, with a random token. It writes the port and token to `~/.sima-neat-vscode/windows/<pid>.json`, readable only by you. Claude starts `~/.sima-neat-vscode/bridge.js`, which passes each tool call to a window: the one whose terminal Claude was started in, else the one whose folder contains Claude's working folder, else the one you used last.
- **Log:** **SiMa Neat: Show Agent Tool Log** lists every tool call and its result.
- **Turn the tools off** in VS Code with `simaNeat.agents.enabled`.

## How it installs sima-cli

It runs the same installer as the sima-cli README:

| Platform | Installer | Install location |
| --- | --- | --- |
| Linux, macOS | `https://artifacts.neat.sima.ai/sima-cli/linux-mac.sh` | `~/.sima-cli/.venv/bin` |
| DevKit | same script | `/data/sima-cli/.venv/bin` |
| Windows | `https://artifacts.neat.sima.ai/sima-cli/windows.bat` | `%USERPROFILE%\.sima-cli-env\Scripts` |

The extension is a `ui` extension: it always runs on the computer where VS Code runs, including in remote and container windows, because that's where Docker and the SDK installation are.

## Where it lives

This extension is meant to sit in [sima-neat/sdk](https://github.com/sima-neat/sdk) as `vscode-desktop-extension/`, next to `vscode-extension/`, the SDK's own extension (`sima-neat.sima-neat`):

| Folder | Extension | Runs |
| --- | --- | --- |
| `vscode-extension/` | `sima-neat.sima-neat` | Inside the SDK container. It is installed in the SDK image. |
| `vscode-desktop-extension/` | `sima-neat.sima-neat-desktop` (this one) | In desktop VS Code, on your computer. It isn't part of the image. |

The pages in `neat/` are ported from the SDK extension; `neat/NOTICE.md` lists what changed. There's no CI workflow for this extension yet: run the tests and package it yourself.

## Tests

```bash
npm test
```

No dependencies, Node.js 18 or later. The tests cover the agent tools: the MCP server, the bridge agents start, and the relay that serves Claude Code in an SDK container. The relay test runs with a fake `docker` and needs neither Docker nor a container. To also run it in a real, running SDK container (in its own folder there, `~/.sima-neat-vscode-test`, so an attached VS Code window keeps working):

```bash
SIMA_NEAT_TEST_CONTAINER=<container name> npm test
```

## Build and install from file

No dependencies and no build step. Packaging needs Node.js and network access for `npx`:

```bash
npm run package
```

This produces `sima-neat-desktop-<version>.vsix`. Install it with **Extensions → ⋯ → Install from VSIX…**, or from the command line:

```bash
code --install-extension sima-neat-desktop-<version>.vsix
```

Installing a newer `.vsix` replaces the older version. Before 0.0.21 the extension was `local-dev.sima-neat-vsext`: uninstall that one first, because both register the same commands.

## Before publishing

- `license` is `UNLICENSED` and `LICENSE` matches the SDK extension's: not licensed for redistribution yet.
- Add an `icon`.
- Add a CI workflow that runs `npm test` and packages the `.vsix`, like `.github/workflows/vscode-extension.yml` does for the SDK extension.

## Testing from a clean state

Test in a throwaway VS Code profile, so nothing from earlier runs carries over:

```bash
code --user-data-dir ~/vscode-clean/data --extensions-dir ~/vscode-clean/ext --install-extension sima-neat-desktop-<version>.vsix
code --user-data-dir ~/vscode-clean/data --extensions-dir ~/vscode-clean/ext --new-window
```

Before each test, close that VS Code and run `scripts/reset-clean-test.sh`. It deletes the throwaway profile (settings, extensions, restored windows, Dev Containers' saved answers and per-container settings). It also deletes VS Code Server in every running SDK container, which holds the extensions installed while attached. Your normal VS Code profile and your workspace folder aren't touched. A normal VS Code window attached to one of those containers reconnects with a fresh server.
