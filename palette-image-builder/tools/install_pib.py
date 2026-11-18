#!/usr/bin/env python3
"""Install the launcher from the selected, already-downloaded PIB image."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


def atomic_write(path, text, mode=0o755):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(text)
            output.close()
            temp.chmod(mode)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def install_launcher(image, directory, docker=None, windows=None):
    docker = docker or shutil.which('docker')
    if not docker:
        raise RuntimeError('Docker is required. Install/start Docker and retry.')
    system = subprocess.check_output([docker, 'info', '--format', '{{.OSType}}'], text=True).strip()
    if system != 'linux':
        raise RuntimeError('PIB requires a Linux Docker engine. Select Linux containers and retry.')
    payload = subprocess.check_output([docker, 'run', '--rm', '--pull', 'never', '--entrypoint', 'cat', image,
                                       '/usr/local/share/pib/host/pib'], text=True)
    if not payload.startswith('#!/usr/bin/env python3\n'):
        raise RuntimeError('The selected image does not contain the portable PIB launcher.')
    payload, count = re.subn(r'^DEFAULT_IMAGE = .*$', 'DEFAULT_IMAGE = ' + json.dumps(image), payload, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError('The selected image has an unsupported PIB launcher format.')
    directory = Path(directory)
    launcher = directory / 'pib'
    atomic_write(launcher, payload)
    windows = os.name == 'nt' if windows is None else windows
    if windows:
        interpreter = sys.executable.replace('%', '%%')
        atomic_write(directory / 'pib.cmd', f'@echo off\n"{interpreter}" "%~dp0pib" %*\n')
    return launcher


def add_to_path(directory):
    directory = str(Path(directory).resolve())
    if os.name == 'nt':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            try:
                value, kind = winreg.QueryValueEx(key, 'Path')
            except FileNotFoundError:
                value, kind = '', winreg.REG_EXPAND_SZ
            if os.path.normcase(directory) not in [os.path.normcase(os.path.expandvars(p)) for p in value.split(';')]:
                winreg.SetValueEx(key, 'Path', 0, kind, value.rstrip(';') + ';' + directory)
        import ctypes
        from ctypes import wintypes
        broadcast = ctypes.windll.user32.SendMessageTimeoutW
        broadcast.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                              wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        result = ctypes.c_size_t()
        broadcast(0xFFFF, 0x001A, 0, 'Environment', 2, 1000, ctypes.byref(result))
    else:
        shell = Path(os.environ.get('SHELL', '/bin/bash')).name
        home = Path.home()
        if shell == 'bash':
            # Bash login shells read only the first readable file in this order.
            # Reuse it: creating .bash_profile could hide an existing .profile.
            login_profiles = [home / name for name in ('.bash_profile', '.bash_login', '.profile')]
            login_profile = next((path for path in login_profiles
                                  if path.is_file() and os.access(path, os.R_OK)), login_profiles[0])
            profiles = [home / '.bashrc', login_profile]
        else:
            profiles = [home / ('.zshrc' if shell == 'zsh' else '.profile')]
        line = f'export PATH={shlex.quote(directory)}:"$PATH"'
        # A login profile may source .bashrc; avoid adding the same PATH entry twice.
        block = ('\n# Palette Image Builder\ncase ":$PATH:" in\n'
                 f'    *:{shlex.quote(directory)}:*) ;;\n'
                 f'    *) {line} ;;\nesac\n')
        for profile in profiles:
            existing = profile.read_text() if profile.exists() else ''
            if block not in existing and line not in existing.splitlines():
                with profile.open('a') as output:
                    output.write(block)
    return directory not in os.environ.get('PATH', '').split(os.pathsep)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--bin-dir', type=Path)
    parser.add_argument('--no-path', action='store_true', help='do not update the user shell/Windows PATH')
    args = parser.parse_args()
    directory = args.bin_dir or (Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'SiMa/bin'
                                 if os.name == 'nt' else Path.home() / '.local/bin')
    try:
        launcher = install_launcher(args.image, directory)
        changed = False if args.no_path else add_to_path(directory)
        print('Checking the Docker host for image building...', flush=True)
        subprocess.run([sys.executable, str(launcher), 'doctor'], check=True)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f'PIB installation failed: {error}')
    print(f'Installed PIB: {launcher}')
    if changed:
        print('Open a new terminal to use the updated PATH.')
    print('Docker host checks passed. Run pib init my-image --flavor minimal to get started.')


if __name__ == '__main__':
    main()
