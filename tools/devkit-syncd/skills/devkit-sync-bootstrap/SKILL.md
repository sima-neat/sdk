---
name: devkit-sync-bootstrap
description: Configure NFS-based DevKit workspace access for the SDK container. Use when the user asks to pair/switch a DevKit, set up host export, and mount host workspace on DevKit using `run.py` and `source devkit.sh`.
---

# DevKit NFS Bootstrap

This skill is NFS-only and no longer uses `devkit-syncd`, `mutagen`, or `devkit-sync.yaml`.

## Workflow

1. Start SDK container with host export setup using `run.py` (or `run.sh`).
2. Enter container shell.
3. Source `devkit.sh` to configure remote DevKit mount.
4. Verify mount and Git safe-directory behavior.

## Commands

Start container and restrict export to one DevKit:

```bash
./run.sh --prefer-local --devkit-ip 10.0.0.244
```

Inside container:

```bash
source devkit.sh
```

Optional explicit user/port:

```bash
source devkit.sh 10.0.0.244 sima 22
```

## Validation

On DevKit:

```bash
mount | grep /nfs
ls -la /nfs
```

If running Git in mounted repo:

```bash
git config --global --get-all safe.directory
```

For operations and troubleshooting, use `references/ops.md`.
