<p align="center">
  <img src="images/simaai_logo.png" alt="SiMa.ai Logo" width="30%">
</p>

# SiMa.ai Neat SDK

[![Build Docker Image](https://github.com/sima-neat/sdk/actions/workflows/docker-build.yml/badge.svg)](https://github.com/sima-neat/sdk/actions/workflows/docker-build.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-supported-E95420?logo=ubuntu&logoColor=white)
![Windows 11](https://img.shields.io/badge/Windows%2011-supported-0078D4?logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-supported-000000?logo=apple&logoColor=white)
![eLxr Platform 2.1.2](https://img.shields.io/badge/eLxr%20Platform-2.1.2%20compatible-2E7D32)
![Modalix](https://img.shields.io/badge/Modalix-supported-4B5563)

This repository packages the SiMa.ai Neat SDK as a Docker image for `x86_64` and `arm64` Linux hosts.

The current Neat SDK image is compatible with the eLxr platform `2.1.2` release.

The main user workflow is:

1. Install `sima-cli`.
2. Install the SDK container image.
3. Start the SDK and optionally pair with a Modalix DevKit.
4. On x86 platforms, during setup optionally install Model SDK extension.
5. Use VS Code to attach to the running container for an IDE.

## Install The SDK

Install the latest published SDK and run setup:

```bash
sima-cli neat install sdk@developer
```

Install a released SDK version:

```bash
sima-cli neat install sdk@{version}
```

The install command pulls the SDK image and then asks whether to pair the SDK
with a Modalix DevKit. If you choose to pair, enter the DevKit IP address when
prompted.

You can still install a container image resource directly when needed:

```bash
sima-cli install ghcr:sima-neat/sdk:latest
```

Install a branch-specific image:

```bash
sima-cli install ghcr:sima-neat/sdk:feature-devkit-sync
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

The SDK image also preinstalls the OpenAI Codex CLI. From the SDK shell, run:

```bash
codex
```

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
  -p 9900:9900 -p 9999:9999 -p 10000:10000 -p 9000-9079:9000-9079 -p 9100-9179:9100-9179 -p 8081:8081 -p 8554:8554 \
  -v "$(pwd):/workspace" -w /workspace -v /dev:/dev --pid=host \
  ghcr.io/sima-neat/sdk:latest /bin/bash -l
```

The build environment is configured automatically when the container starts. To configure it manually:

```bash
source /opt/bin/simaai-init-build-env modalix
```

The browser-based VS Code server starts automatically with the SDK container. Full Neat SDK containers keep the HTTP editor endpoint on port `9999` for reverse proxies such as an AWS ALB, and also expose a local HTTPS endpoint using the SDK certificate mounted at `/sdk-cert`. Open the `codeUI` URL printed by `sima-cli sdk setup`; browsers may require trusting the local certificate before loading editor webviews.

To start it manually if supervision is disabled:

```bash
sima-code
```

By default, it serves `/workspace` and runs as the SDK user configured by `sima-cli sdk setup`. Set `OPENVSCODE_SERVER_TOKEN` before the container starts if the port is exposed beyond a trusted local machine. Set `OPENVSCODE_SERVER_CERT` and `OPENVSCODE_SERVER_CERT_KEY` to override the HTTPS certificate files, or mount `/sdk-cert/neat-sdk.pem` and `/sdk-cert/neat-sdk-key.pem`. Set `OPENVSCODE_SERVER_HTTPS_PORT` to change the HTTPS listener port. Set `OPENVSCODE_SERVER_SUPERVISED=0` to disable automatic startup.

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
- [Manage Neat Insight in the SDK container](docs/neat-insight.md)
- [Use the DevKit NFS workspace](docs/devkit-workspace.md)
- [Build kernel, U-Boot, and device-tree artifacts](docs/building-software.md)
- [Install BSP artifacts on a board](docs/installing-artifacts.md)
- [SDK smoke tests](tests/sdk/README.md)

## References

- [eLxr project](https://elxr.org/about)
- [Docker Engine installation](https://docs.docker.com/engine/install/ubuntu/)
