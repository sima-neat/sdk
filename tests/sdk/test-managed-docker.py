"""Run the remote dispatcher with managed paths redirected into a disposable fixture."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/devkit-container-remote.sh'


class ManagedDockerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.helper = self.root / 'helper'
        self.nfs = self.root / 'nfs'
        self.log = self.root / 'calls'
        self.remote = self.root / 'remote.sh'
        self.remote.write_text(SCRIPT.read_text().replace('/usr/local/bin/kerrigan-docker', str(self.helper)).replace('/usr/local/sbin/kerrigan-sdk-nfs', str(self.nfs)))
        self.helper.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n[ "$1" != status ] || exit "${HEALTH_EXIT:-0}"\n')
        self.helper.chmod(0o755)

    def run_remote(self, *args, **env):
        return subprocess.run(['bash', str(self.remote), *args], env={**os.environ, 'CALL_LOG': str(self.log), **env}, capture_output=True, text=True, timeout=10)

    def test_managed_setup_and_commands_use_helper_without_sudo(self):
        for args in [('setup', '192.0.2.1:5050'), ('docker-check',), ('managed-docker-check',), ('list',)]:
            result = self.run_remote(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.log.read_text().splitlines()
        self.assertIn('registry-setup 192.0.2.1:5050', lines)
        self.assertIn('docker ps -a', lines)

    def test_unhealthy_runtime_blocks_privileged_fallback(self):
        result = self.run_remote('setup', HEALTH_EXIT='1')
        self.assertEqual(result.returncode, 2)
        self.assertIn('device-bundle status', result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ['status'])

    def test_managed_without_docker_requests_bundle_not_installation(self):
        self.helper.unlink(); self.nfs.touch()
        result = self.run_remote('docker-check')
        self.assertEqual(result.returncode, 2)
        self.assertIn('device bundle', result.stderr)
        self.assertFalse(self.log.exists())

    def test_unmanaged_probe_retains_legacy_path(self):
        self.helper.unlink()
        self.assertEqual(self.run_remote('managed-docker-check').returncode, 42)


if __name__ == '__main__':
    unittest.main()
