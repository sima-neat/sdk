#!/usr/bin/env python3
"""Delegate camera requests through code-server's Palette webview frames.

This enables the browser permission prompt, not camera access without consent.
Other extensions retain upstream policy. Insight's own iframe restricts camera
delegation to the resolved Insight origin.
"""
import argparse
import base64
import hashlib
from pathlib import Path
import re


def patch_workbench(source):
    marker = '/* palette-insight-camera-outer */'
    if marker in source:
        return source
    pattern = (r'(_createElement\((\w+),(\w+)\)\{let (\w+)=document\.createElement\("iframe"\);)'
               r'(.*?)((\w+)\.setAttribute\("allow",(\w+)\.join\("; "\)\))')
    matches = list(re.finditer(pattern, source, re.S))
    if len(matches) != 1:
        raise ValueError(f'Expected one webview iframe policy; found {len(matches)}')
    m = matches[0]
    if m[4] != m[7]:
        raise ValueError('Webview iframe variable changed')
    guard = marker + f'{m[3]}?.id.value==="sima-neat.sima-neat"&&{m[8]}.push("camera *"),'
    return source[:m.start(6)] + guard + source[m.start(6):]


def patch_preload(source):
    marker = '// palette-insight-camera-inner'
    if marker in source:
        return update_script_hash(source)
    anchor = "newFrame.setAttribute('allow', allowRules.join(' '));"
    if source.count(anchor) != 1 or "const searchParams =" not in source:
        raise ValueError('Webview preload policy layout changed')
    guard = (marker + '\n'
             "\t\t\t\tif (searchParams.get('extensionId') === 'sima-neat.sima-neat') {\n"
             "\t\t\t\t\tallowRules.push('camera *;');\n"
             "\t\t\t\t}\n\t\t\t\t")
    return update_script_hash(source.replace(anchor, guard + anchor))


def update_script_hash(source):
    scripts = re.findall(r'<script async type="module">(.*?)</script>', source, re.S)
    if len(scripts) != 1:
        raise ValueError('Expected one webview preload script')
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    source, count = re.subn(r"sha256-[A-Za-z0-9+/=]+", 'sha256-' + digest, source)
    if count != 1:
        raise ValueError('Expected one preload CSP script hash')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-dir', type=Path, default=Path('/opt/code-server'))
    args = parser.parse_args()
    base = args.server_dir / 'lib/vscode/out/vs'
    bundle = base / 'code/browser/workbench/workbench.js'
    preload = base / 'workbench/contrib/webview/browser/pre/index.html'
    # Validate both upstream anchors before mutating either file.
    updates = [(bundle, patch_workbench(bundle.read_text())),
               (preload, patch_preload(preload.read_text()))]
    for file, content in updates:
        file.write_text(content)


if __name__ == '__main__':
    main()
