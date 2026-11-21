"""Inspect the signed SWU itself, rather than only its intermediate rootfs."""
import gzip
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

ws = Path('/workspace')
swus = list((ws / 'out').glob('*.swu'))
swus = [p for p in swus if not p.name.endswith('.unsigned.swu')]
assert len(swus) == 1, swus
swu = swus[0]
manifest = json.loads(swu.with_suffix('.manifest.json').read_text())
expected_spec = yaml.safe_load(Path('/example/image.yaml').read_text())
for field in ('version', 'release', 'vendor'):
    assert manifest[field] == expected_spec[field], (field, manifest[field])
pkg = next(p for p in manifest['packages'] if p['name'] == 'pib-example-app')
assert pkg['version'] == '1.0.0' and pkg['origin'] == 'customer', pkg
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    with swu.open('rb') as source:
        subprocess.run(['cpio', '-id', '--quiet', '--no-absolute-filenames', 'rootfs.ext4.gz'],
                       stdin=source, cwd=root, check=True)
    with gzip.open(root / 'rootfs.ext4.gz', 'rb') as source, (root / 'rootfs.ext4').open('wb') as target:
        shutil.copyfileobj(source, target)

    def read(path):
        return subprocess.run(['debugfs', '-R', f'cat {path}', str(root / 'rootfs.ext4')],
                              capture_output=True, text=True, check=True).stdout

    example = Path('/example')
    for path, expected in (
        ('/usr/bin/pib-example-app', (example / 'package-root/usr/bin/pib-example-app').read_text()),
        ('/etc/pib-example.conf', (example / 'overlay/etc/pib-example.conf').read_text()),
        ('/etc/systemd/system/pib-example.service', (example / 'overlay/etc/systemd/system/pib-example.service').read_text()),
        ('/etc/pib-example-build', 'PIB example post-install hook\n'),
    ):
        assert read(path) == expected, path
        print(f'PASS: signed rootfs matches example input {path}')
    link = subprocess.run(['debugfs', '-R',
        'stat /etc/systemd/system/multi-user.target.wants/pib-example.service',
        str(root / 'rootfs.ext4')], capture_output=True, text=True, check=True).stdout
    assert 'symlink' in link and 'pib-example.service' in link, link
    app = subprocess.run(['debugfs', '-R', 'stat /usr/bin/pib-example-app',
                          str(root / 'rootfs.ext4')], capture_output=True, text=True, check=True).stdout
    assert '0755' in app, app
    assert f'no-downgrading = "{expected_spec["version"]}"' in read('/etc/swupdate.cfg')
    assert f'VENDOR = {expected_spec["vendor"]}\n' in read('/etc/buildinfo')
    print('PASS: image spec version, release, vendor, and update policy reached the artifacts')
    assert read('/etc/swupdate/swupdate.crt') == (ws / 'keys/ca.crt').read_text()
    status = next(p for p in read('/var/lib/dpkg/status').split('\n\n')
                  if p.startswith('Package: pib-example-app\n'))
    assert 'Status: install ok installed' in status and 'Version: 1.0.0' in status
    print('PASS: customer package installed; rootfs trusts the test CA')
