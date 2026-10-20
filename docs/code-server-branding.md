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
password guidance. For local SDK containers created by sima-cli, run
`sima-cli sdk neat printenv CODE_SERVER_PASSWORD` on the Docker host. This prints
the configured container-environment credential in the host terminal. If the
launcher generated the password instead, use the latest `Password:` entry in its
startup output. For supervised containers:

```bash
docker exec <sdk-container> tail -n 40 /var/log/supervisor/code-server.err.log
```

For a direct launch, check the launching terminal. The login page explains both
paths and never embeds a credential. Hosted users are directed to their
provider. Reapplying branding refreshes the password guidance and header icon,
including when the supplied icon changes.

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
