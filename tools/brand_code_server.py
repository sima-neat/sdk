#!/usr/bin/env python3
"""Use the Neat extension icon as code-server's browser favicon."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--server-dir', type=Path, default=Path('/opt/code-server'))
parser.add_argument('--icon', type=Path, default=Path(__file__).resolve().parents[1] / 'vscode-extension/media/neat-logo.png')
args = parser.parse_args()
icon = args.icon.read_bytes()
if not icon.startswith(b'\x89PNG\r\n\x1a\n'):
    parser.error('--icon must be a PNG')
name = f'neat-favicon-{hashlib.sha256(icon).hexdigest()[:12]}.png'
media = args.server_dir / 'src/browser/media'
templates = [args.server_dir / p for p in (
    'src/browser/pages/login.html',
    'src/browser/pages/error.html',
    'lib/vscode/out/vs/code/browser/workbench/workbench.html',
)]
pattern = re.compile(r'<link\b[^>]*\brel="(?:alternate )?icon"[^>]*>', re.I)
asset = re.compile(r'(?P<prefix>/src/browser/media/)(?:favicon(?:-dark-support)?\.(?:svg|ico)|neat-favicon-[a-f0-9]+\.png)')
updates = []
# Validate all upstream templates before changing files; fail visibly on layout drift.
if not media.is_dir():
    parser.error(f'Missing code-server media directory: {media}')
for template in templates:
    original = template.read_text()
    count = [0]
    def replace(match):
        tag, replaced = asset.subn(lambda m: m['prefix'] + name, match[0])
        if replaced:
            count[0] += 1
            tag = re.sub(r'\s+type="[^"]*"', '', tag)
            tag = tag.replace('<link ', '<link type="image/png" ', 1)
        return tag
    updated = pattern.sub(replace, original)
    if count[0] != 2:
        parser.error(f'Expected two favicon links in {template}; found {count[0]}')
    updates.append((template, updated))
shutil.copyfile(args.icon, media / name)
(media / name).chmod(0o644)
for template, updated in updates:
    template.write_text(updated)
print(f'Branded editor, login, and error favicons with {name}')
