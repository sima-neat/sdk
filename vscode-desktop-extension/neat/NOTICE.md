# Ported from the SDK's VS Code extension

The pages in this folder come from SiMa's own extension, `sima-neat.sima-neat` ("Palette SDK Development Environment"), in [sima-neat/sdk `vscode-extension/`](https://github.com/sima-neat/sdk/tree/develop/vscode-extension) at commit `a1c4c02`. That extension runs inside the SDK container. These run on your computer and reach the container through `../container.js` (`docker exec`).

| File | Status | Changes |
| --- | --- | --- |
| `insight-launcher.js`, `landing-data.js`, `registry-state.js`, `panel-status.js`, `sdk-capabilities.js`, `unpack-model.py` | Unchanged | They take a file reader and a command runner as parameters; we pass ones that work in the container. |
| `landing-page.js` | Adapted | Its own view type. Coding agents install the latest Marketplace version into this VS Code: the SDK's qualified-version catalog (`components.js`) reads code-server's version files, which don't exist here. "Connect" runs `dk shell` in the container. |
| `palette-panel.js` | Adapted from `NeatPanelProvider` and `getPanelHtml` in `src/extension.js` | Login uses this extension's sima-cli login. The script and styles moved to `media/neat/panel.js` and `panel.css` with a nonce CSP. Adds the container name, Getting Started and Open SDK in VS Code. No session countdown (an Arthas feature). |
| `insight-view.js` | Adapted | Insight on `localhost`, the port Docker publishes. A bar with Reload and Open in browser. |
| `model-registry.js` | Adapted | Uses this computer's sima-cli. Files go into the SDK workspace folder (`/workspace` in the container) without asking for a workspace. |
| `services.js` | New | Host-side versions of the SDK extension's helpers: DevKit checks, samples, tutorials, Insight address. |
| `media/neat/landing/*`, fonts, logos | Copied | Small wording changes for running outside the container. |

Not ported: the themes and their editor defaults (they'd change your desktop VS Code's theme and fonts), the session countdown, browser-IDE-only behavior (menu bar, startup page, camera permission patch), and the SDK's own login flow.

When the SDK extension changes upstream, compare its `vscode-extension/src` with this folder.
