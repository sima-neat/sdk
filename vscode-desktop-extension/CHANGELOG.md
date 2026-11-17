# Changelog

## 0.0.21

- Ready to move into [sima-neat/sdk](https://github.com/sima-neat/sdk) as `vscode-desktop-extension/`, next to the SDK's own extension. The extension ID is now `sima-neat.sima-neat-desktop` (was `local-dev.sima-neat-vsext`): uninstall the old one, because both register the same commands. Settings carry over; the state the old one remembered (last container, first run) doesn't.
- `LICENSE` and `repository`, the same as the SDK extension's; packaging no longer skips them.
- `npm test`: tests for the MCP server, the bridge, and the relay into SDK containers, which runs with a fake `docker`, or in a real container with `SIMA_NEAT_TEST_CONTAINER`.
- Fixed, found by the tests: a `docker exec` command that ended without reading its input could raise an uncaught error in the extension host.

## 0.0.20

- Claude Code in the SDK container now reaches VS Code through a relay over `docker exec`, instead of a socket in the shared workspace. It works the same on Linux, macOS and Windows: Docker Desktop for macOS can't pass a socket from the shared folder into a container, but `docker exec` works everywhere. The relay runs in the container from `~/.sima-neat-vscode`, serves the tools on a socket there, and passes each request to the window over `docker exec`'s input and output. It stops when the window closes, and the window restarts it if it stops early, for example when the container restarts.
- Nothing goes in your workspace any more: the `.sima-neat-vscode` folder that 0.0.19 created there is removed.
- `scripts/reset-clean-test.sh` no longer stops silently partway: its own `pkill` matched the script and killed it. It also removes the relay files from each container and reports a container it couldn't reset.

## 0.0.19

- Claude Code in the SDK container, the one in the SDK window's side bar, can now open Insight too. The window serves its tools on a socket in the shared workspace (`<workspace>/.sima-neat-vscode`, which is `/workspace/.sima-neat-vscode` in the container), and registers the bridge with the container's Claude Code before opening it, so its first session already has `open_insight`. The status bar shows "connecting Claude Code to VS Code…" as one more step of setting up the SDK window. If connecting fails, the window still finishes, with "ready, Claude Code not connected" and the reason.
- Connect and Disconnect in the status bar menu also cover the container's Claude Code in an SDK window.

## 0.0.18

- Claude Code connects to VS Code by itself, without asking: at startup, and right after the Claude Code extension is installed, if Claude Code is on this computer and isn't connected (or is connected with an outdated command). The status bar shows "Connecting Claude Code to VS Code…", then the result. **SiMa Neat: Disconnect Claude Code from VS Code** removes it and stops reconnecting (`simaNeat.agents.connectClaudeCode`). The status bar menu shows Connect or Disconnect, whichever applies.

## 0.0.17

- Prototype: coding agents can act in VS Code. Each window serves an `open_insight` tool to agents (MCP, on 127.0.0.1 with a private token), so Claude Code can open Insight in an editor tab by itself. **SiMa Neat: Connect Claude Code to VS Code** registers it with Claude Code; the extension offers this once when Claude Code is installed. **SiMa Neat: Show Agent Tool Log** shows every call. Turn it off with `simaNeat.agents.enabled`.

## 0.0.16

- Progress on the right of the status bar while the SDK opens in VS Code: starting the container, preparing VS Code, connecting. Then, in the SDK window: installing or starting Claude Code in the container, opening it, and "Neat SDK: ready" for a few seconds. If Claude Code doesn't start, the item says so; hover it for what to do.

## 0.0.15

- A window opened in an SDK container shows SiMa Getting Started in the editor, in place of the Welcome pages, when it has no other editors open. Reopened windows keep the tabs they had.
- `scripts/reset-clean-test.sh` quits the clean VS Code reliably: it now stops its main process, whose rewritten command line the old match missed.

## 0.0.14

- Fixed: setup stopped after two seconds. With `-n`, sima-cli aborts when a host check fails instead of asking, and its firewall check fails on any computer with `ufw` installed, even when ufw is inactive ("inactive" contains "active"). Setup now also passes `-y`, which continues past failed checks the way answering "yes" did in the terminal. The Model Compiler and Edgematic Studio choices stay explicit, so `-y` doesn't install them.
- Fixed: a failed setup looked successful when the previous SDK container was still running, and VS Code switched into that old container. Now any non-zero exit is shown as a failure, with the log open, and nothing is opened.

## 0.0.13

- SDK setup runs on the setup page instead of in a terminal, with `-n` so it takes its defaults instead of asking. The page shows its progress and a log with the time of each line. If setup needs your sudo password, VS Code asks for it in a password box. **Run in a terminal instead** is still there.
- "Ask me during setup" is gone from the coding agents choice: setup no longer asks questions.
- In the SDK window, Claude Code opens on the right once it has started in the container, and VS Code's Welcome page and Claude Code's first-run walkthrough are closed.

## 0.0.12

- **Start over** at the bottom of the setup page removes what setup installed, so you can run it again from step 1. You choose what goes: SDK containers, SDK images, this extension's settings and progress (with Dev Containers' saved settings for SDK containers), your sima-cli login, or sima-cli itself. A confirmation lists exactly what will be removed. Your workspace folder is always kept. It only removes Neat SDK containers and images, unlike `sima-cli sdk remove`, which also deletes every unused Docker image.

