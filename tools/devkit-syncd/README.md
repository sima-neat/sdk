# DevKit Workspace Sync (NFS)

This repository now uses a simple NFS-based workflow for DevKit workspace access.

## What remains

- `run.py` / `run.sh`: host launcher for SDK container + host-side export setup
- `scripts/devkit.sh`: sourced inside container to configure remote DevKit mount

## What was removed

- `devkit-sync.yaml`
- `devkit-syncd` daemon and related bootstrap/check/run wrappers
- Mutagen/rsync/sshfs sync paths

## Quick Start

1. Start the SDK container and configure host share/export:

```bash
./run.sh --prefer-local --devkit-ip 10.0.0.244
```

2. Inside container, configure DevKit NFS mount:

```bash
source devkit.sh
```

`devkit.sh` uses environment injected by `run.py`:

- `NFS_SERVER_HOST_IP`
- `DEVKIT_HOST_EXPORT_PATH`
- `DEVKIT_HOST_PLATFORM`
- `DEVKIT_SYNC_DEVKIT_IP` (optional)

## Notes

- macOS host export uses NFSv3-compatible mount options on DevKit.
- Script installs a watchdog timer on DevKit to auto-remount stale mounts.
- Script configures Git `safe.directory` on DevKit for the mounted workspace path.
