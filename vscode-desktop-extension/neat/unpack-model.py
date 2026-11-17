"""Unpack downloaded model packages for review without executing contents."""
import shutil
import stat
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def safe_name(value):
    name = PurePosixPath(value)
    if name.is_absolute() or '..' in name.parts or '\\' in value or ':' in value:
        raise ValueError('Unsafe archive path')
    return name


def unpack(root, downloaded):
    root, downloaded = Path(root).resolve(), Path(downloaded).resolve()
    if not downloaded.is_relative_to(root):
        raise ValueError('Downloaded artifact is outside the model folder')
    if downloaded.is_dir():
        return
    target = root / 'contents'
    if zipfile.is_zipfile(downloaded):
        with zipfile.ZipFile(downloaded) as archive:
            members = archive.infolist()
            for item in members:
                safe_name(item.filename)
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('Archive links are not supported')
            if sum(m.file_size for m in members) > shutil.disk_usage(root).free:
                raise ValueError('Not enough disk space to unpack this model')
            target.mkdir(exist_ok=False)
            archive.extractall(target)
    elif tarfile.is_tarfile(downloaded):
        with tarfile.open(downloaded) as archive:
            members = archive.getmembers()
            for item in members:
                safe_name(item.name)
                if not (item.isfile() or item.isdir()):
                    raise ValueError('Archive links and special files are not supported')
            if sum(m.size for m in members) > shutil.disk_usage(root).free:
                raise ValueError('Not enough disk space to unpack this model')
            target.mkdir(exist_ok=False)
            for item in members:
                output = target.joinpath(*safe_name(item.name).parts)
                if item.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(item) as source, output.open('xb') as dest:
                        shutil.copyfileobj(source, dest)
    # Individual MPK/ONNX/etc. files are already reviewable as downloaded.


if __name__ == '__main__':
    unpack(*sys.argv[1:])
