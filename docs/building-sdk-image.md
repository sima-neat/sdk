# Build The SDK Image Locally

The CI-published SDK image is the recommended path for most users. Build locally when you need to test Dockerfile changes, add sysroot packages, or create a private development image.

## Prerequisites

- Docker Engine installed on the host build machine.
- Access to any private package sources required by the build.
- Optional: `qemu-user-static` if your workflow needs to execute non-native target binaries during cross-architecture builds.

```bash
sudo apt install qemu-user-static
```

The normal SDK image build does not require `qemu-user-static` when the container is built for the host's native architecture and only carries an `arm64` sysroot for cross-compilation.

## Build

Build the default local image:

```bash
./build.sh
```

By default, this builds `sdk:latest`.

Build with a custom image name and tag:

```bash
./build.sh sdk 2.1.3
```

By default, `build.sh` loads the completed native-architecture image into the local Docker
daemon. It can instead push directly from Buildx, avoiding a second local image load and
registry upload:

```bash
BUILDX_OUTPUT=push ./build.sh ghcr.io/sima-neat/sdk test
```

The helper also supports a registry-backed BuildKit cache:

```bash
BUILDX_OUTPUT=push \
BUILDX_CACHE_FROM=ghcr.io/sima-neat/sdk-buildcache:develop-x86_64 \
BUILDX_CACHE_TO=ghcr.io/sima-neat/sdk-buildcache:my-branch-x86_64 \
./build.sh ghcr.io/sima-neat/sdk-my-branch test-x86_64
```

`BUILDX_CACHE_FROM` and `BUILDX_CACHE_TO` are cache references, not runnable SDK image
tags. Do not pass credentials, tokens, or other secrets through Docker build arguments or
write them into cached layers.

The build helper supports both `aarch64` and `x86_64` hosts and automatically selects the matching Docker platform for the current machine.

Example output:

```text
Building sdk:latest
Host architecture: arm64
Docker platform: linux/arm64
```

## CI Build Cache

The Docker build workflow publishes each native-architecture image directly from Buildx.
Branch builds import both their independent GHCR cache tag and the `develop` fallback,
then update only their own tag in the `sdk-buildcache` package. The architecture suffix
prevents x86_64 and aarch64 writers from colliding.
Pull requests import the target branch cache but do not update it, so untrusted or
speculative changes cannot poison a shared cache. Release tags reuse the matching
`release-X.Y` cache without modifying it.

The cleanup workflow removes cache versions belonging only to deleted branches and prunes
untagged cache versions after seven days. The package is an implementation detail of CI;
SDK consumers should continue pulling images from the normal `sdk` or branch-specific SDK
packages.

The ARM64 sysroot's downloaded Debian packages use a separate BuildKit cache mount. Local
BuildKit builders retain this mount automatically. In GitHub Actions, the workflow restores
it with `actions/cache` and injects/extracts it with the BuildKit cache-dance action because
registry-backed BuildKit layer caches do not export cache-mount contents. Both native image
architectures share the cache: they build the same ARM64 target sysroot.

The cache key includes the resolved immutable platform version, a hash of the sysroot
download inputs, and a unique workflow-run suffix. Each run restores the newest compatible
package cohort as a seed, downloads only changed packages, and saves its final state under
a new immutable key. The rolling key is required because GitHub cache entries cannot be
overwritten: without it, a repaired package or dependency update would be lost after the
build. Before reuse, every package is checked against cached source URI metadata and its
Debian package name, architecture, exact version, and repository SHA-256; invalid entries
are replaced through a temporary file and atomic rename. The cache mount is outside the
image filesystem and is never copied into the published SDK image.
Each build log reports downloaded and cached package counts and byte totals so cache savings
can be monitored directly.

Neat Core and Neat Apps source trees embedded in the image are selected by the `ref` values
in `deps/manifest.json`. Before Buildx starts, `build.sh` resolves release tags and
`branch:latest` references to full Git commit SHAs. Those resolved commits become Docker
build arguments, so moving a branch invalidates the source-installation layer without
duplicating package and source selections in the manifest.

