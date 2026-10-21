# SiMa Neat branding for code-server

The browser favicon is served by code-server, independently of the Neat VS Code
extension. Use the extension's existing 256 × 256 PNG as the shared source:
`vscode-extension/media/neat-logo.png`.

After installing code-server, run the branding helper as a user with write
access to its installation:

```bash
python3 tools/brand_code_server.py --server-dir /opt/code-server
```

The helper updates the editor workbench, login, and error-page favicon links.
It copies the PNG to a content-hashed filename to avoid reusing a cached stock
favicon. It validates all expected template links before writing and can be run
again. It does not alter extension icons, authentication-provider icons, or
installed-app/PWA icons.

For a container, copy the helper and PNG into it and supply an explicit source:

```bash
docker cp tools/brand_code_server.py CONTAINER:/tmp/brand_code_server.py
docker cp vscode-extension/media/neat-logo.png CONTAINER:/tmp/neat-favicon.png
docker cp vscode-extension/media/fonts CONTAINER:/tmp/fonts
docker cp vscode-extension/media/sima-logo.png CONTAINER:/tmp/sima-logo.png
docker exec --user 0 CONTAINER python3 /tmp/brand_code_server.py \
  --server-dir /opt/code-server --icon /tmp/neat-favicon.png
```

Reload the browser page after applying. No server restart is needed with the
currently tested code-server installation. If a browser retains the previous
icon, close and reopen the tab.

The SDK Dockerfile runs this helper after installing code-server and copying the
bundled extension icon, making branding reproducible in newly built images.
Reapply after an in-place code-server upgrade. An unsupported upstream template
layout causes a visible failure rather than silently retaining stock branding.

## Login page

The helper also brands the sign-in page with the Neat icon, SiMa.ai name, and
password guidance for local SDK setup. The page first directs users to the
password shown in the CLI output after SDK setup. If they cannot find it, it
shows one command to run in a terminal on their computer:

```bash
sima-cli sdk neat printenv CODE_SERVER_PASSWORD
```

Users paste the printed password into the sign-in field. The page never embeds
a credential. Reapplying branding refreshes the password guidance and header
icon, including when the supplied icon changes.

The upstream login form, error rendering, proxy-path fields, and authentication
remain intact. Styles are served locally under the existing content security
policy, and browser zoom remains enabled.

Image publication smoke tests fetch `/login` after SDK setup and check the
Palette Neat branding, password guidance, login form, and served CSS/logo assets.
The test fixture is not installed; the helper modifies the real code-server page
at image build time. Existing containers must be recreated from a published
image containing the change to receive it.

## Shared SiMa palette and typography

The login and editor styling follows Models PR #334 (commit
`fae1993d488ed0823ddb3d3674be92ea35f2f87d`): SiMa blue `#5998DD`, green
`#2A9C4F`, teal `#C0E8DB`, purple `#D1CEE6`, and orange `#D26728`, with
neutral light/dark surfaces. Text accents use darker variants where needed for
readability on light backgrounds.

Roboto styles the code-server UI; IBM Plex Mono styles code and terminals.
Latin fonts and their licenses are bundled under `vscode-extension/media/fonts`
and served locally, without external font requests. Other scripts use fallback
fonts. The helper adds a local stylesheet to the installed workbench because
VS Code color themes cannot set the workbench font.

The extension contributes SiMa Neat Light as its default theme, SiMa Neat Dark
as the preferred dark theme, and IBM Plex Mono as the editor/terminal font.
Explicit user or workspace settings override these defaults. The login page
follows the browser's light/dark preference independently of the editor theme.
Desktop VS Code users need the fonts installed locally; bundled web fonts are
loaded by the SDK's code-server pages.

The extension always shows “Palette Neat SDK” in the left status bar.
Clicking it opens the Neat panel. In code-server, the bundled workbench stylesheet
adds the SiMa logo beside the label; desktop VS Code shows the text alone.
This branding item is independent of the optional session-expiration indicator.

## Browser certificate help

The password page keeps **Certificate help** available and runs a small
same-origin service-worker probe. Success leaves the instructions collapsed.
Failure automatically opens help only when an enabled, matching CA download is
available. A six-second timeout leaves help collapsed, including if the probe
later fails. Failure and timeout display a neutral troubleshooting hint; neither
blocks sign-in nor claims to diagnose certificate trust. Manually opened help
stays open. The probe uses a unique scope beneath `/_neat/probe/`, bypasses the
script cache, has no fetch handler, and unregisters when registration completes.
It does not control the login page or VS Code webviews.

Updated sima-cli setup stages `sima-sdk-rootCA.pem` beside `neat-sdk.pem` after
verifying the mkcert CA signature. The login server exposes three fixed routes
before authentication (relative to the deployment base path):

- `/_neat/certificate-info`: availability only, without host filesystem paths.
- `/_neat/ca-certificate`: a download of the public CA certificate, with no-store
  caching and an attachment filename. Each request checks the issuing CA,
  signature, validity dates, and CA constraint against the configured SDK leaf.
  Missing, invalid, or mismatched files return 404. Private keys and directories
  are never served; the response is serialized from the parsed certificate.
- `/_neat/probe/service-worker.js`: a JavaScript probe with a narrow default scope.

For Arthas or another deployment with trusted HTTPS termination, set
`SIMA_SDK_CERT_HELP=off` in the code-server process environment to hide the local
CA section and disable the download. Browser trust cannot be inferred from the
certificate issuer name or an HTTP forwarded header. With older CLI versions or
a plain self-signed fallback, the page keeps generic help but offers no CA download.
Installing a downloaded CA remains an explicit user action on the browser computer.

The branding tool also installs the route module into code-server's compiled
route registration. It validates the expected upstream hook before writing any
files, and should be rerun after code-server upgrades.

Checks:

```sh
python3 -m unittest discover -s tests -p test_code_server_branding.py
node --test tests/test_browser_trust.cjs
```
