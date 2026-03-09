# DevKit NFS Ops

## Requirements

- Host: `docker`, `python3`, `sudo` access for export setup
- In container: `ssh`, `ssh-keygen`, `ssh-copy-id`, `bash`
- DevKit: SSH reachable, `sudo` available for mount/fstab/service setup

## Standard Flow

On host:

```bash
./run.sh --prefer-local --devkit-ip <devkit_ip>
```

Inside container:

```bash
source devkit.sh
```

## Common Errors

- `--devkit-ip is required`:
  - Use `--devkit-ip` when you want restricted export to one DevKit.
- `sudo: a terminal is required` / password prompt loops:
  - Configure passwordless sudo for DevKit user (`sima`) or rerun with `root`.
- NFS mount hangs/stales:
  - Re-run `source devkit.sh` to force remount and refresh watchdog.
  - Check host NFS export status (`showmount -e <host_ip>`).
- Git `dubious ownership` on `/nfs/...`:
  - Script should configure safe.directory automatically.
  - Manual fallback: `git config --global --add safe.directory /nfs`.

## Useful Checks

On DevKit:

```bash
showmount -e <host_ip>
mount | grep nfs
systemctl status devkit-nfs-watchdog.timer --no-pager
```

On host (macOS):

```bash
sudo nfsd checkexports
sudo nfsd restart
showmount -e localhost
```
