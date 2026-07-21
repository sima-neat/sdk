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
./build.sh sdk 2.1.2
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

Neat Core and Neat Apps source trees embedded in the image are selected by the `ref` values
in `deps/manifest.json`. Before Buildx starts, `build.sh` resolves release tags and
`branch:latest` references to full Git commit SHAs. Those resolved commits become Docker
build arguments, so moving a branch invalidates the source-installation layer without
duplicating package and source selections in the manifest.

The `sima-cli` dependency is also selected by `deps/manifest.json`. Release refs such as
`v2.1.15` install that exact PyPI version. A branch ref may use `main:latest`; `build.sh`
resolves `latest.tag` before invoking Buildx and passes the resulting artifact commit into
the Docker build, so a new branch artifact invalidates the cached installation layer.

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

Packages installed through `sysroot install` are tracked in lightweight manifests, so they can be listed or removed later:

```bash
sysroot list
sudo sysroot remove libzix-dev
```

## NEAT Insight Version

To make an Insight upgrade permanent in the image, rebuild the SDK image with the desired Insight channel and version:

```bash
NEAT_INSIGHT_BRANCH=main NEAT_INSIGHT_VERSION=latest ./build.sh sdk 2.1.2
```
