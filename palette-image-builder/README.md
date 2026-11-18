# Palette Image Builder container

A standalone companion to the Neat SDK. Customers start with
[Create a custom Modalix image](../docs/palette-image-builder.md) and install with
`sima-cli neat install sdk/pib`. This directory is not copied into the main SDK
image. sima-cli uses the generic metadata installer; PIB commands stay in the
container. Manual Docker installation is also supported.

## Maintainer layout

- `Dockerfile`, `entrypoint.sh`, `host/pib`: container and host launcher.
- `pib/`: container CLI and inherited regression suite.
- Board templates, APT key, nginx configuration and helpers are fetched from the
  exact upstream commit in `deps/artifacts.json` during the container build.
- `RELEASE`, `CODENAME`: platform release and package suite; independent of the CLI
  package version and the SDK repository's release/container tags.
- `deps/`: hash-locked Python requirements and commit-pinned artifact URLs/checksums.
- `ci/image-config.py`: SDK-style GHCR repository/tag selection.
- `examples/custom-image/`: sample image spec, application package, overlay and hook.
- `tests/`: port regressions and full custom-SWU qualification.

The source was imported from
[SiMa-ai/swsoc-simaai-elxr-doc](https://github.com/SiMa-ai/swsoc-simaai-elxr-doc)
at `3b3ee82d4a88fe6ad67834de83fe3db6ea9539e4`. `UPSTREAM` records provenance.
Test workspaces, credentials, private keys, wheels, and binary archives are not
committed. Standard Python dependencies are downloaded from PyPI with exact wheel
hashes. SiMa Pasha and elxr-config are downloaded from the original public source
repository at the commit above and checked against recorded SHA256 values. The
eLxr base is selected by its pinned multi-platform OCI index. Do not update these
dependencies from a floating branch.

## Build and test locally

On a native Linux Docker host (amd64 or arm64):

```bash
docker build -t palette-image-builder:local palette-image-builder
export PIB_IMAGE=palette-image-builder:local
palette-image-builder/host/pib doctor
```

On amd64, the image configures its packaged ARM64 emulator automatically when
started through the privileged PIB launcher. ARM64 needs no target emulation. Use native runners for container builds: QEMU
amd64 on Apple Silicon segfaulted during setuptools package configuration in the
initial PDF reproduction. That failure did not occur with the matching ARM64 base.

Run CLI regression tests and the full artifact-generation test:

```bash
docker run --rm --network none --entrypoint bash \
  -v "$PWD/palette-image-builder:/source" -w /source \
  "$PIB_IMAGE" -lc \
  'tests/run-unit-tests.sh'
palette-image-builder/tests/smoke.sh
```

The smoke test requires an unused output directory (`test-output/` by default;
`PIB_TEST_OUTPUT` overrides it). It copies the checked-in sample via `pib init --example custom-image`, checks
that the installed spec matches the source, generates a local CA, packages/signs
the sample application, and builds/signs/verifies the image; and reads the
signed SWU's rootfs to prove all customizations and the CA reached the payload.
It does not contact a board. Private test keys and SWU binaries are not uploaded
by CI; qualification logs, SBOM, checksums, and manifests are retained.

## CI and GHCR naming

The SDK Docker workflow calls `.github/workflows/palette-image-builder.yml` for
every source commit. PIB builds natively on
`ubuntu-24.04` and `ubuntu-24.04-arm`. Each architecture must pass the regression
suite and full custom minimal-SWU smoke test before its image is pushed. Pull
requests from forks run the same qualification without logging in or publishing;
same-repository PRs use their push-run results and skip duplicate builds. A merge job
combines the tested immutable digests and promotes them only after both jobs pass.

Publication follows the main SDK scheme:

| Git ref | Package | Promoted tags/aliases |
|---|---|---|
| `main` | `ghcr.io/sima-neat/palette-image-builder` | `latest`, canonical `:main` |
| `develop` | `ghcr.io/sima-neat/palette-image-builder-develop` | `latest`, canonical `:develop` |
| `release-3.0` | `ghcr.io/sima-neat/palette-image-builder-release-3.0` | `latest`, canonical `:release-3.0` |
| `feature/foo` | `ghcr.io/sima-neat/palette-image-builder-feature-foo` | `latest`, canonical `:feature-foo` |
| `v3.0.0.2` | `ghcr.io/sima-neat/palette-image-builder` | `v3.0.0.2`, `v3.0-latest` |

All non-PR builds also produce commit SHA, `staged-<SHA>`, `<SHA>-x86_64`, and
`<SHA>-aarch64` tags. Release tags accept `vX.Y.Z` or `vX.Y.Z.N`; release publication
does not advance the main branch's `latest`. Branch names use the SDK's lowercase
sanitization rules. The launcher extracted from an image embeds its build commit tag, rather than following `latest` on each invocation. Commit tags follow the SDK
convention and can be replaced by a rerun; use `PIB_IMAGE=repository@sha256:...`
when you require an immutable registry identity.

After GHCR promotion, the workflow publishes an installer and metadata through
the existing Vulcan publisher with `artifact_folder: pib`. This creates
`sdk/<ref>/<commit>/pib/metadata.json` without replacing the main SDK metadata or
changing its root `latest.tag` itself. The SDK workflow advances that shared pointer
only after PIB publication and install verification succeed, keeping the subfolder
available at the selected SDK commit. The package references the qualified multi-platform
index by digest, so Docker selects the native image. Host installer tests run on
Linux, macOS and Windows; post-publication jobs install the exact subfolder package
on native Linux x86 and ARM. The bare `sdk/pib` command becomes available when this
workflow publishes from main; feature branches use `sdk/pib@<branch>`. GHCR packages must be made customer-readable by repository
maintainers before advertising them publicly. The existing SDK package cleanup
workflow is scoped to SDK packages; automatic PIB retention/cleanup is not added
by this port.

## Updating platform inputs

Update `RELEASE`, `CODENAME`, the Pasha artifact URL/hash in `deps/artifacts.json`,
and the upstream board-input commit together. Update the pinned eLxr OCI index and elxr-config
artifact as needed. Keep standard Python versions and wheel hashes in
`deps/debsbom-requirements.txt`; record source commits in `UPSTREAM`. Update the `upstream` commit in the same
lock for board templates, the public APT key, nginx configuration and helper
scripts. The image
build downloads and verifies these inputs before installation. Do not commit the
downloaded binaries. Inspect dependency licenses/notices when changing versions.

APT packages are still resolved from signed live repositories during container
and rootfs builds. The pinning/checksums here identify sources; they do not make
APT snapshots or guarantee bit-for-bit reproducible images. Retain the tested
container digest and per-build manifests/SBOM for provenance.

Minimal-image smoke tests establish artifact generation and verification. Palette,
securepalette, physical flash/update/rollback, and fused-board secure boot require
separate qualification. The templates retain those advanced workflows without
claiming they passed this port's tests.