Core is optional while a new SDK/Core release pair is being bootstrapped. If the requested
Core Git ref or published artifact does not exist yet, or its artifact metadata is
incompatible with the selected platform, the SDK build continues without bundled Core
binaries or source trees. Other installation failures remain fatal. Every build rechecks
Core availability even when Buildx imports a registry cache, so rebuilding the same SDK
commit after the Core artifact is published includes it automatically.

The build log prints a `Neat Core bundle result` summary. `/etc/sdk-release` records
`Neat Core`, `Neat Core Requested`, and `Neat Core Reason`; an image without Core uses the
`platform-cross` profile so smoke tests and DevKit synchronization do not assume those
resources exist.

The `sima-cli` dependency is also selected by `deps/manifest.json`. Release refs such as
`v2.1.15` install that exact PyPI version. A branch ref may use `main:latest`; `build.sh`
resolves `latest.tag` before invoking Buildx and passes the resulting artifact commit into
the Docker build, so a new branch artifact invalidates the cached installation layer.

## Build Against Pre-release Platform Packages

CI reads the repository variable `PRE_RELEASE_BASE`. A value such as `2.1.3`
selects the highest Debian version matching `2.1.3~pre*`; a value such as
`2.1.3~pre4460` pins that exact build. The workflow resolves the value once and
passes the same immutable version to both architecture builds.

For a manual workflow run, the optional **Platform selector** input overrides
the repository variable. Leave it empty to use `PRE_RELEASE_BASE`, enter
`X.Y.Z` to select the latest matching pre-release, or enter `X.Y.Z~preN` to pin
that exact platform build.

Floating selectors follow the mirror's `Release` metadata to its current
Acquire-By-Hash package index. Exact `X.Y.Z~preN` values bypass latest-version
selection but are still checked against that current index before the build.

Pre-release images use the `platform-cross` profile. They contain the cross
compiler and exact target sysroot but do not bundle Neat Core binaries or source
checkouts. `/etc/sdk-release` records the requested selector, resolved platform
version, repository, profile, and `Neat Core = not bundled`.

The pre-release mirror is configured as an overlay on the official release
repository. Exact platform-version pins select the requested pre-release
packages, while SDK-pinned dependencies that are not duplicated in the
pre-release mirror remain available from the release repository.

Floating selectors are rejected on `main`, `release-*` branches, and tags.
Those refs use the stable channel when `PRE_RELEASE_BASE` is unset and accept
pre-release packages only when an exact `X.Y.Z~preN` version is explicitly
pinned.

## Add Sysroot Packages

Inside a running SDK container, install additional ARM64 Debian packages into the sysroot with `sysroot`:

```bash
sudo sysroot install libzix-dev vxi-dev
```

The command installs into `/opt/toolchain/aarch64/modalix` by default and appends `:arm64` to unqualified package names. You can also pass explicit package qualifiers:

```bash
sudo sysroot install libopencv-dnn406:arm64 libfoo-dev=1.2.3
```

For OpenCV CMake component names, `sysroot` can resolve names such as `opencv_dnn` to the matching Debian package when apt metadata contains a single match:

```bash
sudo sysroot install opencv_dnn
```

Packages installed through `sysroot install` are tracked in lightweight
manifests so they can be removed later. `sysroot list` reports the complete
image or overlay inventory:

```bash
sysroot list
sudo sysroot remove libzix-dev
```

### Test a Pre-release Platform Sysroot Overlay

To test a newer pre-release platform revision without rebuilding the SDK
image, use `sysroot update` inside the SDK container. With no revision, the
command queries the public pre-release mirror and offers only revisions that
match the immutable image's `Platform Base` from `/etc/sdk-release`:

```bash
sudo sysroot update
```

Providing an exact revision is noninteractive and is suitable for automation:

```bash
sudo sysroot update 2.1.3~pre4617
```

Following the newest eligible revision requires explicit confirmation in
noninteractive environments. A dry run downloads and validates the dependency
cohort without extracting it into the sysroot:

```bash
sudo sysroot update --latest --yes
sudo sysroot update 2.1.3~pre4617 --dry-run
```

