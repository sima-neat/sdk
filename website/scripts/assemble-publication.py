#!/usr/bin/env python3
"""Build current main/develop snapshots into one GitHub Pages artifact."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def build(source, channel):
    site = source / 'website'
    if not (site / 'package.json').is_file():
        return None
    env = {**os.environ, 'DOCS_CHANNEL': channel}
    subprocess.run(['npm', 'ci'], cwd=site, env=env, check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=site, env=env, check=True)
    return site / 'build'


def assemble(production, preview, destination):
    if destination.exists():
        raise ValueError('publication destination must not exist')
    if production is not None:
        if (production / 'staging-preview').exists():
            raise ValueError('production build must not contain a staging-preview subtree')
        shutil.copytree(production, destination)
    else:
        # Bootstrap: develop can preview this new site before main contains it.
        # No develop documentation is promoted into the production root.
        destination.mkdir(parents=True)
        (destination / 'index.html').write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>Systems Builder Guide</title><h1>Systems Builder Guide</h1>'
            '<p>The production guide has not been released yet.</p>'
            '<p><a href="/staging-preview/">Preview unreleased documentation</a></p></html>\n')
    if preview is not None:
        shutil.copytree(preview, destination / 'staging-preview')
        # The single Pages site owns the domain, not its preview subtree.
        (destination / 'staging-preview/CNAME').unlink(missing_ok=True)
    (destination / 'CNAME').write_text('sdk.neat.sima.ai\n')
    (destination / 'robots.txt').write_text('User-agent: *\nDisallow: /staging-preview/\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--develop', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    production = build(args.main, 'production')
    preview = build(args.develop, 'preview')
    # An old main checkout may predate channel support. Its default root build
    # is safe; an old develop build without the preview prefix is not.
    if preview is not None and not (args.develop / 'website/site-settings.cjs').is_file():
        raise ValueError('develop does not yet support staging-preview publication')
    assemble(production, preview, args.output)
    commits = {branch: subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
               for branch, source in [('main', args.main), ('develop', args.develop)]}
    (args.output / 'publication.json').write_text(json.dumps(commits, indent=2) + '\n')


if __name__ == '__main__':
    main()
