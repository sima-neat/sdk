# SiMa Neat VS Code Extension

Experimental VS Code extension scaffold for SiMa Neat SDK workspaces.

## Features

- Adds a SiMa Neat activity bar container.
- Shows a Neat webview panel with SDK-oriented placeholder content.
- Adds Developer Portal Login/Logout controls that store tokens in the same `~/.sima-cli/.tokens.json` cache used by `sima-cli`.
- Contributes `SiMa Neat Light` and `SiMa Neat Dark` themes.

## Development

Open this directory in VS Code or OpenVSCode Server and run the extension host.

The extension is intentionally dependency-free for now. It uses plain JavaScript and VS Code contribution points so the first iteration stays small.

## Package Install

Build the VSIX and Vulcan package metadata from the SDK repository root:

```bash
tools/prepare_vscode_extension_package.sh --output-dir dist/vscode-extension
```

After the workflow publishes the package, install it in an SDK Code terminal:

```bash
sima-cli neat install sdk/vscode-extension@vscode-integration-pr:latest
```

Use the target branch in place of `vscode-integration-pr` when installing from another branch.
