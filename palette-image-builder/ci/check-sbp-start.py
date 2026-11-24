#!/usr/bin/env python3
"""CI: start pib package through a launcher and check that its container set-up ran.

    check-sbp-start.py LAUNCHER...    e.g. python3 host/pib, or an installed pib

"pib package --list" runs sbp/setup.sh first (sbp's local apt repo, nginx, apt pins and apt-get
update against SiMa.ai's release repo); pib then looks for sbp. It lists sbp's packages once the
image carries sbp; until then it stops with a message pib prints only after the set-up passed.
"pib package --help" would prove nothing: it skips the set-up.
"""
import subprocess
import sys

NOT_YET = 'this image does not carry sbp yet'  # sbp.source_tree(), after the set-up


def check(launcher):
    r = subprocess.run([*launcher, 'package', '--list'], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode == 0:
        print('pib package started: set-up passed, sbp listed its packages')
        return 0
    if r.returncode == 1 and NOT_YET in r.stderr:
        print('pib package started: set-up passed (sbp itself is not in the image yet)')
        return 0
    print(f'::error::pib package did not start (exit {r.returncode})', file=sys.stderr)
    return 1


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(check(sys.argv[1:]))
