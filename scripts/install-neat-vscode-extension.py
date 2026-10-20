#!/usr/bin/env python3
"""Copy the image's Neat extension into the invoking user's code-server profile."""
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def extension_entry(directory):
    package = json.loads((directory / "package.json").read_text())
    return {
        "identifier": {"id": package["publisher"] + "." + package["name"]},
        "version": package["version"],
        "location": {"$mid": 1, "scheme": "file", "path": str(directory.resolve())},
        "relativeLocation": directory.name,
    }


def install(seed, extensions):
    seed, extensions = Path(seed), Path(extensions)
    package = json.loads((seed / 'package.json').read_text())
    identifier = package['publisher'] + '.' + package['name']
    digest = hashlib.sha256()
    for path in sorted(seed.rglob('*')):
        if path.is_file():
            digest.update(str(path.relative_to(seed)).encode())
            digest.update(path.read_bytes())
    name = identifier + '-' + package['version'] + '-' + digest.hexdigest()[:16]
    extensions.mkdir(parents=True, exist_ok=True)
    with (extensions / '.sima-neat-setup.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        destination = extensions / name
        if not destination.exists():
            with tempfile.TemporaryDirectory(prefix='.sima-neat-', dir=extensions) as tmp:
                staging = Path(tmp) / name
                shutil.copytree(seed, staging)
                staging.rename(destination)
        profile = extensions / 'extensions.json'
        # Older profiles may have folders but no registry yet. Preserve those too.
        entries = (json.loads(profile.read_text()) if profile.exists() else
                   [extension_entry(path.parent) for path in sorted(extensions.glob('*/package.json'))])
        if not isinstance(entries, list):
            raise ValueError('Invalid extension profile: ' + str(profile))
        entries = [entry for entry in entries if entry['identifier']['id'].lower() != identifier.lower()]
        entries.append(extension_entry(destination))
        with tempfile.NamedTemporaryFile(mode='w', prefix='.sima-neat-profile-', dir=extensions, delete=False) as out:
            temporary = Path(out.name)
            json.dump(entries, out, indent=2)
            out.write('\n')
        try:
            temporary.replace(profile)
        finally:
            temporary.unlink(missing_ok=True)
    print('SiMa Neat extension ready: ' + str(destination))


if __name__ == '__main__':
    import sys
    install('/opt/sima-neat/vscode-extension', sys.argv[1] if len(sys.argv) > 1 else
            Path.home() / '.local/share/code-server/extensions')
