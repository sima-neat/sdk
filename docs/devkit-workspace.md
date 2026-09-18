# DevKit Workspace

The DevKit workspace flow prefers NFS, which shares the workspace bi-directionally
between the host and the DevKit. If the host export cannot be configured or the
DevKit cannot mount it, setup falls back to rsync over SSH.

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

When host NFS is available, this configures the remote DevKit mount, updates
DevKit `/etc/fstab`, enables a watchdog timer for stale mount recovery, and sets
Git `safe.directory` for the mounted workspace path.

When `sima-cli` cannot configure the host export, it sets
`DEVKIT_HOST_NFS_AVAILABLE=0`. `devkit.sh` then skips the NFS mount and initializes
the rsync workspace directly. Older `sima-cli` versions do not set the variable,
so NFS remains the default.

Use `dk status` to see the active sync method. With rsync active, `dk <path>`
synchronizes the relevant top-level workspace folder before running the remote
command; `dk sync --all` synchronizes the entire workspace explicitly.

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
