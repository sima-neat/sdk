# Neat favicon for code-server

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
