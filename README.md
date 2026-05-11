<p align="center">
  <img src="images/simaai_logo.png" alt="SiMa.ai Logo" width="30%">
</p>

# SiMa.ai NEAT SDK

[![Build Docker Image](https://github.com/sima-neat/sdk/actions/workflows/docker-build.yml/badge.svg)](https://github.com/sima-neat/sdk/actions/workflows/docker-build.yml)
[![Smoke Test](https://github.com/sima-neat/sdk/actions/workflows/smoke-test.yml/badge.svg)](https://github.com/sima-neat/sdk/actions/workflows/smoke-test.yml)

This repository packages the SiMa.ai NEAT SDK as a Docker image for `x86_64` and `arm64` Linux hosts.

The main user workflow is:

1. Install `sima-cli`.
2. Install the SDK container image.
3. Start the SDK workspace.
4. Optional: pair the SDK container with a DevKit.

## Prerequisites

- Ubuntu Linux host with Docker Engine installed.
- Access to GitHub Container Registry packages for this repository.
- `sima-cli` installed in a Python virtual environment.
- Optional: a SiMa.ai DevKit reachable over SSH when using DevKit workspace sync.

Install `sima-cli`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
curl -fsSL \
  https://artifacts.sima-neat.com/tools/sima_cli-2.1.5-py3-none-any.whl \
  -o sima_cli-2.1.5-py3-none-any.whl
python -m pip install ./sima_cli-2.1.5-py3-none-any.whl
```

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

Run the SDK setup in non-interactive mode:

```bash
sima-cli sdk setup -y -n
```

Open the SDK shell:

```bash
sima-cli sdk neat
```

Check the installed SDK status from inside the SDK shell:

```bash
neat --json
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
./run.sh --prefer-local --devkit-ip 10.0.0.244
```

If the host IP selected for NFS is not reachable from the DevKit, provide the host interface IP explicitly:

```bash
./run.sh --prefer-local --devkit-ip 10.0.0.244 --hostip 10.0.0.10
```

Inside the SDK container, source the DevKit helper:

```bash
source devkit.sh
```

This configures the remote DevKit mount, updates DevKit `/etc/fstab`, enables stale-mount recovery, and sets Git `safe.directory` for the mounted workspace path.

Open a direct SSH shell to the paired DevKit:

```bash
dk shell
```

## Advanced Topics

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
