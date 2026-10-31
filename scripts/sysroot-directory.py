#!/usr/bin/env python3
"""Replace a daily sysroot directory while keeping one complete rollback copy."""
import os
from pathlib import Path
import shutil
import sys


def remove(path):
    if path.exists():
        shutil.rmtree(path)


def relocate(root, destination):
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                target = os.readlink(path)
                if target.startswith(str(root) + "/"):
                    path.unlink()
                    path.symlink_to(str(destination) + target[len(str(root)):])
            elif path.suffix in (".pc", ".cmake", ".la") and path.is_file():
                path.write_text(path.read_text().replace(str(root), str(destination)))
    receipt = root / "var/lib/sima-sdk/sysroot-overlay"
    if receipt.exists():
        receipt.write_text(receipt.read_text().replace(str(root), str(destination)))


def require_sysroot(root):
    metadata = root / "var/lib/sima-sdk"
    if root.is_symlink() or not all(
        (metadata / name).is_file()
        for name in ("requested-packages", "sysroot-packages.tsv")
    ):
        raise RuntimeError(f"Not an initialized SDK sysroot: {root}")


def recover(active, previous, pending):
    if pending.exists():
        require_sysroot(previous)
        remove(active)
        shutil.copytree(previous, active, symlinks=True)
        pending.unlink()
        print("Restored sysroot after an interrupted replacement")


def main():
    operation, raw = sys.argv[1:3]
    active = Path(os.path.abspath(raw))
    if active.is_symlink():
        raise RuntimeError("Use a refreshed SDK image with a real sysroot directory")
    work = Path(str(active) + ".update")
    previous, pending = work / "previous", work / "pending"
    retired = work / "retired"
    if operation == "init":
        requested = sorted({p.strip() for p in os.environ.get("SDK_PKG_LIST", "").split(",") if p.strip()})
        manifest = active / "var/lib/sima-sdk/requested-packages"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("".join(p + "\n" for p in requested))
        return
    require_sysroot(previous if pending.exists() else active)
    if operation == "check":
        if pending.exists():
            raise RuntimeError("Interrupted replacement; run sysroot rollback before building")
        return
    if not previous.exists() and retired.exists():
        require_sysroot(retired)
        retired.rename(previous)
    recover(active, previous, pending)
    if operation == "recover":
        return
    work.mkdir(exist_ok=True)
    staging = work / "next"
    if operation == "prepare":
        remove(staging)
        staging.mkdir()
        return
    if operation == "rollback":
        require_sysroot(previous)
        remove(staging)
        shutil.copytree(previous, staging, symlinks=True)
    elif operation == "activate":
        require_sysroot(staging)
        relocate(staging, active)
    else:
        raise ValueError(operation)
    # Docker may copy+delete a lower-layer directory on rename. Complete the
    # backup first, so recovery never depends on a partially moved directory.
    backup = work / "backup"
    remove(backup)
    shutil.copytree(active, backup, symlinks=True)
    # Never recursively delete the backup that rollback can select.
    remove(retired)
    if previous.exists():
        previous.rename(retired)
    backup.rename(previous)
    remove(retired)
    pending.touch()
    try:
        remove(active)
        staging.rename(active)
        pending.unlink()
    except BaseException:
        recover(active, previous, pending)
        raise


if __name__ == "__main__":
    main()
