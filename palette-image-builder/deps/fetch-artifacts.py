#!/usr/bin/env python3
"""Fetch release-specific build artifacts; verify bytes before exposing them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

# The sbp tree pib package builds with, sbp (pkgbuild/) and its package configs (configs/packages/),
# and the files pib package looks for in it (pib/pib/sbp.py, SBP_FILES); the launcher mounts the
# same two from PIB_PKGBUILD_SRC.
SBP_PARTS = ('pkgbuild', 'configs/packages')
SBP_FILES = ('pkgbuild/sbp/cli.py', 'configs/packages/packages.yaml')


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


def pinned(source):
    """The upstream repository and commit: an HTTPS URL and a full commit SHA."""
    repository, commit = source['repository'], source['commit']
    if not repository.startswith('https://') or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('upstream needs an HTTPS repository and a full commit SHA')
    return repository, commit


def checkout(repository, commit, paths, destination):
    """Shallow sparse checkout of commit: the directories in paths (cone mode), the top-level files."""
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


def fetch_source(source, destination):
    """Sparse checkout of immutable board inputs, without upstream's binary bundle."""
    repository, commit = pinned(source)
    paths = source['paths']
    if not paths or any(not re.fullmatch('[a-z][a-z0-9_-]*', p) for p in paths):
        raise ValueError('upstream paths must be top-level directory names')
    checkout(repository, commit, paths, destination)
    print(f'Upstream board inputs pinned to {commit}')


def fetch_sbp(source, destination):
    """The sbp tree at the same pinned commit, into destination, with a SOURCE file naming the
    repository and commit, when that commit carries both parts. For a commit that carries
    neither, nothing is made and pib package needs PIB_PKGBUILD_SRC; one part alone is an error.
    Returns whether the tree was fetched."""
    repository, commit = pinned(source)
    destination = Path(destination)
    with tempfile.TemporaryDirectory() as staging:
        tree = Path(staging) / 'upstream'
        checkout(repository, commit, SBP_PARTS, tree)
        if not any((tree / part).exists() for part in SBP_PARTS):
            print(f'Upstream {commit} carries no sbp (pkgbuild/, configs/packages/): '
                  'pib package needs PIB_PKGBUILD_SRC')
            return False
        missing = [f for f in SBP_FILES if not (tree / f).is_file()]
        if missing:
            raise ValueError(f'upstream {commit} carries only part of sbp: it has no {", ".join(missing)}')
        destination.mkdir(parents=True)
        for part in SBP_PARTS:
            shutil.copytree(tree / part, destination / part, symlinks=True)
    (destination / 'SOURCE').write_text(f'{repository} {commit}\n')
    print(f'sbp and its package configs pinned to {commit}')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, usage=(
        '%(prog)s --destination DIR --release RELEASE --codename CODENAME\n'
        '       %(prog)s --sbp DIR'))
    parser.add_argument('--destination', metavar='DIR')
    parser.add_argument('--release')
    parser.add_argument('--codename')
    parser.add_argument('--sbp', metavar='DIR',
                        help='only the sbp tree pib package builds with (pkgbuild/, configs/packages/) of '
                             'the pinned upstream commit, into DIR, when that commit carries it; takes no '
                             'other option')
    args = parser.parse_args()
    manifest = Path(__file__).with_name('artifacts.json')
    source = json.loads(manifest.read_text())['upstream']
    options = ('destination', 'release', 'codename')
    if args.sbp is not None:
        if not args.sbp or any(getattr(args, n) is not None for n in options):
            parser.error('--sbp takes a directory and no other option')
        fetch_sbp(source, args.sbp)
    elif missing := [f'--{n}' for n in options if not getattr(args, n)]:
        parser.error(f'the following arguments are required: {", ".join(missing)} (or --sbp DIR alone)')
    else:
        fetch(manifest, args.destination, args.release)
        upstream = Path(args.destination) / 'upstream'
        fetch_source(source, upstream)
        for name, expected in (('RELEASE', args.release), ('CODENAME', args.codename)):
            if (upstream / name).read_text().strip() != expected:
                raise ValueError(f'upstream {name} does not match the selected platform')
