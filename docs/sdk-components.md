# SDK component compatibility and qualification

`components.json` is the reviewed compatibility catalog for Codex, Claude, and the
image-bundled Codex CLI. `deps/manifest.json` separately selects the code-server
release and its two archive checksums.

## Selection and installation

The schema version is `1`. `revision` increases when compatibility data changes.
`build_sdk_version` selects the Codex CLI for an SDK image build. Each exact SDK
key in `sdks` declares explicit SDK release aliases, supported host architectures,
code-server/VS Code engine **pairs**, qualification status, and exact
component IDs, versions, URLs and SHA-256 values. SDK identity comes from
`SDK Release` in `/etc/sdk-release`, not the platform/sysroot version. Tagged SDK
image builds additionally require the selected build cohort to be qualified and
to explicitly list that tag as a supported SDK release. Unknown
releases and development branches do not inherit a stable release mapping.

The Palette SDK environment card displays the selected cohort, target versions,
and installed CLI version; agent cards show installed and target versions.
Install verifies the downloaded VSIX checksum and package identity/version.
A successful editor command must expose the expected installed version or its
verified profile entry before the UI offers Reload. A different installed version
can be explicitly repaired/downgraded with Install. Open is blocked for mismatches.

If an already installed extension has frozen the editor, close the browser and
repair it from the SDK shell with `code-server --install-extension openai.chatgpt
--extensions-dir "$HOME/.local/share/code-server/extensions"`. The same resolver
and qualification checks apply; this path does not require a responsive workbench.

The code-server CLI wrapper enforces the same policy for bare agent IDs used by
`sima-cli sdk setup`, including explicitly requested versions. Other extension
IDs and ordinary server commands retain the upstream CLI contract. Installing
local exact VSIX packages uses upstream pinned-version behavior to avoid silent
gallery auto-updates. This controls SDK-managed installation, not deliberate
administrator replacement of files or packages.

The last validated online catalog and artifacts are cached in the extension's
global storage. A network outage can use that catalog or the image-bundled copy.
Malformed online data and known revocations fail closed instead of using stale
qualified data. Downloaded cache files are hashed again before use. Downloads
have time/size limits and redirects remain restricted to known artifact hosts.
The Codex CLI installer consumes the same catalog, verifies the pinned npm
archive, and checks `codex --version` after installing it. Its native optional
packages are versioned by the pinned upstream npm package.

## Candidate qualification

New cohorts start as `candidate`. The initial 3.0.0 mapping is a **test candidate**,
not a customer qualification: Codex 26.908.40401, Claude 2.1.316, Codex CLI 0.153.4.
The reported Codex 26.1021.22027 freeze is excluded from that cohort.

To test a candidate in a disposable SDK container, set these environment values
before starting the extension host:

```text
SIMA_SDK_COMPONENTS_ALLOW_CANDIDATE=1
SIMA_SDK_COMPONENT_TEST_VERSION=3.0.0
```

The second setting is required for development images. It is an exact test SDK
key, not a general fallback. Palette labels the result **Candidate test**.
Ordinary customer sessions accept only `qualified` cohorts.

For each supported architecture and engine pair:

1. Record the SDK image digest, code-server and Code versions, exact agent and
   CLI versions, Chrome version, and installation checksums.
2. Install each agent and both together through Palette and the SDK CLI path.
   Verify the installed versions and pinned metadata, repair/downgrade, reload,
   service restart, and preserved update policy.
3. Check editor responsiveness, file edit/save, terminal creation, reconnect,
   agent startup, and the known startup-freeze regression. Retain redacted browser
   and extension-host diagnostics on failure.
4. Complete account sign-in and basic authenticated agent use manually where
   automation cannot do it. Do not record credentials or chat content in evidence.
5. Record results for every declared architecture/engine pair and the approval
   in the PR and qualification documentation. Change status to `qualified` only
   when the matrix has passed. Review the recorded results before promotion; CI
   validates compatibility data and the publication gate. The runtime catalog
   carries status, not evidence links, notes, or approval records.

Run `node --test vscode-extension/test/*.test.js`,
`python3 tests/sdk/test-components-publication.py`, and
`node scripts/components-catalog.js validate` for fast regression checks.
The opt-in browser qualification workflow produces a report and diagnostics;
its unauthenticated smoke alone cannot promote a candidate.

## Publication and rollback

The public URL is `https://artifacts.neat.sima.ai/sdk/components.json`.
Normal publication runs only after a successful `Build SDK Docker Image` push
build on `main`. The publisher additionally verifies that the exact checked-out
SHA is the current main head and is a merged PR commit. There is no manual
workflow trigger or committed command-line bypass. PRs, other branches, tags,
failed builds and unrelated repositories cannot publish. Main is checked again
immediately before upload; concurrency serialization, revision/ancestry checks,
and conditional S3 writes prevent an older/in-flight run overwriting a newer one.

Publication uses the Vulcan production artifact bucket and its customer-managed
KMS key, sets JSON/no-cache response metadata, records source SHA and manifest
hash, and invalidates the exact CloudFront path. Existing S3 versions provide
recovery evidence. To roll back or revoke a cohort, increase the manifest revision
and merge a reviewed change into main; do not independently edit production data.

The initial manual **candidate-only** upload was explicitly authorized for this
task before merge. It is marked `publication.manual_test: true`, uses the same
checksum/schema validation, and does not establish a general bypass of the
normal merge gate. The one-time operator script is outside the repository.
