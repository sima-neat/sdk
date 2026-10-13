#!/usr/bin/env python3
"""Prepare the isolated GCC16 prefix once while building the SDK image.

The small vendored installer is byte-pinned to Kernels so building this image
does not require credentials for a second private Git repository.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def load_installer(directory):
    source = directory / 'ensure_gcc16.py'
    provenance = json.loads((directory / 'source.json').read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest() != provenance['sha256']:
        raise ValueError('Vendored GCC16 installer differs from its pinned source')
    spec = importlib.util.spec_from_file_location('sdk_gcc16_installer', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.VERSION != provenance['version']:
        raise ValueError('Unexpected GCC version in pinned installer')
    return module, provenance


def install(vendor, sysroot, cache, jobs):
    installer, provenance = load_installer(vendor)
    root = installer.ensure('aarch64', sysroot.resolve(strict=True), cache,
                            auto_install=True, jobs=jobs)
    # The stable path is an alias within the SDK-owned directory, not a change
    # to /usr/bin or the default compiler selected by other SDK consumers.
    alias = cache / 'aarch64'
    if not root.is_relative_to(cache.resolve()):
        raise ValueError('Expected the isolated SDK GCC16 prefix')
    if alias.is_symlink():
        if alias.resolve(strict=True) != root:
            raise ValueError('Refusing to replace a different GCC16 SDK alias')
    elif alias.exists():
        raise ValueError('Compiler alias path already exists')
    else:
        alias.symlink_to(root.name)
    return {'schema': 1, 'version': installer.VERSION, 'prefix': str(alias),
            'sysroot': str(sysroot), 'installer': provenance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path, required=True)
    parser.add_argument('--sysroot', type=Path, default=Path('/opt/toolchain/aarch64/modalix'))
    parser.add_argument('--cache', type=Path, default=Path('/opt/toolchain/gcc16'))
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--manifest', type=Path, default=Path('/usr/local/share/sima-sdk/gcc16.json'))
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    result = install(args.vendor, args.sysroot, args.cache, args.jobs)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
