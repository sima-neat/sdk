import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pib import emulation


class EmulationTests(unittest.TestCase):
    def test_arm64_needs_no_kernel_registration(self):
        with patch.object(Path, 'open', side_effect=AssertionError('no registration on native ARM')):
            emulation.ensure_arm64('arm64')

    def test_existing_working_handler_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'register').touch()
            entry = root / 'qemu-aarch64'
            entry.write_text('enabled\ninterpreter /other/tool\nflags: POCF\n')
            emulation.ensure_arm64('amd64', root, root / 'missing-config', root / 'lock')
            self.assertEqual((root / 'register').read_text(), '')
            self.assertIn('/other/tool', entry.read_text())

    def test_missing_handler_registers_only_packaged_arm64(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            register = root / 'register'
            register.touch()
            other = root / 'qemu-riscv64'
            other.write_text('preserve other architectures')
            binary = root / 'qemu-aarch64'
            # Interpreter path differs from the registry entry directory in this fixture.
            binary = root / 'interpreter'
            binary.touch(); binary.chmod(0o755)
            config = root / 'aarch64.conf'
            registration = f':qemu-aarch64:M::magic:mask:{binary}:OPF'
            config.write_text(registration + '\n')
            original_write = Path.write_text
            def kernel_write(path, text, *args, **kwargs):
                result = original_write(path, text, *args, **kwargs)
                if path == register:
                    original_write(root / 'qemu-aarch64', 'enabled\nflags: OPF\n')
                return result
            with patch.object(Path, 'write_text', kernel_write):
                emulation.ensure_arm64('amd64', root, config, root / 'lock')
            self.assertEqual(register.read_text(), registration + '\n')
            self.assertEqual(other.read_text(), 'preserve other architectures')


if __name__ == '__main__':
    unittest.main()
