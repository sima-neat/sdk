#!/usr/bin/env python3
"""Prepare the small sdk/pib installer package, independently of the main SDK."""
import argparse
import json
from pathlib import Path
import re
import shutil

from sima_cli.install.package_builder import build_metadata, write_metadata

ROOT = Path(__file__).resolve().parents[1]


def prepare(output, image_resource, version, release):
    if not re.fullmatch(r'ghcr:[A-Za-z0-9_./:@-]+', image_resource):
        raise ValueError('image-resource must be a ghcr: reference')
    image = 'ghcr.io/' + image_resource.removeprefix('ghcr:').removeprefix('ghcr.io/')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('output directory must be empty')
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'tools/install_pib.py', output / 'install_pib.py')
    metadata = build_metadata(output, name='pib', version=version,
        description='SiMa.ai Palette Image Builder',
        install_script=(f'python3 ./install_pib.py --image {image} || '
                        f'python ./install_pib.py --image {image}'),
        host_platforms=['linux,mac,windows'], host_arches=['amd64,arm64'])
    metadata['resources'].append(image_resource)
    metadata['release'] = release
    metadata['size'] = {'download': '2GB', 'install': '2GB'}
    metadata['installation']['post-message'] = (
        'Palette Image Builder installed.\nOpen a new terminal if PATH was updated.\n'
        'Run [cyan]pib doctor[/cyan], then [cyan]pib init my-image --flavor minimal[/cyan].\n')
    write_metadata(output, metadata)
    print(f'Prepared sdk/pib package: {output}')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--image-resource', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    prepare(args.output_dir, args.image_resource, args.version, args.release)
