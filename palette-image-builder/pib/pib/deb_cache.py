"""Content-addressed Debian downloads, authorized by each bootstrap's fresh APT indexes."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def verified_copy(source, destination, digest, size):
    """Verify the bytes actually copied, rather than trusting a filename or sidecar."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            sha = hashlib.sha256()
            count = 0
            with source.open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    output.write(block)
                    sha.update(block)
                    count += len(block)
            output.close()
            if count != size or sha.hexdigest() != digest:
                return False
            temp.chmod(0o644)
            os.replace(temp, destination)
            return True
        finally:
            temp.unlink(missing_ok=True)


def trusted_records(wanted, packages=None):
    """Read SHA256 and sizes only from APT-authenticated package indexes."""
    import apt_pkg
    apt_pkg.init_config()
    apt_pkg.init_system()
    cache = apt_pkg.Cache(None)
    sources = apt_pkg.SourceList()
    sources.read_main_list()
    seen = set()
    for package_file in cache.file_list:
        index = sources.find_index(package_file)
        if index is None or not index.is_trusted:
            continue
        proc = subprocess.Popen(['/usr/lib/apt/apt-helper', 'cat-file', package_file.filename],
                                stdout=subprocess.PIPE)
        try:
            for record in apt_pkg.TagFile(proc.stdout):
                digest = record.get('SHA256', '')
                if digest not in wanted or digest in seen:
                    continue
                if packages is not None and (record['Package'], record['Version'], record['Architecture']) not in packages:
                    continue
                name = record['Package']
                version = apt_pkg.quote_string(record['Version'], ':')
                archive = f"{name}_{version}_{record['Architecture']}.deb"
                if Path(archive).name != archive:
                    raise RuntimeError('invalid archive name in APT metadata')
                seen.add(digest)
                yield digest, int(record['Size']), archive
            if proc.wait() != 0:
                raise RuntimeError('cannot read authenticated APT package index')
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.terminate()
                proc.wait()


def transfer(mode, root, directory):
    archives = root / 'var/cache/apt/archives'
    archives.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if mode == 'restore':
        files = {p.stem: p for p in directory.glob('*.deb')
                 if re.fullmatch('[0-9a-f]{64}', p.stem) and not p.is_symlink() and p.is_file()}
    else:
        files = {}
        # A restored archive may still be authorized by the repository without
        # being selected by this build. Only retain packages actually used.
        candidates = (root / p.lstrip('/') for p in os.environ.get('MMDEBSTRAP_ESSENTIAL', '').split()) \
            if os.environ.get('MMDEBSTRAP_HOOK') == 'extract' else archives.glob('*.deb')
        for p in candidates:
            if p.is_file() and not p.is_symlink():
                with p.open('rb') as stream:
                    files[hashlib.file_digest(stream, 'sha256').hexdigest()] = p
    count = total = rejected = 0
    packages = None
    if mode == 'save' and os.environ.get('MMDEBSTRAP_HOOK') == 'customize':
        packages = set()
        status = root / 'var/lib/dpkg/status'
        for stanza in (status.read_text() if status.exists() else '').split('\n\n'):
            fields = dict(line.split(': ', 1) for line in stanza.splitlines()
                          if ': ' in line and not line.startswith((' ', '\t')))
            if fields.get('Status', '').endswith((' installed', ' unpacked')):
                packages.add(tuple(fields.get(key, '') for key in ('Package', 'Version', 'Architecture')))
    if files:
        for digest, size, name in trusted_records(set(files), packages):
            source = files[digest]
            target = archives / name if mode == 'restore' else directory / f'{digest}.deb'
            if verified_copy(source, target, digest, size):
                if mode == 'save' and os.environ.get('PIB_DEB_CACHE_USED'):
                    used = Path(os.environ['PIB_DEB_CACHE_USED'])
                    used.mkdir(parents=True, exist_ok=True)
                    (used / digest).touch()
                count += 1
                total += size
            else:
                rejected += 1
                if mode == 'restore':
                    source.unlink(missing_ok=True)
    print(f'pib: Debian cache {mode}: verified={count} bytes={total} rejected={rejected}', flush=True)


def prune(directory, used):
    """Keep the union saved by all successful bootstrap phases, not old downloads."""
    for blob in directory.glob('*.deb'):
        if not (used / blob.stem).is_file():
            blob.unlink()


def main():
    mode, root = sys.argv[1:]
    root = Path(root)
    config = os.environ.get('MMDEBSTRAP_APT_CONFIG')
    if not config or not Path(config).is_file():
        raise RuntimeError('mmdebstrap APT configuration is required')
    os.environ['APT_CONFIG'] = config
    if mode == 'restore':
        # Authenticate current metadata before considering any cached bytes.
        # Generate both caches so mmdebstrap recognizes that update already ran.
        subprocess.run(['apt-get', '-oDir::Cache::pkgcache=pkgcache.bin',
                        '-oDir::Cache::srcpkgcache=srcpkgcache.bin',
                        'update', '--error-on=any'], check=True)
        for name in ('pkgcache.bin', 'srcpkgcache.bin'):
            if not (root / 'var/cache/apt' / name).is_file():
                raise RuntimeError('APT metadata cache missing; refusing a second metadata update')
    elif mode != 'save':
        raise ValueError(f'unknown cache operation: {mode}')
    transfer(mode, root, Path(os.environ['PIB_DEB_CACHE_DIR']))


if __name__ == '__main__':
    main()
