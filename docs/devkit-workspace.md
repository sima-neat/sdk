# DevKit Workspace

The DevKit workspace flow uses NFS. The workspace is shared bi-directionally between the host and the DevKit.

## Start The SDK Container

Start the SDK container and configure the host-side NFS export:

```bash
./run.sh --prefer-local --devkit-ip 10.0.0.244
```

If the host IP selected for NFS is not reachable from the DevKit, provide the host interface IP explicitly:

```bash
./run.sh --prefer-local --devkit-ip 10.0.0.244 --hostip 10.0.0.10
```

## Configure The DevKit Mount

Inside the SDK container, source the setup helper:

```bash
source devkit.sh
```

This configures the remote DevKit mount, updates DevKit `/etc/fstab`, enables a watchdog timer for stale mount recovery, and sets Git `safe.directory` for the mounted workspace path.

## NEAT Framework Sync

During setup, `devkit.sh` compares the SDK NEAT framework package versions cached under:

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
