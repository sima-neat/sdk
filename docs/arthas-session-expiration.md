# Arthas integration: environment expiration reminders

## Status and scope

Tracking issue: [sima-neat/sdk#265](https://github.com/sima-neat/sdk/issues/265).

The Neat VS Code extension supports a host-written session control file. Arthas
can use it to communicate an environment's expiration and decide when to remind
the user. Publish a tested SDK image or extension package containing this feature before
enabling it in Arthas.
Arthas integration and environment shutdown enforcement are not implemented by
this extension.

**Local development is silent by default.** Installing or activating the
extension does not create a deadline. When the control file is absent, there is
no footer item, Neat panel banner, or reminder notification. Do not ship a
sample deadline in the SDK image or create one in ordinary local startup.
This behavior depends on the control file, not on detecting whether the
extension is running locally or in Arthas.

`quiet` is an enabled display mode: it shows an expiration without emphasis.
To disable the display entirely, remove the file or write `{"expiresAt":null}`.
Previously delivered notifications may remain in VS Code's notification center.

## Ownership and transport

Arthas owns the authoritative expiration, extensions of the lease, reminder
policy, and enforcement of access or environment shutdown. The extension only
renders an advisory display; it does not terminate terminals, save files,
shut down containers, or call Arthas APIs.

The interface is a JSON file, not an HTTP endpoint:

- Default path inside the SDK: `/run/sima-neat/session.json`.
- Optional override: `NEAT_SESSION_FILE`, set to an absolute path in the VS Code
  server/extension-host environment before starting it. A shell export in a
  later terminal does not update an already-running extension host.
- Polling: nominally once per second while the extension host is running.
  Scheduling, I/O stalls, or a disconnected browser can delay the visible update.
- Run the extension in the SDK server environment where the file is readable.
- Use one controller per environment and keep host/container clocks synchronized.

Arthas can write through its existing container execution mechanism, or mount a
host-controlled directory read-only at `/run/sima-neat`. Mount the **directory**,
not just `session.json`, so atomic file replacement remains visible. Restrict
write access to the controller, while allowing the SDK user to read the file.
This is not a security boundary against a privileged environment user.

## Control contract

Write a complete JSON object, UTF-8, no larger than 4 KiB:

```json
{
  "expiresAt": "2026-10-21T18:00:00-07:00",
  "display": "quiet",
  "blink": false,
  "blinkColor": "red"
}
```

| Field | Values and default |
| --- | --- |
| `expiresAt` | Required ISO date/time including `Z` or a `±HH:MM` timezone offset (no offset seconds). `null` clears the display. Use valid calendar dates. |
| `display` | Optional: `quiet`, `warning`, `urgent`, or `auto`. Defaults to `auto`. |
| `blink` | Optional boolean, defaults to `false`. Blinks only a highlighted footer background. |
| `blinkColor` | Optional `red` (default) or `amber`. Selects the footer blink highlight independently of display severity. |

| Mode | Footer and panel | Notifications |
| --- | --- | --- |
| `quiet` | Plain exact expiration, displayed in UTC; no highlight. Past deadlines say “Expired”. | None, even after expiration. |
| `warning` | Warning-colored footer and prominent countdown banner. | One warning on entering this mode. |
| `urgent` | Error-colored footer and prominent countdown banner. | One error notification on entering this mode. |
| `auto` | Countdown; warning at five minutes, error styling at one minute and expiration. | Reminders at those thresholds. |

Explicit modes never escalate automatically. Arthas should explicitly send
`quiet` for a long-lived session instead of relying on the default `auto`.
`blink:true` alternates the footer highlight approximately one second on and
one second off. The text remains visible; the panel does not blink. Blinking defaults to red;
`blinkColor:amber` selects the warning theme background. VS Code only supports
error/warning backgrounds for individual footer items, so arbitrary hex colors
are not accepted and the theme controls the exact shades. With blinking off,
steady color follows display severity. It has no
visible effect in `quiet` mode or normal-severity `auto` mode.

Notifications are deduplicated per editor window and stage. Changing the
expiration or display mode resets deduplication; rewriting equivalent state or
changing only `blink` or `blinkColor` does not. Reloading the editor resets deduplication.
Multiple windows can each show a reminder.

## Suggested Arthas lifecycle

1. When provisioning a leased environment, write its authoritative deadline with
   `display:quiet` and `blink:false`.
2. When Arthas decides a reminder is appropriate, keep the same deadline and
   publish `display:warning`. Optionally enable blinking.
3. For an urgent reminder, publish `display:urgent` with the same deadline.
4. When a lease is extended, publish the new absolute deadline and explicitly
   reset presentation to `quiet` and blinking to `false`.
5. On expiration, enforce policy in Arthas. The UI clamps the countdown at zero
   and shows expiration; it is not an enforcement acknowledgement.
6. On removal of the time limit or reuse as an unrestricted environment, clear
   the state. Clear any persisted/mounted state before assigning a new session.

If the controller stops updating, the last valid deadline continues counting
down. There is no heartbeat TTL or controller connectivity indicator. Missing
files clear the display. Malformed or unreadable updates retain the last valid
in-memory state and log to the **Neat Session Time** output channel. A fresh
extension host with invalid input has no previous state to display. Reloads read
the absolute deadline again rather than starting a fresh duration.

## Atomic writer example

Run this Python code in the controller against the host-mounted directory, or
inside the SDK container through Arthas's existing execution mechanism. Adapt
the directory to the chosen transport. Submit the entire state each time.

```python
import json
import os
import tempfile
from pathlib import Path

folder = Path('/run/sima-neat')
state = {
    'expiresAt': '2026-10-21T18:00:00-07:00',  # actual lease deadline
    'display': 'quiet',
    'blink': False,
}
folder.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix='.session-', dir=folder)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(state, out)
        out.write('\n')
        os.fchmod(out.fileno(), 0o644)
    os.replace(temporary, folder / 'session.json')
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
```

For clearing, use `state = {'expiresAt': None}` with the same writer.

## Local Docker development helper

From the SDK repository root on the Docker host:

```bash
python3 tools/neat-session-time.py CONTAINER \
  --expires-at '2026-10-21T18:00:00-07:00' --display quiet
python3 tools/neat-session-time.py CONTAINER --display warning --blink
python3 tools/neat-session-time.py CONTAINER --display urgent
python3 tools/neat-session-time.py CONTAINER --blink-color amber
python3 tools/neat-session-time.py CONTAINER --no-blink
python3 tools/neat-session-time.py CONTAINER --clear
```

For a new blinking demo without an existing deadline, use
`python3 tools/neat-session-time.py CONTAINER --minutes 30 --display warning --blink`.
A display-only command after `--clear` cannot start a new session.

The helper needs Python 3 on both sides and Docker execution access. It writes
as root inside the container. Presentation-only updates preserve the existing
deadline and unspecified fields, and require a currently configured deadline.
A new deadline replaces state: omitted display becomes `auto` and omitted blink
becomes `false`. `--minutes N` is a local testing convenience, calculated from
the host clock; use `--expires-at` for the actual Arthas lease.

Do not run concurrent helper updates: its presentation-only read/modify/write
operation is not a compare-and-swap API. Prefer a single Arthas controller
publishing complete state from its authoritative lease record.

## Integrator acceptance checks

- Fresh local SDK without a file: no footer, banner, or reminder notification.
- Exact deadline in quiet mode: UTC expiration appears without highlighting.
- Host reminder with substantial time remaining: warning/urgent mode applies
  without changing the deadline or requiring an editor reload.
- Blink toggles the footer background while text remains visible; disabling it
  restores a steady highlight and does not produce another notification.
- Extending the lease and resetting to quiet removes emphasis.
- Reloading the editor preserves the absolute deadline.
- Expiration is displayed, but only Arthas enforces access/shutdown policy.
- Clearing or removing state hides the footer/banner; stale files are not reused.
- Malformed updates retain prior valid state and produce a diagnostic.

Run extension tests with `node --test vscode-extension/test/*.test.js`.
After installing an updated extension package, reload existing editor windows.
Before rollout, qualify live blinking and the complete lease lifecycle in the
Arthas environment, including disconnects and reconnects.
