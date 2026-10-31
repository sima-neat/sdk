#!/usr/bin/env python3
"""Keep explicitly marked Insight HTTPS links out of code-server's HTTP proxy."""
import argparse
from pathlib import Path
import re


def patch(source):
    marker = '/* palette-insight-direct */'
    if marker in source:
        return source
    pattern = r'resolveExternalUri:([A-Za-z_$][\w$]*)=>\{'
    matches = list(re.finditer(pattern, source))
    if len(matches) != 1:
        raise ValueError(f"Expected one browser external URI resolver; found {len(matches)}")
    match = matches[0]
    uri = match[1]
    guard = (marker + f'if({uri}.scheme==="https")'
             + '{const q=new URLSearchParams(' + uri + '.query);'
             + 'if(q.get("palette-insight-direct")==="1")'
             + '{q.delete("palette-insight-direct");return Promise.resolve('
             + uri + '.with({query:q.toString()}))}}')
    return source[:match.end()] + guard + source[match.end():]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-dir", type=Path, default=Path("/opt/code-server"))
    args = parser.parse_args()
    bundle = args.server_dir / "lib/vscode/out/vs/code/browser/workbench/workbench.js"
    bundle.write_text(patch(bundle.read_text()))
