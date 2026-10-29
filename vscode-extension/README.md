# SiMa Neat VS Code Extension

Experimental VS Code extension scaffold for SiMa Neat SDK workspaces.

## Features

- Adds a SiMa Neat activity bar container.
- Opens Insight using the current URL reported by `neat --json`.
- Initializes the browser editor menu bar to always visible (`window.menuBarVisibility: visible`) when no explicit user/workspace value exists. Users can change it afterward; desktop VS Code preferences are untouched.
- Shows a Neat webview panel with SDK controls.
- Supports opt-in, host-controlled expiration reminders for Arthas; ordinary local environments remain silent.
- Adds Developer Portal Login/Logout controls that store tokens in the same `~/.sima-cli/.tokens.json` cache used by `sima-cli`.
- Contributes `SiMa Neat Light` and `SiMa Neat Dark` themes.

### Host-provided Insight launch URL

The Insight button checks `/home/docker/.insight-config/launch-url` each time it
is clicked. A host process can override the default URL by atomically replacing
the corresponding file in the container-specific host directory:

```text
<workspace>/.<container-name>/insight-config/launch-url
```

The file must contain one HTTP or HTTPS URL. If it is missing, empty, or
invalid, the extension falls back to `insight.webUiUrl` from `neat --json`.

## Development

Open this directory in VS Code or code-server and run the extension host.

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

## Host-controlled session countdown

See the [Arthas integrator guide](../docs/arthas-session-expiration.md) for the
control contract, lifecycle, transport, and acceptance checks. This feature is
opt-in: no control file means no footer, banner, or reminder notification.
Installing the extension does not create a deadline.

The extension polls `/run/sima-neat/session.json` once per second in the
extension host. Set `NEAT_SESSION_FILE` in the server environment before startup
to use another absolute path. Run the extension in the SDK/server environment.
No file means no countdown.

From the Docker host, set or replace the remaining time:

```bash
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --minutes 30
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --minutes 5
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --minutes 0
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --clear
```

The helper requires Docker access and Python 3 on both sides. It writes a
root-owned, readable file atomically. For an orchestrator integration, write
`{"expiresAt":"2026-10-20T18:00:00Z"}` with the actual absolute deadline, using
an atomic rename in the same directory. Use `{"expiresAt":null}` or remove the
file to clear it. A directory mounted read-only into the container is another
option; mount the directory rather than one file when using atomic replacement.
Host and container clocks must agree. This is an advisory UI, not access control
or environment shutdown enforcement.

The status bar shows a live countdown; clicking it opens a prominent banner at
the top of the Neat panel. Warnings appear at five minutes, one minute, and
expiration (once per stage per deadline, per editor window). Changing the deadline
resets warnings. Expiration stays visible until the host clears or extends it.
Reloading the editor reads the same absolute deadline, without resetting time.
Malformed/unreadable updates retain the last valid deadline and log to **Neat
Session Time**. VS Code has no public extension API for a full-width workbench
banner; this uses the supported status bar, notifications, and Neat webview.

After installing an updated VSIX, reload existing editor windows. To run tests:

```bash
node --test vscode-extension/test/*.test.js
```

### Exact expiration and host-selected presentation

The host can independently select the deadline and display mode:

```json
{"expiresAt":"2026-10-21T18:00:00-07:00","display":"quiet"}
```

| `display` | Behavior |
| --- | --- |
| `quiet` | Plain expiration date/time in UTC, without highlight or notifications. Past deadlines say “Expired” but remain quiet. |
| `warning` | Highlighted countdown and one warning notification when selected. |
| `urgent` | Red countdown and one error notification when selected. |
| `auto` (default) | Countdown with automatic five-minute, one-minute, and expiration warnings. |

Explicit modes never escalate automatically. The host owns the reminder policy.
Changing modes resets notification deduplication; rewriting identical state does
not repeat notifications. Existing notifications already delivered by VS Code
may remain in its notification center. Reloading an editor resets deduplication.

```bash
# Exact timestamp must include Z or a timezone offset.
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest \
  --expires-at '2026-10-21T18:00:00-07:00' --display quiet

# Change presentation while preserving the same expiration.
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --display warning
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --display urgent
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --display quiet
```

The JSON file is the control interface; no listening HTTP service is added.
Direct writers submit the complete state. The helper supports display-only
updates by reading the current deadline; use a single host controller to avoid
concurrent read/modify/write conflicts. Setting a new deadline without
`--display` selects the default `auto` mode.

### Blinking footer highlight

Add `"blink":true` to the JSON state to blink the status-bar warning/error
background (one second on, one second off). Text remains visible throughout;
the Neat panel does not blink. Blinking defaults to off and has no visual effect
in `quiet` mode or while `auto` has normal severity. Toggling blink alone does
not repeat notifications. Presentation-only updates preserve the blink setting;
a new deadline resets it to off unless `--blink` is specified.

```bash
# Start a new demo, including its deadline.
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --minutes 30 --display warning --blink
# For an already-configured deadline, --display warning --blink is sufficient.
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --no-blink
```

The blinking footer defaults to red. Set `"blinkColor":"amber"` (or `"red"`)
in the control file, or use `--blink-color amber`. This changes only the blink
highlight, not notification severity or the panel. It does not enable blinking
by itself. Color-only updates preserve the deadline and do not repeat alerts.
With blinking disabled, the steady highlight follows the display severity.
VS Code supports only error and warning backgrounds for individual status items;
red/amber select those theme colors, so the exact shade depends on the theme.
Arbitrary CSS or hex colors are unsupported.