This command is deliberately restricted to pre-release development and
testing. It refuses stable versions and revisions outside the SDK's Platform
Base. For example, an SDK with `Platform Base = 2.1.3` cannot update its
sysroot to `2.2.0~preN`.

An update creates a visible **sysroot overlay** rather than changing the
immutable SDK image identity. Inspect both states with:

```bash
sysroot status
```

List the complete package inventory for either the image-default sysroot or
the active overlay with:

```bash
sysroot list
```

The table includes package name, architecture, exact version, and summarized
payload locations relative to the displayed sysroot. A package may show
multiple locations because Debian packages commonly contain both headers and
libraries. Manual `sysroot install` and `sysroot remove` operations update the
same inventory.

New interactive shells include the active overlay revision in the SDK prompt.
The overlay descriptor and exact package inventory are stored under
`/opt/toolchain/aarch64/modalix/var/lib/sima-sdk/`. Recreate the SDK container
to discard the overlay and restore the image-default sysroot. Because this is
an in-place overlay, recreating the container is also the way to guarantee that
files removed between platform revisions are absent from the sysroot.

Package downloads use eight workers by default and validated downloads are
cached per platform revision under `/tmp`. Override the concurrency when
needed, for example `SIMAAI_DOWNLOAD_WORKERS=16 sudo -E sysroot update ...`.
Retries of the same revision reuse valid cached packages. Interactive terminals
show animated download and extraction progress; CI logs receive periodic
plain-text progress updates.

The pre-release repository currently uses HTTPS transport with APT
`trusted=yes`; this is not equivalent to signed APT repository metadata. The
command prints this trust mode before every update.

## NEAT Insight Version

To make an Insight upgrade permanent in the image, rebuild the SDK image with the desired Insight channel and version:

```bash
NEAT_INSIGHT_BRANCH=main NEAT_INSIGHT_VERSION=latest ./build.sh sdk 2.1.3
```

## Platform 3.0 preparation branch

Pushes to `3.0.0-prep` default to the floating `3.0.0` platform selector.
The workflow resolves it once to an exact mirrored Palette `~git` version and
passes the same version to both host-architecture builds. A manual Platform
selector overrides this default and can pin a full `3.0.0~gitTIMESTAMP.COMMIT-BUILD`.

Daily builds resolve development packages together with the platform sysroot,
using Debian 13 package names and Python 3.13. The later overlay step only
repairs linker paths; it does not install the legacy Bookworm packages or kernel
header pin.

The `daily` channel uses `https://debian.neat.sima.ai/daily`, suite `agate`,
plus Debian 13 `trixie` target dependencies. It does not add the legacy
Aria/Bookworm platform fallback. Agate components have independent versions;
resolution honors dependency constraints, prefers the newest mirrored component
version whose build number is no later than the selected Palette build, and
uses Debian 13 for general dependencies. Actual package versions and hashes are
validated and recorded in the sysroot inventory. Debian virtual-package
providers (including `t64` replacements) and merged-`/usr` aliases are handled
when assembling the target filesystem. A GStreamer C++ link check runs against
the extracted sysroot during image construction. This is not a complete archive
snapshot of Debian: general Debian dependencies follow current Trixie updates.

These images use `platform-cross`: no matching Core artifact or Core/Apps source
checkout is required or bundled. Daily builds keep the Ubuntu host and source
GCC 14 from Debian 13, matching the compiler generation in the upstream eLxr
SDK. Stable and legacy pre-release builds retain the Bookworm GCC 12 toolchain.
Test Core builds against the new sysroot before promoting these experimental images.

For a local build with a known mirrored version:

```bash
SDK_APT_CHANNEL=daily \
BASE_SDK_VERSION=3.0.0~git202609090513.9e68a68-1218 \
REQUESTED_PRE_RELEASE_BASE=3.0.0 \
./build.sh sdk-3.0.0-prep local
```

`/etc/sdk-release` records the daily repository, exact platform version, base
`3.0.0`, and `Neat Core = not bundled`. In-container `sysroot update` still
supports the legacy `~preN` overlay flow; rebuild the experimental image to
change its daily platform revision.
