#!/usr/bin/env python3
"""The SDK's GHCR repository/tag scheme, scoped to Palette Image Builder."""
import json
import os
import re


def slug(ref):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9._-]+', '-', ref.lower())).strip('-') or 'branch'


def configuration(owner, ref, sha, event='push', head_ref=''):
    canonical = f'ghcr.io/{owner.lower()}/palette-image-builder'
    branch = slug(head_ref or ref.removeprefix('refs/heads/'))
    release = re.fullmatch(r'refs/tags/(v([0-9]+)\.([0-9]+)\.[0-9]+(?:\.[0-9]+)?)', ref)
    if ref.startswith('refs/tags/') and not release:
        raise ValueError('Release tags must use vX.Y.Z or vX.Y.Z.N')
    repository = canonical if ref == 'refs/heads/main' or release else f'{canonical}-{branch}'
    if release:
        tags = [f'{canonical}:{release[1]}', f'{canonical}:v{release[2]}.{release[3]}-latest']
        cache = f'release-{release[2]}.{release[3]}'
    else:
        tags = [f'{repository}:latest', f'{canonical}:{branch}']
        cache = branch
    return dict(repository=repository, canonical=canonical, commit=sha,
                staged=f'{repository}:staged-{sha}', cache_scope=cache,
                promotion_tags='\n'.join(dict.fromkeys(tags)), publish=str(event != 'pull_request').lower())


if __name__ == '__main__':
    cfg = configuration(os.environ['GITHUB_REPOSITORY_OWNER'], os.environ['GITHUB_REF'],
                        os.environ['GITHUB_SHA'], os.environ.get('GITHUB_EVENT_NAME', 'push'),
                        os.environ.get('GITHUB_HEAD_REF', ''))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            for key, value in cfg.items():
                out.write(f'{key}<<PIB_OUTPUT\n{value}\nPIB_OUTPUT\n')
    print(json.dumps(cfg, indent=2))
