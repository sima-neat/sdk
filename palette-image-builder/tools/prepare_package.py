#!/usr/bin/env python3
"""Prepare the small sdk/pib installer package, independently of the main SDK."""
import argparse
import json
from pathlib import Path
import re
import shutil

from sima_cli.install.package_builder import build_metadata, write_metadata

ROOT = Path(__file__).resolve().parents[1]


def ghcr_image(what, resource):
    if not re.fullmatch(r'ghcr:[A-Za-z0-9_./:@-]+', resource):
        raise ValueError(f'{what} must be a ghcr: reference')
    return 'ghcr.io/' + resource.removeprefix('ghcr:').removeprefix('ghcr.io/')


def prepare(output, image_resource, version, release, sbp_image_resource=None):
    """sbp_image_resource, the pib-sbp image published with image_resource, is bound into the
    launcher (pib sbp's default image) but is not a resource: sima-cli would download it with
    every install, and only kernel builds use it; Docker pulls it on the first pib sbp."""
    image = ghcr_image('image-resource', image_resource)
    options = f'--image {image}'
    if sbp_image_resource:
        options += f' --sbp-image {ghcr_image("sbp-image-resource", sbp_image_resource)}'
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('output directory must be empty')
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'tools/install_pib.py', output / 'install_pib.py')
    metadata = build_metadata(output, name='pib', version=version,
        description='SiMa.ai Palette Image Builder',
        install_script=(f'python3 ./install_pib.py {options} || '
                        f'python ./install_pib.py {options}'),
        host_platforms=['linux,mac,windows'], host_arches=['amd64,arm64'])
    metadata['resources'].append(image_resource)
    metadata['release'] = release
    metadata['size'] = {'download': '2GB', 'install': '2GB'}
    metadata['installation']['post-message'] = (
        'Palette Image Builder installed.\nOpen a new terminal if PATH was updated.\n'
        'Run [cyan]pib init my-image --flavor minimal[/cyan] to get started.\n')
    write_metadata(output, metadata)
    print(f'Prepared sdk/pib package: {output}')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--image-resource', required=True)
    parser.add_argument('--sbp-image-resource', help='the pib-sbp image published with --image-resource')
    parser.add_argument('--version', required=True)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    prepare(args.output_dir, args.image_resource, args.version, args.release, args.sbp_image_resource)
