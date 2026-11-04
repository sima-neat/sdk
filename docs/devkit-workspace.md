# DevKit Workspace

The DevKit workspace flow uses NFS. The workspace is shared bi-directionally between the host and the DevKit.

## Start The SDK Container

Start the SDK container and configure the host-side DevKit integration:

```bash
sima-cli sdk setup --devkit 10.0.0.244
```

Then open the SDK shell:

```bash
sima-cli sdk neat
```

## Configure The DevKit Mount

Inside the SDK container, source the setup helper:

```bash
source devkit.sh
```

Setup probes for `/usr/local/sbin/kerrigan-sdk-nfs` on the DevKit before checking
general sudo access. When the helper is available, it mounts the approved CloudEx
host export at `/workspace` using the existing restricted sudo permission. SSH key
setup still runs as the selected DevKit user. Setup leaves sudoers unchanged and
does not install an fstab entry or a watchdog for this session-scoped mount.

The helper must support `/workspace`, and the CloudEx session must permit the
export. An unusable helper, rejected export or SSH failure stops setup with an
error. Ask the Kerrigan administrator to update or repair the helper if necessary.
Setup does not fall back to granting unrestricted sudo after these errors.

If the helper is absent, the existing setup flow applies: configure the remote
mount, update `/etc/fstab`, enable a watchdog timer for stale mount recovery, and
set Git `safe.directory`. This flow requires root or general passwordless sudo.

## NEAT Framework Sync

For a Kerrigan-managed DevKit with the NFS helper, Neat/PyNeat are supplied by the
Kerrigan device bundle. Pairing skips SDK package synchronization; ask the
administrator to update the bundle when a different Neat version is needed.

For other DevKits, `devkit.sh` compares the SDK NEAT framework package versions cached under:

```text
${SYSROOT:-/opt/toolchain/aarch64/modalix}/neat-install-packages
```

with the versions installed on the DevKit. If the DevKit is missing NEAT framework packages or has different versions, the SDK copies its cached artifacts to the DevKit and runs the cached installer locally there.

Optional controls:

```bash
DEVKIT_NEAT_SYNC=OFF           # skip NEAT framework version check/sync
DEVKIT_NEAT_SYNC_REQUIRED=ON   # fail setup if NEAT framework sync fails
DEVKIT_NEAT_SYNC_CACHE_DIR=... # override SDK artifact cache directory
```

## Open A DevKit Shell

```bash
dk shell
```

## Deploy A Container To The DevKit

For SDK 3.0 and newer, sima-cli can set up a local container registry while it
connects the SDK to the DevKit. Build and push an ARM64 image from the directory
that contains your Dockerfile:

```bash
docker buildx build \
  --platform linux/arm64 \
  --tag "${SIMA_CONTAINER_REGISTRY}/hello-neat:develop" \
  --push \
  .
```

Then download the image on the connected DevKit and run it:

```bash
dk container deploy hello-neat:develop --detach --name hello-neat --network host
```

The image name does not need the registry address. `dk` replaces the SDK
address with the DevKit address configured by sima-cli. Before starting the
container, it also verifies that the downloaded image is ARM64.

Use `run` when the image is already on the DevKit:

```bash
dk container run hello-neat:develop --rm
```

Arguments before `--` are Docker run options. Arguments after `--` are passed
to the command inside the container:

```bash
dk container run hello-neat:develop --rm -- --help
```

Other useful commands:

```bash
dk container pull hello-neat:develop
dk container images
dk container list
dk container logs hello-neat --follow
dk container stop hello-neat
dk container remove hello-neat
```

Run `dk container help` to show the command summary. If the registry is not
configured, rerun `sima-cli sdk setup --devkit <devkit-ip>` and open a new SDK
shell.

Docker is not installed or changed during ordinary SDK setup. If it is missing
on the DevKit, the first `dk container` command explains the required board
changes and asks whether to install it. The
installer uses the Modalix storage and networking configuration, stores Docker
and containerd data under `/data`, enables the services, and adds the DevKit
user to the `docker` group. It also configures the scoped SDK registry before
retrying the original command. It requires passwordless `sudo` and Internet
access to Docker's Debian repository. For an explicitly approved noninteractive
installation, run:

```bash
dk container setup --yes
```
