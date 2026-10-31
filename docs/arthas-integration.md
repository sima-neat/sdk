# Arthas SDK integration guide

This guide describes the SDK interfaces Arthas can use when provisioning a
hosted Neat development environment. Arthas owns user authentication,
environment routing, lease policy, and shutdown. The SDK provides the browser
editor and advisory expiration UI; it does not implement the Arthas controller.

## Image and startup

Use a tested SDK image containing the required features. The development channel
is `ghcr.io/sima-neat/sdk:develop`; pin an approved image digest for reproducible
rollouts. Check the image's `org.opencontainers.image.revision` label rather than
assuming an existing container has updated when a mutable tag is pulled.
Recreate the container to use a new image.

Set integration environment variables in the container specification **before
startup**, so the supervised code-server process and extension host inherit
them. Exporting variables in an editor terminal afterward does not reconfigure
those processes. The SDK normally starts code-server automatically; setting
`CODE_SERVER_SUPERVISED=0` disables that startup.

## Authentication through the Arthas gateway

For a hosted environment authenticated by Arthas, disable code-server's separate
password prompt with this container environment setting:

```yaml
# Environment fragment for a Docker Compose service.
environment:
  CODE_SERVER_WITHOUT_PASSWORD: "1"
```

For a Docker invocation, add `-e CODE_SERVER_WITHOUT_PASSWORD=1` to the existing
container creation command. This is a container setting, not a `sima-cli sdk
setup` flag; a host-shell export alone does not guarantee it is forwarded.

The SDK launcher runs code-server with `--auth none` and unsets its `PASSWORD`
variable. The explicit setting takes precedence even when launch tooling also
injects `CODE_SERVER_PASSWORD` or the legacy `OPENVSCODE_SERVER_TOKEN`.
`OPENVSCODE_SERVER_WITHOUT_TOKEN=1` is a compatibility alias; new integrations
should use `CODE_SERVER_WITHOUT_PASSWORD`.

Arthas must authenticate and authorize every request, including WebSocket
upgrades. Route users only to their authorized environment. Keep both
code-server listeners inaccessible directly from the public network; the
Arthas gateway must be the only user access path.

The default HTTP listener is port `9999`, suitable for a trusted reverse proxy.
The optional HTTPS listener defaults to `10000` when SDK certificates are
configured. Forward WebSocket upgrades and preserve the external scheme and
host through the proxy. Validate editor terminals and reconnection through the
actual Arthas route before rollout.

To change authentication on an existing environment, update the container
specification and recreate it using Arthas's normal persistence/lifecycle flow.
A browser reload or an environment export in a running terminal is insufficient.

### Password-protected environments

Without the explicit opt-out, password authentication remains enabled. Set
`CODE_SERVER_PASSWORD` before startup when Arthas supplies a credential. If no
password is supplied, the launcher generates a temporary password and prints it
to its startup output. Leaving the password empty does **not** disable login.

For local SDKs created by sima-cli, setup prints the password. Users can retrieve
the configured value from a host terminal with:

```bash
sima-cli sdk neat printenv CODE_SERVER_PASSWORD
```

This command applies when the password was supplied in the container environment,
as in sima-cli setup. A password generated only inside the launcher is instead
available in its startup output. Hosted users should obtain credentials through
Arthas's authenticated access flow, not a public page or shared logs.

## Environment expiration and reminders

Arthas can publish the authoritative lease deadline through
`/run/sima-neat/session.json`. The Neat extension reads it and updates the footer,
Neat panel banner, and notifications. It does not enforce expiration or shut down
the environment.

- Start a lease with its absolute `expiresAt` timestamp and `display: "quiet"`.
- When Arthas decides to remind the user, switch to `warning` or `urgent` without
  changing the deadline. Optionally set `blink: true`; `blinkColor` supports
  `red` (default) or `amber`.
- On renewal, publish the new deadline and reset to quiet with blinking disabled.
- On expiration, Arthas enforces access and shutdown policy.
- Remove the file or publish `{"expiresAt": null}` to hide the UI. Clear stale
  state before assigning an environment to another session.

Write state atomically through container execution or a host-controlled directory
mount. Mount the directory rather than a single file so replacements remain
visible. Set `NEAT_SESSION_FILE` before startup to override the default path.
Local SDKs without a control file show no reminder UI.

See the [expiration integration contract](arthas-session-expiration.md) for the
complete schema, writer example, display behavior, and acceptance checks.

## Branding and editor defaults

The SDK image includes the Neat extension icon as the code-server favicon.
The web extension initializes the menu bar to visible when no explicit user or
workspace preference exists. Existing preferences are preserved.

The [code-server branding guide](code-server-branding.md) documents the build-time
branding helper and login-page customization. Passwordless Arthas environments
bypass the login page. Branding does not provide authentication and must never
embed a credential in publicly served HTML.

## Integration acceptance checks

- Through an authenticated Arthas route, the passwordless editor opens without a
  second login, and terminals reconnect over WebSockets.
- Unauthenticated users and users assigned another environment cannot access
  that environment through the gateway; neither editor port is publicly reachable.
- The explicit no-password setting still works if provisioning injects a password.
- Removing the opt-out restores password authentication after recreation.
- The deployed image revision matches the approved SDK build.
- Lease creation, reminder changes, renewal, clearing, and expiry work through
  the real controller; Arthas independently enforces expiry.

The SDK launcher regression checks are in
`tests/sdk/test-code-server-launcher.sh`; the reminder tests are in
`vscode-extension/test/session-time.test.js`. These checks do not replace testing
the Arthas gateway, provisioning, and lifecycle integration.
