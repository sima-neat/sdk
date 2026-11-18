"""Exercise gzip compatibility and cache verification against a real signed APT repository."""
import email.utils
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from pib.deb_cache import verified_copy

ROOT = Path(__file__).resolve().parents[1]


class Compression(unittest.TestCase):
    def test_parallel_output_is_readable_by_gnu_gzip_and_keeps_requested_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'payload'
            data = bytes(range(256)) * 4096
            source.write_bytes(data)
            wrapper = ROOT / 'runtime/gzip'
            compressed = subprocess.check_output(['python3', str(wrapper), '-9', '-n', '--rsyncable', '-c', str(source)])
            self.assertEqual(compressed[4:8], bytes(4))  # no timestamp
            self.assertFalse(compressed[3] & 8)  # no filename
            self.assertEqual(subprocess.check_output(['/usr/bin/gzip', '-dc'], input=compressed), data)
            subprocess.run(['python3', str(wrapper), '-1', '--keep', '-f', str(source)], check=True)
            self.assertTrue(source.is_file())
            self.assertEqual(subprocess.check_output(['/usr/bin/gzip', '-dc', str(source) + '.gz']), data)

    def test_corrupt_blob_cannot_replace_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / 'cache', Path(tmp) / 'archive'
            source.write_bytes(b'wrong')
            dest.write_bytes(b'existing')
            self.assertFalse(verified_copy(source, dest, hashlib.sha256(b'right').hexdigest(), 5))
            self.assertEqual(dest.read_bytes(), b'existing')


class DebianCache(unittest.TestCase):
    def test_cold_warm_corrupt_and_new_metadata(self):
        with tempfile.TemporaryDirectory(prefix='pib-cache-test-') as tmp:
            base = Path(tmp)
            repo, cache, gnupg = base / 'repo', base / 'cache', base / 'gnupg'
            gnupg.mkdir(mode=0o700)
            env = {**os.environ, 'GNUPGHOME': str(gnupg), 'PIB_DEB_CACHE_DIR': str(cache)}
            def run(*args, **kwargs):
                try:
                    return subprocess.run(args, env=env, check=True, capture_output=True, **kwargs)
                except subprocess.CalledProcessError as error:
                    error.add_note(str(error.stderr))
                    raise
            try:
                run('gpg', '--batch', '--pinentry-mode', 'loopback', '--passphrase', '',
                    '--quick-gen-key', 'PIB Cache Fixture', 'ed25519', 'sign', '0')
                repo.mkdir()
                key = repo / 'key.gpg'
                key.write_bytes(run('gpg', '--export').stdout)
                package = base / 'package'
                (package / 'DEBIAN').mkdir(parents=True)
                (package / 'DEBIAN/control').write_text(
                    'Package: pib-cache-fixture\nVersion: 1:1.0\nArchitecture: all\n'
                    'Maintainer: PIB Test <pib@example.invalid>\nDescription: cache fixture\n')
                payload = package / 'usr/share/pib-cache-fixture/value'
                payload.parent.mkdir(parents=True)
                pool = repo / 'pool'
                pool.mkdir()
                deb = pool / 'pib-cache-fixture_1.0_all.deb'
                indexes = repo / 'dists/fixture/main/binary-arm64'
                indexes.mkdir(parents=True)
                def publish(value):
                    payload.write_text(value)
                    run('dpkg-deb', '--root-owner-group', '--build', str(package), str(deb))
                    data = deb.read_bytes()
                    digest = hashlib.sha256(data).hexdigest()
                    packages = (package / 'DEBIAN/control').read_text() + (
                        f'Filename: pool/{deb.name}\nSize: {len(data)}\nSHA256: {digest}\n\n')
                    (indexes / 'Packages').write_text(packages)
                    contents = packages.encode()
                    release = repo / 'dists/fixture/Release'
                    release.write_text('Suite: fixture\nCodename: fixture\nArchitectures: arm64\n'
                        'Components: main\nDate: ' + email.utils.formatdate(usegmt=True) + '\nSHA256:\n '
                        + hashlib.sha256(contents).hexdigest() + f' {len(contents)} main/binary-arm64/Packages\n')
                    run('gpg', '--batch', '--yes', '--clearsign', '--output', str(release.parent / 'InRelease'), str(release))
                    return digest
                def bootstrap(number):
                    target = base / f'root-{number}'
                    result = run('/usr/local/bin/mmdebstrap', '--mode=chrootless', '--variant=extract',
                        '--skip=check/chrootless',  # extract-only fixture; no package scripts execute
                        '--architectures=arm64', '--include=pib-cache-fixture', 'fixture', str(target),
                        f'deb [signed-by={key}] copy:{repo} fixture main', text=True)
                    self.assertEqual((target / 'usr/share/pib-cache-fixture/value').read_text(), expected)
                    self.assertIn('skipping apt-get update because it was already run', result.stderr)
                    return result.stdout + result.stderr
                expected = 'first package\n'
                digest = publish(expected)
                cold = bootstrap(1)
                self.assertIn('cache restore: verified=0', cold)
                self.assertIn('cache save: verified=1', cold)
                blob = cache / f'{digest}.deb'
                self.assertTrue(blob.is_file())
                warm = bootstrap(2)
                self.assertIn('cache restore: verified=1', warm)
                # Same-size tampering must be rejected, not merely checked by filename/size.
                damaged = bytearray(blob.read_bytes())
                damaged[-1] ^= 1
                blob.write_bytes(damaged)
                repaired = bootstrap(3)
                self.assertIn('rejected=1', repaired)
                self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), digest)
                expected = 'new repository contents\n'
                newer = publish(expected)
                self.assertNotEqual(newer, digest)
                changed = bootstrap(4)
                self.assertIn('cache restore: verified=0', changed)
                # Authentication failures must stop bootstrap, even with an existing warm cache.
                release = repo / 'dists/fixture/InRelease'
                release.write_text(release.read_text().replace('Codename: fixture', 'Codename: altered'))
                with self.assertRaises(subprocess.CalledProcessError):
                    bootstrap(5)
            finally:
                subprocess.run(['gpgconf', '--homedir', str(gnupg), '--kill', 'all'], capture_output=True)


if __name__ == '__main__':
    unittest.main()