```bash
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest \
  --minutes 30 --display warning --blink --blink-color red
# Change an existing session's blinking color without changing its deadline:
python3 tools/neat-session-time.py ghcr.io-sima-neat-sdk-develop-latest --blink-color amber
```

## Browse model builds

Model Registry is available only on SDK 3.0 or newer, including 3.0 pre-release
and daily builds. The Models button and command are hidden on older SDKs or
when `/etc/sdk-release` cannot identify a supported platform version.

Choose **Models** in the Neat panel or run **SiMa Neat: Browse Models (develop)**
from the Command Palette. Search existing production registry builds by model name,
variant, description, task, or license. After selecting a model, choose an action (downloads and source copies then ask for a destination workspace):

- **Show Model Card** opens the production Model Registry inside VSCode, with the
  selected model, variant, and `develop` branch in the URL. No files are downloaded.
- **Download prebuilt artifact** downloads the existing build for the selected variant.
- **Copy model source folder** copies `models/<model>` from the current `develop`
  branch of `sima-neat/models`, including its definition, README, and scripts.
  This source revision can differ from the prebuilt artifact's revision. Source
  lands in `models/<model>-source-<unique suffix>/contents/models/<model>`;
  `registry-source.json` records the repository and exact commit. Requires Git
  and GitHub read access for that repository. The extension uses VSCode's GitHub
  sign-in and asks permission to use your account on first use. Signing into
  GitHub only in a browser or on the host does not sign into the SDK's VSCode.
  The session is passed only to Git processes, never saved in model files or Git
  configuration. If access is denied, verify repository access and organization
  SSO authorization for that account. No Git metadata, dependencies outside the model folder,
  or build outputs are copied. Scripts are not executed.

Downloads use the SDK's `sima-cli models` commands and checksum verification.
The extension explicitly selects `https://models-registry.neat.sima.ai` for
listing and downloads; model cards open `https://developer.sima.ai/models/`.
The current existing build for that model/variant on `develop` is downloaded
into a new `models/<model>-<variant>-<unique suffix>` folder. No existing model
folder is overwritten. ZIP and tar packages are unpacked into `contents/` for review;
directory packages and individual model artifacts are kept as downloaded.
`registry-download.json` records the CLI's downloaded build and artifact details.
The folder is revealed in Explorer when complete. Cancel aborts the operation
and removes its incomplete folder. Model contents are never executed.

Requires an SDK with `sima-cli models list/download --json`, Python 3.9+,
and network access to the production registry and artifact download endpoints.
This initial integration uses `develop` only; it does not compile or deploy models.

### SDK landing page

Each browser-editor launch with no restored tabs or explicit
`workbench.startupEditor` preference opens the local Palette Neat landing page.
The stock Welcome page is disabled by default. Existing startup preferences and
open editors are preserved. A stock Welcome tab alone does not suppress the
landing page if it appears before extension activation. Use **SiMa Neat: Getting
Started** to reopen the page. Earlier one-time onboarding markers no longer
suppress the page in an otherwise empty editor.
The landing tab and selected task restore across browser reloads.

The page reads SDK version metadata from `/etc/sdk-release`. CPU availability
accounts for affinity, cpusets, and cgroup quotas; RAM shows available headroom
and the visible container limit. **Refresh** reads a new snapshot.

The configured DevKit comes from the same DevKit Sync settings used by the
Neat panel. A bounded SSH read retrieves `/proc/device-tree/model` and
`SIMA_BUILD_VERSION` from `/etc/build` or `/etc/buildinfo`. Unconfigured,
unreachable, and invalid configurations are distinct states; missing metadata
is shown as unknown. SSH tries keys first, then the standard DevKit password
through `sshpass` when available. New host keys are accepted; changed host keys
are rejected. No firmware or device settings are modified.

Insight version comes from `neat --json --offline`, with an installed Python
package metadata fallback for platform-only SDK images. Both the landing page
and Neat panel share the launch resolver: `/home/docker/.insight-config/launch-url`
first, then `neat`'s `insight.webUiUrl`, then the published mainUI port and
`CONTAINER_HOST_IP` when Core is absent. Missing URLs disable the launch action.

Quick-access actions open Insight, the Apps repository, the existing Neat model
browser (SDK 3.0+), the Getting Started documentation, or the Neat sidebar. Remote
pages and the model catalog require network access; the landing UI itself is
bundled locally and uses a restrictive webview Content Security Policy.

### Coding agents

The landing page's **Agents** tab installs **OpenAI Codex** (`openai.chatgpt`)
and **Claude Code** (`anthropic.claude-code`) through the editor's configured
extension gallery. The editor selects a compatible release and presents any
publisher-trust prompts; installations are not synced to other editors.

Each agent reports its own installation state immediately. Gallery downloads
can take several minutes; publisher prompts appear in the editor. **Manage in
Extensions** remains available during installation. Once available, **Open Codex** or
**Open Claude Code** opens that extension for account setup. If an installation
requires an editor restart, the page offers **Reload editor**. Failed or cancelled
installations can be retried. **Manage in Extensions** opens the selected
extension for enablement or troubleshooting. Installing an extension does not
sign in, purchase a plan, or send a coding task to the provider.

Only the two built-in agent identifiers and their predefined actions are
accepted from the webview. Extension changes made elsewhere in the editor
update the page while it is open. Network access to the configured gallery is
required; provider sign-in and service access remain provider-managed.
