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
./build.sh sdk 3.0.0
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

## Platform 3.0 package selection

`build.sh` defaults to platform `3.0.0`, the `daily` APT channel, and the
`debian:trixie` GCC 14 toolchain. It resolves the floating platform base to an
exact mirrored `3.0.0~gitTIMESTAMP.COMMIT-BUILD` revision before building.
Dockerfile-only builds perform the same resolution and record the exact version.
Local resolution requires `curl`, `gzip`, Python 3, and `dpkg`.

CI resolves the version once for both architectures. Use the workflow's platform
selector to pin a specific daily revision. Floating selectors are rejected on
`main`, `release-*`, and tags; use an exact revision for those refs.

## Add packages or change the platform revision

For the 3.0 SDK, rebuild the image to change the platform revision or add target
packages. For example:

```bash
SDK_PKG_LIST=libpgm-dev ./build.sh sdk 3.0.0
```

Use `BASE_SDK_VERSION=3.0.0~gitTIMESTAMP.COMMIT-BUILD` to select a particular
mirrored revision. `sysroot list` and `sysroot status` inspect the installed
inventory. The legacy in-place updater and package installer are unavailable
for daily images because they apply older repository and kernel-header pins.

## NEAT Insight Version

To make an Insight upgrade permanent in the image, rebuild the SDK image with the desired Insight channel and version:

```bash
NEAT_INSIGHT_BRANCH=main NEAT_INSIGHT_VERSION=latest ./build.sh sdk 3.0.0
```

## Platform 3.0 preparation branch

Pushes to `3.0.0-prep` default to the floating `3.0.0` platform selector.
The workflow resolves it once to an exact mirrored Palette `~git` version and
passes the same version to both host-architecture builds. A manual Platform
selector overrides this default and can pin a full `3.0.0~gitTIMESTAMP.COMMIT-BUILD`.

Daily builds resolve development packages together with the platform sysroot,
using Debian 13 package names and Python 3.13. The development package set
includes the matching SiMa platform development packages (memory, logging,
tracing, A65 apps, AppComplex, heap, MLA runtime, PCIe, pipeline, GStreamer,
and codec), plus LTTng-UST, JsonCpp, OpenCV, and ZeroMQ C++ headers for internals
builds. The later overlay step only
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
SDK. Trixie is the default toolchain source throughout this branch.
Test Core builds against the new sysroot before promoting these experimental images.

For a local build with a known mirrored version:

```bash
SDK_APT_CHANNEL=daily \
BASE_SDK_VERSION=3.0.0~git202609090513.9e68a68-1218 \
REQUESTED_PRE_RELEASE_BASE=3.0.0 \
./build.sh sdk-3.0.0-prep local
```

`/etc/sdk-release` records the daily repository, exact platform version, base
`3.0.0`, and `Neat Core = not bundled`. Update an existing daily SDK with an
exact mirrored version:

```bash
sudo sysroot update 3.0.0~git202609070138.4a147cf-1157
sysroot status
```

Daily updates require an exact version with the same platform base. `--dry-run`
resolves packages without modifying the active sysroot. Repeating the active
revision skips reinstalling only when the requested `SDK_PKG_LIST` is unchanged.
Changing that list creates a fresh generation at the same revision. Both amd64 and arm64 SDK hosts resolve arm64 target
packages.

Each update extracts a fresh generation, records package versions and SHA256
checksums, and checks compatibility with the SDK compiler before atomically
switching the active symlink. Obsolete package files are not carried forward.
Include additional development packages explicitly with `SDK_PKG_LIST` when
updating. `/etc/sdk-release` continues to describe the original image.

Build environments use permanent generation paths. Existing shells and configured
builds retain their generation; start a new shell and reconfigure a build directory
to use an update. Consumers that hardcode the active symlink must instead use
`SYSROOT` from `simaai-init-build-env` to obtain this guarantee.

`sudo sysroot rollback` reactivates the previous generation. Updates are serialized;
failed or interrupted extraction never replaces the active generation. Generations
are retained, including incomplete attempts, so running builds keep their files.
Disk space grows with updates; remove unused generations only after their builds
have finished. This layout is initialized during SDK image construction; older
images with a plain sysroot directory must first use the refreshed SDK image.
Daily `--latest` and standalone `sysroot install`/`remove` remain unsupported.
Existing `~preN` updates are unchanged.

The SDK build environment exports `-march=armv8.2-a+crypto -mtune=cortex-a65`:
the architecture flag controls permitted instructions, while the tuning flag
optimizes scheduling for Cortex-A65 without selecting additional ISA features.
The smoke suite compiles C and C++ with the exported flags and `-Werror` to catch
conflicting target options in initialized interactive environments.
