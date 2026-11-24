#!/usr/bin/env python3
"""Fetch release-specific build artifacts; verify bytes before exposing them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request


def fetch(manifest, destination, release):
    data = json.loads(Path(manifest).read_text())
    if data['platform_release'] != release:
        raise ValueError(f'artifact release {data["platform_release"]} != platform {release}')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for artifact in data['artifacts']:
        name, url, expected = (artifact[k] for k in ('filename', 'url', 'sha256'))
        if Path(name).name != name or not name or not url.startswith('https://'):
            raise ValueError(f'invalid artifact name or URL: {name}')
        if not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError(f'invalid sha256: {name}')
        digest = hashlib.sha256()
        # A failed download/hash check never leaves an installable output file.
        with tempfile.TemporaryDirectory(dir=destination) as staging:
            partial = Path(staging) / name
            with urllib.request.urlopen(url, timeout=60) as source, partial.open('wb') as output:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f'sha256 mismatch: {name}')
            os.replace(partial, destination / name)
        print(f'Verified {name}: {expected}')


def fetch_source(source, destination):
    """Sparse checkout of immutable board inputs, without upstream's binary bundle."""
    repository, commit, paths = (source[k] for k in ('repository', 'commit', 'paths'))
    if not repository.startswith('https://') or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('upstream needs an HTTPS repository and a full commit SHA')
    if not paths or any(not re.fullmatch('[a-z][a-z0-9_-]*', p) for p in paths):
        raise ValueError('upstream paths must be top-level directory names')
    destination = Path(destination)
    destination.mkdir(parents=True)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(destination), *args], text=True).strip()
    git('init', '--quiet')
    git('remote', 'add', 'origin', repository)
    git('sparse-checkout', 'init', '--cone')
    git('sparse-checkout', 'set', *paths)
    git('-c', 'protocol.version=2', 'fetch', '--depth=1', '--filter=blob:none', 'origin', commit)
    git('-c', 'advice.detachedHead=false', 'checkout', '--detach', 'FETCH_HEAD')
    if git('rev-parse', 'HEAD') != commit:
        raise ValueError('upstream checkout does not match the pinned commit')
    print(f'Upstream board inputs pinned to {commit}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--codename', required=True)
    args = parser.parse_args()
    manifest = Path(__file__).with_name('artifacts.json')
    fetch(manifest, args.destination, args.release)
    upstream = Path(args.destination) / 'upstream'
    fetch_source(json.loads(manifest.read_text())['upstream'], upstream)
    for name, expected in (('RELEASE', args.release), ('CODENAME', args.codename)):
        if (upstream / name).read_text().strip() != expected:
            raise ValueError(f'upstream {name} does not match the selected platform')
