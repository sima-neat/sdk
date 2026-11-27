#!/usr/bin/env python3
"""CI: start pib package through a launcher and check that its container set-up ran.

    check-sbp-start.py LAUNCHER...    e.g. python3 host/pib, or an installed pib

"pib package --list" runs sbp/setup.sh first (sbp's local apt repo, nginx, apt pins and apt-get
update against SiMa.ai's release repo); pib then lists sbp's packages. The check passes only when
the image's own sbp, from the commit deps/artifacts.json pins, lists them (OWN): an image without
sbp (NOT_YET, which pib prints only after the set-up passed) or a listing from PIB_PKGBUILD_SRC
fails it.
"pib package --help" would prove nothing: it skips the set-up.
"""
import json
from pathlib import Path
import subprocess
import sys

NOT_YET = 'this image does not carry sbp yet'  # sbp.source_tree(), after the set-up
# What sbp.cmd_package prints first for --list, from the SOURCE that deps/fetch-artifacts.py --sbp writes
PIN = json.loads((Path(__file__).resolve().parents[1] / 'deps/artifacts.json').read_text())['upstream']
OWN = f"pib: sbp and its package configs: this image's, from {PIN['repository']} @ {PIN['commit']}"


def check(launcher):
    r = subprocess.run([*launcher, 'package', '--list'], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode == 0 and OWN in r.stdout.splitlines():
        print("pib package started: set-up passed, the image's own sbp listed its packages")
        return 0
    if r.returncode == 0:
        print(f"::error::pib package listed packages, but not with the image's own sbp: expected '{OWN}'",
              file=sys.stderr)
        return 1
    if r.returncode == 1 and NOT_YET in r.stderr:
        print('::error::pib package set-up passed, but the image carries no sbp: deps/artifacts.json '
              'pins a commit with pkgbuild/ and configs/packages/', file=sys.stderr)
        return 1
    print(f'::error::pib package did not start (exit {r.returncode})', file=sys.stderr)
    return 1


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(check(sys.argv[1:]))
