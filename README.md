<p align="center">
  <img src="images/simaai_logo.png" alt="SiMa.ai Logo" width="30%">
</p>

# SiMa.ai NEAT SDK

[![Build Docker Image](https://github.com/sima-neat/sdk/actions/workflows/docker-build.yml/badge.svg)](https://github.com/sima-neat/sdk/actions/workflows/docker-build.yml)
[![Smoke Test](https://github.com/sima-neat/sdk/actions/workflows/smoke-test.yml/badge.svg)](https://github.com/sima-neat/sdk/actions/workflows/smoke-test.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-supported-E95420?logo=ubuntu&logoColor=white)
![Windows 11](https://img.shields.io/badge/Windows%2011-supported-0078D4?logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-supported-000000?logo=apple&logoColor=white)
![eLxr Platform 2.0.0](https://img.shields.io/badge/eLxr%20Platform-2.0.0%20compatible-2E7D32)

This repository packages the SiMa.ai NEAT SDK as a Docker image for `x86_64` and `arm64` Linux hosts.

The current NEAT SDK image is compatible with the eLxr platform `2.0.0` release.

The main user workflow is:

1. Install `sima-cli`.
2. Install the SDK container image.
3. Start the SDK and optionally pair with a Modalix DevKit.
4. On x86 platforms, during setup optionally install Model SDK extension.
5. Use VS Code to attach to the running container for an IDE.

## Install The SDK

Install the latest published SDK image:

```bash
sima-cli install ghcr:sima-neat/sdk
```

Install a branch-specific image:

```bash
sima-cli install ghcr:sima-neat/sdk-feature-devkit-sync:latest
```

The published image contains the toolchain, sysroot, headers, libraries, NEAT runtime components, and helper scripts needed to build software for SiMa.ai platforms.

## Start The SDK

Run the SDK setup:

```bash
sima-cli sdk setup --devkit {devkit ip address}
```

Open the SDK shell:

```bash
sima-cli sdk neat
```

Check the installed SDK status from inside the SDK shell:

```bash
neat
```

The SDK workspace is mounted at `/workspace` inside the container.

## Local Repository Helper

If you are working directly from this repository, you can also start the SDK with:

```bash
./run.sh
```

`run.sh` tries to pull the configured SDK image from GitHub Container Registry first and falls back to a matching local image if present. It mounts the current directory into `/workspace`.

You can also run Docker directly:

```bash
docker pull ghcr.io/sima-neat/sdk:latest
docker run --rm -it --name sdk --privileged \
  -p 9900:9900 -p 9000-9079:9000-9079 -p 9100-9179:9100-9179 -p 8081:8081 -p 8554:8554 \
  -v "$(pwd):/workspace" -w /workspace -v /dev:/dev --pid=host \
  ghcr.io/sima-neat/sdk:latest /bin/bash -l
```

The build environment is configured automatically when the container starts. To configure it manually:

```bash
source /opt/bin/simaai-init-build-env modalix
```

## Pair With A DevKit

The SDK supports an NFS-based shared workspace with a DevKit. The workspace is shared bi-directionally between the host and the DevKit.

Start the SDK container with the DevKit IP:

```bash
sima-cli sdk setup --devkit-ip 10.0.0.244
```

Open a direct SSH shell to the paired DevKit:

```bash
dk shell
```

Run an executable or Python application from the DevKit:

```bash
dk /workspace/app-binary-or-dot-py-file
```

## Advanced Topics

- [Official Neat SDK installation guide](https://docs.sima-neat.com/getting-started/installation/neat-elxr-sdk)
- [Build the SDK image locally](docs/building-sdk-image.md)
- [Manage NEAT Insight in the SDK container](docs/neat-insight.md)
- [Use the DevKit NFS workspace](docs/devkit-workspace.md)
- [Build kernel, U-Boot, and device-tree artifacts](docs/building-software.md)
- [Install BSP artifacts on a board](docs/installing-artifacts.md)
- [SDK smoke tests](tests/sdk/README.md)

## Supported Platforms

The examples use the `modalix` platform. The same flow can be adapted to `davinci` where corresponding platform configuration is available.

The SDK sysroot is located under:

```text
/opt/toolchain/aarch64/<platform>
```

## References

- [eLxr project](https://elxr.org/about)
- [Docker Engine installation](https://docs.docker.com/engine/install/ubuntu/)
