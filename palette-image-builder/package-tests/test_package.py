"""Installer metadata and native host launchers; no live Docker or credentials needed."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


installer = module('install_pib', ROOT / 'tools/install_pib.py')
builder = module('prepare_package', ROOT / 'tools/prepare_package.py')
IMAGE = 'ghcr.io/sima-neat/palette-image-builder@sha256:' + 'a' * 64


class PackageTests(unittest.TestCase):
    def test_metadata_resource_and_installer_bind_to_same_multiarch_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'pib'
            metadata = builder.prepare(out, IMAGE.replace('ghcr.io/', 'ghcr:'), 'develop', 'commit')
            self.assertEqual(metadata['name'], 'pib')
            self.assertEqual(metadata['release'], 'commit')
            self.assertEqual(metadata['resources'], ['install_pib.py', IMAGE.replace('ghcr.io/', 'ghcr:')])
            self.assertEqual(metadata['installation']['script'], f'python3 ./install_pib.py --image {IMAGE} || python ./install_pib.py --image {IMAGE}')
            self.assertEqual(metadata['resources-checksum']['install_pib.py'],
                             hashlib.sha256((out / 'install_pib.py').read_bytes()).hexdigest())
            platforms = metadata['platforms']
            self.assertEqual({name for p in platforms for name in p['os']}, {'linux', 'mac', 'windows'})
            for p in platforms:
                self.assertEqual(set(p['arch']), {'amd64', 'arm64'})
            self.assertNotEqual(metadata['name'], 'sdk')

    def test_subfolder_resolution_uses_sdk_latest_without_retargeting_it(self):
        from sima_cli.vulcan.artifacts import parse_install_target, resolve_install_metadata_url
        self.assertEqual(parse_install_target('sdk/pib'), ('sdk', 'pib', 'main', 'latest'))
        class Client:
            def read_text(self, url):
                self.url = url
                return '0123456789ab\n'
        client = Client()
        result = resolve_install_metadata_url(environment='production', target='sdk/pib',
                     base_url='https://artifacts.example.invalid', client=client)
        self.assertEqual(client.url, 'https://artifacts.example.invalid/sdk/main/latest.tag')
        self.assertEqual(result.metadata_url, 'https://artifacts.example.invalid/sdk/main/0123456789ab/pib/metadata.json')

    def test_installer_uses_downloaded_image_and_creates_native_launcher(self):
        source = (ROOT / 'host/pib').read_text()
        for windows in (False, True):
            with self.subTest(windows=windows), tempfile.TemporaryDirectory(prefix='pib install ') as tmp:
                directory = Path(tmp) / 'bin with spaces'
                with patch.object(installer.subprocess, 'check_output', side_effect=['linux\n', source]) as docker:
                    path = installer.install_launcher(IMAGE, directory, docker='docker', windows=windows)
                self.assertIn('DEFAULT_IMAGE = ' + json.dumps(IMAGE), path.read_text())
                self.assertEqual(docker.call_args_list[1].args[0], ['docker', 'run', '--rm', '--pull', 'never',
                      '--entrypoint', 'cat', IMAGE, '/usr/local/share/pib/host/pib'])
                if windows:
                    cmd = (directory / 'pib.cmd').read_text()
                    self.assertIn('"%~dp0pib" %*', cmd)
                    self.assertIn('"' + sys.executable.replace('%', '%%') + '"', cmd)
                elif os.name != 'nt':
                    self.assertTrue(path.stat().st_mode & 0o111)
                subprocess.run([sys.executable, '-m', 'py_compile', str(path)], check=True)

    def test_installation_checks_host_without_requiring_updated_path(self):
        launcher = Path('bin with spaces') / 'pib'
        with patch.object(sys, 'argv', ['install_pib.py', '--image', IMAGE, '--no-path']), \
                patch.object(installer, 'install_launcher', return_value=launcher), \
                patch.object(installer.subprocess, 'run') as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            installer.main()
        run.assert_called_once_with([sys.executable, str(launcher), 'doctor'], check=True)
        self.assertIn('Docker host checks passed.', output.getvalue())

    def test_failed_host_check_does_not_report_successful_installation(self):
        with patch.object(sys, 'argv', ['install_pib.py', '--image', IMAGE, '--no-path']), \
                patch.object(installer, 'install_launcher', return_value=Path('pib')), \
                patch.object(installer.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'doctor')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, 'PIB installation failed'):
                installer.main()
        self.assertNotIn('Installed PIB:', output.getvalue())
        self.assertNotIn('checks passed', output.getvalue())

    @unittest.skipIf(os.name == 'nt', 'POSIX shell profile')
    def test_profile_update_preserves_content_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            profile = home / '.zshrc'
            profile.write_text('# existing user settings\n')
            with patch.object(installer.Path, 'home', return_value=home), patch.dict(os.environ, {'SHELL': '/bin/zsh'}):
                installer.add_to_path(home / 'bin with spaces')
                first = profile.read_text()
                installer.add_to_path(home / 'bin with spaces')
            self.assertTrue(first.startswith('# existing user settings\n'))
            self.assertEqual(first, profile.read_text())

    @unittest.skipUnless(os.name == 'nt', 'Windows user PATH')
    def test_windows_path_update_uses_user_registry(self):
        import winreg
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(winreg, 'CreateKey'), patch.object(winreg, 'QueryValueEx', return_value=('C:\\existing', winreg.REG_EXPAND_SZ)), \
                    patch.object(winreg, 'SetValueEx') as write, patch('ctypes.windll.user32.SendMessageTimeoutW'):
                installer.add_to_path(tmp)
            self.assertEqual(write.call_args.args[1:4], ('Path', 0, winreg.REG_EXPAND_SZ))
            self.assertTrue(write.call_args.args[4].endswith(';' + str(Path(tmp).resolve())))

    def test_bad_image_preserves_existing_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pib'
            path.write_text('existing launcher')
            with patch.object(installer.subprocess, 'check_output', side_effect=['linux\n', 'bad image content']):
                with self.assertRaisesRegex(RuntimeError, 'portable PIB launcher'):
                    installer.install_launcher(IMAGE, tmp, docker='docker')
            self.assertEqual(path.read_text(), 'existing launcher')
            with patch.object(installer.subprocess, 'check_output', return_value='windows\n'):
                with self.assertRaisesRegex(RuntimeError, 'Linux Docker engine'):
                    installer.install_launcher(IMAGE, tmp, docker='docker')


if __name__ == '__main__':
    unittest.main()
