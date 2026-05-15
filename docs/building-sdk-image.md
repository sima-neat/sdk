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
./build.sh sdk 2.0.0
```

The build helper supports both `aarch64` and `x86_64` hosts and automatically selects the matching Docker platform for the current machine.

Example output:

```text
Building sdk:latest
Host architecture: arm64
Docker platform: linux/arm64
```

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
NEAT_INSIGHT_BRANCH=main NEAT_INSIGHT_VERSION=latest ./build.sh sdk 2.0.0
```
