# Palette Image Builder container

A standalone companion to the Palette SDK. Customers start with
[Create a custom Modalix image](../docs/palette-image-builder.md) and install with
`sima-cli neat install sdk/pib`. This directory is not copied into the main SDK
image. sima-cli uses the generic metadata installer; PIB commands stay in the
container. Manual Docker installation is also supported.

`pib --version` reports the SDK repository build identity: the exact release tag
for a release build (for example `v3.0.0.2`), otherwise the branch and short Git
hash (for example `develop-abc1234`). Branch slashes become underscores, matching
the SDK release reference. This identity is embedded in the image and OCI labels;
it is separate from the platform release that PIB builds. Source checkouts or
manual builds without build metadata report `unknown-nogit`.

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
- `sbp/`: `pib sbp`, the opt-in package builder of the `pib-sbp` image (see below):
  its run-time set-up, apt/reprepro/nginx templates and the default sources (the
  kernel's repository and branch, the lttng-modules pin).
- `ci/`: the GHCR tag scheme (`image-config.py`) and CI's `pib sbp` start check
  (`check-sbp-start.py`).
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
docker build -t palette-image-builder:local \
  --build-arg PIB_VERSION="$(git branch --show-current | tr / _)-$(git rev-parse --short HEAD)" \
  --build-arg PIB_GIT_SHA="$(git rev-parse HEAD)" palette-image-builder
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

## Building the kernel: `pib sbp` (pib-sbp image)

`pib sbp package -p linux` builds the Modalix kernel with sbp, SiMa.ai's package
builder, and puts its `.deb`s in the workspace's `custom-debs/`; `pib sign-debs`
and `pib build` then make an image with that kernel. In palette workspaces it
also rebuilds, whenever the kernel changes, the out-of-tree kernel-module
packages palette images carry (`smifb`, `lttng-modules`); with `--no-modules` it
builds the kernel alone and removes module packages it built for an older kernel
from `custom-debs/`, so the image falls back to SiMa.ai's. A kernel or module is
rebuilt from scratch whenever its source, its sbp recipe (the checkout's config
directory) or, for the kernel, the FIT key changes. securepalette is refused:
its images check the kernel FIT against SiMa.ai's U-Boot key. `pib sbp --help`
lists the options.

The kernel source is yours to choose; sbp builds it with SiMa.ai's recipe
(`configs/packages/kernel/`: `simaai_modalix_defconfig`, the Debian packages and
the signed FIT):

- By default, SiMa.ai's public repository and branch, `master` of
  `https://github.com/SiMa-ai/simaai-linux.git` (`sbp/sources.json`).
- `--kernel-url` and `--kernel-ref` (or `PIB_SBP_KERNEL_URL` and
  `PIB_SBP_KERNEL_REF`, for every run) name another repository, such as your fork,
  and a branch or commit of it. The URL must be https, with no credentials: the
  container has none.
- `PIB_SBP_KERNEL_SRC` names a git repository on the host, a checkout or a bare
  one: a private fork, or commits not pushed anywhere. The launcher mounts only its
  git directory, read-only (never the working tree and its untracked files), so it
  must be a complete clone (not `--filter`, `--shared` or a worktree), and it refuses
  one with credentials in its git config, which the build would see. pib sbp builds
  the branch checked out there (or `PIB_SBP_KERNEL_REF`) at its latest commit,
  never uncommitted changes; the launcher counts those on the host and pib sbp warns
  when they sit on the commit it builds.

A branch is looked up on every run and built at its tip, whose commit pib sbp
prints; when the branch moves, the next run rebuilds the kernel. A commit must be
on a branch or tag of the repository (sbp clones those only), and is cloned with
a branch that holds it; the same commit asked for through another branch is not
rebuilt. The volume keeps a copy of a remote kernel repository: the first build
downloads all of it (about 2.5 GB for SiMa.ai's), later ones only what is new, and
sbp clones the kernel from that copy. Before a kernel build from scratch, the old
kernels leave sbp's local repo, so a kernel of another version cannot block the
next run. Keep the
release's kernel version (6.18.3), defconfig name and FIT packaging, or the image
leaves the kernel out (its pins name `linux-image-6.18.3-modalix`) or boots it
unsigned (pib sbp warns when the kernel package has no FIT). Each run that copies
a kernel also compares its SiMa.ai uapi headers with the release's: SiMa.ai's
prebuilt userspace (libcamera's ISP, simaai-mlart) is built against those. Today
`master` on GitHub is SiMa.ai's release 2.1.3: a 6.18.3 kernel without the FIT step
and without some of the uapi headers the 3.0 userspace uses, so both warnings
appear until SiMa.ai publishes its 3.0 kernel there.

The command runs in its own image, the Dockerfile's `pib-sbp` target, which adds
the cross toolchain and build tools. CI publishes it next to every PIB image as
`<tag>-sbp` (see CI and GHCR naming); the launcher appends `-sbp` to the tag of
`PIB_IMAGE`, an installed launcher uses the digest its installer bound, and
`PIB_SBP_IMAGE` names any other. For a local build, build both targets and set
`PIB_IMAGE` to the PIB one, as below. It runs unprivileged and builds code fetched from the
network as root inside its container, so the launcher shows it the workspace
read-only except `custom-debs/`, and of `keys/` only the kernel FIT key pair
(`keys/fit-signing.{key,crt}`, made once by `pib keys fit`). sbp's work tree,
local repo and ccache live in the Docker volume `pib-sbp-<uid>` (`PIB_SBP_VOLUME`).

sbp and its package configs (`pkgbuild/` and `configs/packages/`) are to come
with the image configs from swsoc-simaai-elxr-doc (`deps/artifacts.json`), whose
pinned commit does not carry them yet. Until then, `PIB_SBP_SRC` names a
checkout that does (swsoc-simaai-elxr-doc once they are published there, or
SiMa.ai's swsoc-elxr), of which only those two directories are mounted, read-only.

pib sbp takes the kernel's repository from `sbp/sources.json`, `--kernel-url` or
`PIB_SBP_KERNEL_SRC`, never from the URL in `PIB_SBP_SRC`'s own config.
`PIB_SBP_GIT_MIRRORS` serves SiMa.ai's private Bitbucket repositories, for a
kernel named with `--kernel-url https://bitbucket.org/sima-ai/<name>.git`: a
directory of bare mirrors (`<name>.git`) made on the host, mounted read-only, into
which every Bitbucket URL is rewritten, so no credential enters the container.
GitHub URLs are never rewritten. `pib sbp` checks a source before sbp clones
anything: a branch and its tip are read from the mirror, so refresh it first
(`git -C <mirror> remote update`); a commit must be in it.

```bash
docker build -t palette-image-builder:local palette-image-builder
docker build --target pib-sbp -t palette-image-builder:local-sbp palette-image-builder
export PIB_IMAGE=palette-image-builder:local          # pib sbp uses ...:local-sbp
export PIB_SBP_SRC=~/swsoc-simaai-elxr-doc            # a checkout with pkgbuild/ and configs/packages/
pib init --flavor palette my-image && cd my-image && pib keys init && pib keys fit
pib doctor                    # on amd64, once per host boot: arm64 tools for the module builds
pib sbp package -p linux      # SiMa.ai's kernel: master of github.com/SiMa-ai/simaai-linux
pib sign-debs && pib build --sign

# your kernel instead: a fork and branch, or a repository on the host
pib sbp package -p linux --kernel-url https://github.com/<you>/simaai-linux.git --kernel-ref my-branch
PIB_SBP_KERNEL_SRC=~/simaai-linux pib sbp package -p linux    # its checked-out branch
```

The kernel package is `linux-image-6.18.3-modalix` with the version
`6.18.3-<n>`, `n` counting the kernel builds in this volume; PIB's image pins
make it win over SiMa.ai's 6.18.3-2796. A kernel build takes about half an hour
on 3-4 jobs and 6-8 GB on the volume (`PIB_SBP_JOBS` sets the jobs; by default
fewer when memory is short; `PIB_SBP_CCACHE_SIZE`, default 5G, bounds ccache). CI builds
and publishes the `pib-sbp` image but does not build a kernel with it yet: that needs
sbp and its configs in the image (see above).

## CI and GHCR naming

The SDK Docker workflow calls `.github/workflows/palette-image-builder.yml` for
every source commit, in parallel with the SDK build. PIB builds natively on the
Vulcan Ubuntu 24.04 `amd64` and `arm64` runner pools used by the SDK. Each
architecture must pass the regression
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
`<SHA>-aarch64` tags.

Each architecture also builds the `pib-sbp` target, the image `pib sbp` runs in,
from the same build arguments; the Dockerfile applies the per-commit build identity
last in both images, so the toolchain layers stay cached across commits. CI runs
the regression suite in it and starts `pib sbp list` through the launcher, which
runs the container set-up (`sbp/setup.sh`) and the image check, but builds no
kernel: sbp does not ship in the image yet (`ci/check-sbp-start.py`). It is
published in the same package next to every tag above, as `<tag>-sbp`
(`latest-sbp`, `develop-sbp`, `v3.0.0.2-sbp`, `<SHA>-sbp`, `<SHA>-x86_64-sbp`,
...), the name the launcher derives from `PIB_IMAGE`; a branch whose name ends in
`-sbp` gets no canonical alias, which would be another branch's `-sbp` tag. Both
images are staged before either is promoted. The installer binds the multi-platform
`pib-sbp` digest into the launcher it installs, as `pib sbp`'s default image,
without downloading it: Docker pulls it, about 2.5 GB, on the first `pib sbp`,
outside sima-cli, so a package that is not public needs `docker login ghcr.io`
first. Release tags accept `vX.Y.Z` or `vX.Y.Z.N`; release publication
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
the upstream board-input commit and the `pib sbp` sources in `sbp/sources.json` (the kernel's branch, the lttng-modules pin) together. Update the pinned eLxr OCI index and elxr-config
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