## 0.0.11

- Claude Code is installed in the SDK container while VS Code attaches, and opens on the right when the window appears, without asking. To skip it, remove `anthropic.claude-code` from `simaNeat.sdk.containerExtensions`; it's then also taken out of Dev Containers' saved list, so new containers don't get it.

## 0.0.10

- A window opened in an SDK container is set up for work: a terminal in `/workspace` at the bottom, connected to the container, and Claude Code in the secondary side bar on the right. If Claude Code isn't installed in the container, you're asked first (Install, Not now, Don't ask again). Turn it off with `simaNeat.sdk.windowLayout`.

## 0.0.9

- Opening the SDK in VS Code no longer installs Claude Code in the container. `simaNeat.sdk.containerExtensions` is empty by default; choosing a coding agent will be a separate step.
- Opening the SDK in VS Code removes the SDK image's own Neat extension from the container, if an earlier version put it there, so its Palette view and status bar item don't show next to this extension's. `simaNeat.sdk.installSdkExtension` still turns it on.
- `scripts/reset-clean-test.sh` resets the throwaway test profile and the VS Code Server in running SDK containers, for testing from a clean state.

## 0.0.8

- In a window attached to the SDK container (or any remote window), this extension's terminals now run on your computer, where sima-cli and Docker are: installing sima-cli, logging in, the setup page's download, setup and diagnostics, the sima-cli terminal, the SDK shell, and DevKit terminals. Before, VS Code started them inside the container. Passwords, prompts and Ctrl+C work as usual.

## 0.0.7

- The SDK extension's pages, ported to run from your computer: **Getting Started**, the **Palette** panel in the activity bar, **Insight** in an editor tab, and **Browse Models**. They read the running SDK container with `docker exec`, so they work with or without opening the container in VS Code. See `neat/NOTICE.md`.
- The status bar menu has the new pages.
- Opening the SDK in VS Code no longer installs the SDK image's own Neat extension, to avoid showing the same pages twice. Turn it back on with `simaNeat.sdk.installSdkExtension`.

## 0.0.6

- The setup page explains Dev Containers' one-time question about trusting the container.

## 0.0.5

- Dev Containers is installed together with this extension, and installed without asking if it's missing when you open the SDK.

## 0.0.4

- New **Open SDK in VS Code**: switches this desktop VS Code into the Neat SDK container at `/workspace` with Dev Containers. It installs Dev Containers when it's missing, starts a stopped container, installs the SDK's Neat extension and Claude Code in the container, and doesn't duplicate ports Docker already publishes.
- After SDK setup succeeds, VS Code switches into the container automatically. An empty window offers to open the SDK container (`simaNeat.sdk.openOnStartup`).
- The extension now always runs on your computer (`extensionKind: ui`), also in container and remote windows.

## 0.0.3

- New **SiMa Neat Setup** page that installs the Neat SDK step by step: sima-cli, login, host checks, image download, configuration, setup, and links to the running SDK.
- The SDK image downloads with `sima-cli install`. Network errors are retried automatically with increasing waits, continuing from the layers already downloaded, and you can cancel and resume. The download keeps running if you close the page, and an interrupted download is offered for resume after a restart.
- Setup answers (DevKit, Model Compiler, coding agents, Edgematic Studio, workspace) are saved as settings and passed to `sima-cli sdk setup`, so setup only stops for passwords.
- The page opens on first install, and from the status bar menu or **SiMa Neat: Open Neat Setup**.

## 0.0.2

- Log in and out of the SiMa Developer Portal, and optionally of internal SiMa services.
- Status bar item shows login state. Clicking it opens a menu of all actions, and hovering shows quick Log in / Log out links.
- Status bar follows logins and logouts made from any terminal.

## 0.0.1

- Install or update sima-cli with the official installer.
- Status bar item and startup prompt when sima-cli is missing.
- Add the sima-cli virtualenv to the integrated terminal PATH when needed.
