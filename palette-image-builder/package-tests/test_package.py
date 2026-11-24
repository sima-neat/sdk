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
SBP_IMAGE = 'ghcr.io/sima-neat/palette-image-builder@sha256:' + 'b' * 64  # its pib-sbp variant


def launcher_module(path):
    """The installed launcher (a script without .py) as a module."""
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader('installed_pib', str(path))
    spec = importlib.util.spec_from_loader('installed_pib', loader)
    loaded = importlib.util.module_from_spec(spec)
    loader.exec_module(loaded)
    return loaded


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

    def test_the_sbp_image_is_bound_but_not_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'pib'
            metadata = builder.prepare(out, IMAGE.replace('ghcr.io/', 'ghcr:'), 'develop', 'commit',
                                       SBP_IMAGE.replace('ghcr.io/', 'ghcr:'))
            options = f'--image {IMAGE} --sbp-image {SBP_IMAGE}'
            self.assertEqual(metadata['installation']['script'],
                             f'python3 ./install_pib.py {options} || python ./install_pib.py {options}')
            self.assertEqual(metadata['resources'], ['install_pib.py', IMAGE.replace('ghcr.io/', 'ghcr:')],
                             'sima-cli downloads only the PIB image; Docker pulls pib-sbp on first use')
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, 'sbp-image-resource'):
            builder.prepare(Path(tmp) / 'pib', IMAGE.replace('ghcr.io/', 'ghcr:'), 'develop', 'commit', 'docker.io/x')

    def test_installed_launcher_finds_its_sbp_image(self):
        source = (ROOT / 'host/pib').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            for sbp, want in ((SBP_IMAGE, SBP_IMAGE), (None, None)):
                directory = Path(tmp) / str(bool(sbp))
                with patch.object(installer.subprocess, 'check_output', side_effect=['linux\n', source]):
                    path = installer.install_launcher(IMAGE, directory, docker='docker', windows=False, sbp_image=sbp)
                pib = launcher_module(path)
                self.assertEqual(pib.DEFAULT_IMAGE, IMAGE)
                if want:
                    self.assertEqual(pib.sbp_image({}), want)
                else:  # an older package: the digest names no pib-sbp image
                    with self.assertRaisesRegex(ValueError, 'set PIB_SBP_IMAGE'):
                        pib.sbp_image({})
                self.assertEqual(pib.sbp_image({'PIB_IMAGE': 'reg/x:7'}), 'reg/x:7-sbp', 'PIB_IMAGE wins')
                self.assertEqual(pib.sbp_image({'PIB_SBP_IMAGE': 'reg/y:1', 'PIB_IMAGE': 'reg/x:7'}), 'reg/y:1')
            # a launcher from before pib sbp has nowhere to bind it
            old = source.replace('DEFAULT_SBP_IMAGE = ""\n', '')
            with patch.object(installer.subprocess, 'check_output', side_effect=['linux\n', old]), \
                    self.assertRaisesRegex(RuntimeError, 'without pib sbp support'):
                installer.install_launcher(IMAGE, Path(tmp) / 'old', docker='docker', windows=False, sbp_image=SBP_IMAGE)
        with patch.object(sys, 'argv', ['install_pib.py', '--image', IMAGE, '--sbp-image', SBP_IMAGE, '--no-path']), \
                patch.object(installer, 'install_launcher', return_value=Path('pib')) as install, \
                patch.object(installer.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        self.assertEqual(install.call_args.kwargs['sbp_image'], SBP_IMAGE)

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

    def test_failed_host_check_warns_after_successful_installation(self):
        with patch.object(sys, 'argv', ['install_pib.py', '--image', IMAGE, '--no-path']), \
                patch.object(installer, 'install_launcher', return_value=Path('pib')), \
                patch.object(installer.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'doctor')), \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            installer.main()
        self.assertIn('Installed PIB:', output.getvalue())
        self.assertIn('PIB is installed', errors.getvalue())
        self.assertIn('Run pib doctor from your image project', errors.getvalue())
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

    @unittest.skipIf(os.name == 'nt', 'POSIX Bash startup files')
    def test_fresh_bash_login_and_nonlogin_shells_find_pib(self):
        names = ('.bash_profile', '.bash_login', '.profile')
        cases = ((active, shell) for active in (None, *names) for shell in ('/bin/bash', '/bin/zsh'))
        for active, reported_shell in cases:
            with self.subTest(active=active, reported_shell=reported_shell), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                directory = home / "bin with 'quotes' [x]*"
                directory.mkdir()
                launcher = directory / 'pib'
                launcher.write_text('#!/bin/sh\nprintf "installed\\n"\n')
                launcher.chmod(0o755)
                if active:
                    # Keep lower-priority profiles to detect accidental shadowing.
                    for name in names[names.index(active):]:
                        (home / name).write_text(f'export PIB_LOGIN_PROFILE={name}\n'
                            'if [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n')
                with patch.object(installer.Path, 'home', return_value=home), \
                        patch.dict(os.environ, {'SHELL': reported_shell}):
                    installer.add_to_path(directory)
                    first = {path.name: path.read_text() for path in home.iterdir() if path.is_file()}
                    installer.add_to_path(directory)
                    self.assertEqual(first, {path.name: path.read_text() for path in home.iterdir() if path.is_file()})
                selected = active or '.bash_profile'
                self.assertIn('# Palette Image Builder', (home / selected).read_text())
                if active:
                    self.assertTrue((home / active).read_text().startswith(f'export PIB_LOGIN_PROFILE={active}\n'))
                    for name in names[:names.index(active)]:
                        self.assertFalse((home / name).exists(), f'{name} would hide {active}')
                    for name in names[names.index(active) + 1:]:
                        self.assertNotIn('# Palette Image Builder', (home / name).read_text())
                env = {**os.environ, 'HOME': str(home), 'PATH': '/usr/bin:/bin', 'SHELL': reported_shell}
                for name in ('BASH_ENV', 'ENV', 'PIB_LOGIN_PROFILE'):
                    env.pop(name, None)
                command = 'printf "%s\\n" "${PIB_LOGIN_PROFILE:-none}" "$(command -v pib)" "$PATH"; pib'
                for flags in (['--login', '-ic'], ['--noprofile', '-ic']):
                    result = subprocess.run(['/bin/bash', *flags, command], env=env,
                                            capture_output=True, text=True, check=True)
                    profile, executable, search_path, output = result.stdout.splitlines()
                    self.assertEqual(profile, (active or 'none') if '--login' in flags else 'none')
                    self.assertEqual(executable, str(launcher.resolve()))
                    self.assertEqual(search_path.split(':').count(str(directory.resolve())), 1)
                    self.assertEqual(output, 'installed')

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
