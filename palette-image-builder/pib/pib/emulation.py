"""Enable this image's ARM64 emulator in the Docker host kernel when needed."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys


def ready(entry):
    try:
        text = entry.read_text()
    except FileNotFoundError:
        return False
    return text.startswith('enabled\n') and any(
        line.startswith('flags:') and 'F' in line.partition(':')[2] for line in text.splitlines())


def ensure_arm64(architecture=None, root=Path('/proc/sys/fs/binfmt_misc'),
                 config=Path('/usr/lib/binfmt.d/qemu-aarch64.conf'),
                 lock=Path('/dev/.pib-binfmt.lock')):
    architecture = architecture or subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
    if architecture == 'arm64':
        return
    if architecture != 'amd64':
        raise RuntimeError(f'unsupported builder architecture: {architecture}')
    if not (root / 'register').exists():
        subprocess.run(['mount', '-t', 'binfmt_misc', 'binfmt_misc', str(root)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    entry = root / 'qemu-aarch64'
    # The Docker-host /dev mount supplies a shared lock for simultaneous PIB starts.
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if ready(entry):
            return
        registration = next((line for line in config.read_text().splitlines()
                             if line.startswith(':qemu-aarch64:')), None)
        if not registration:
            raise RuntimeError('packaged ARM64 emulator registration is missing')
        fields = registration.split(':')
        if len(fields) != 8 or 'F' not in fields[7] or not os.access(fields[6], os.X_OK):
            raise RuntimeError('packaged ARM64 emulator must be executable and use fix_binary')
        print('pib: enabling packaged ARM64 emulation in the Docker host kernel', flush=True)
        if entry.exists():
            entry.write_text('-1\n')
        (root / 'register').write_text(registration + '\n')
        if not ready(entry):
            raise RuntimeError('Docker host did not enable the ARM64 interpreter')


if __name__ == '__main__':
    try:
        ensure_arm64()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f'pib: cannot enable ARM64 execution: {error}. '
                 'Use the PIB launcher with a Linux Docker host that permits privileged binfmt access.')
