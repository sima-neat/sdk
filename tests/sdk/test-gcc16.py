"""Test SDK provisioning refusals without downloading or building GCC."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('install_sdk_gcc16', ROOT / 'scripts/install-gcc16.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class SDKGCC16Tests(unittest.TestCase):
    def test_vendored_tool_is_exact_and_pinned(self):
        module, source = install.load_installer(ROOT / 'scripts/vendor/gcc16')
        self.assertEqual(module.VERSION, '16.2.0')
        self.assertEqual(len(source['commit']), 40)
        self.assertEqual(source['license'], 'Apache-2.0')

    def test_modified_tool_is_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'ensure_gcc16.py').write_text('raise RuntimeError("must not execute")')
            (root / 'source.json').write_text(json.dumps({'sha256': '0' * 64}))
            with self.assertRaisesRegex(ValueError, 'differs'):
                install.load_installer(root)

    def test_existing_compiler_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            root = cache / '16.2.0-fixture'
            root.mkdir()
            installer = SimpleNamespace(VERSION='16.2.0', ensure=lambda *a, **kw: root)
            with patch.object(install, 'load_installer', return_value=(installer, {})):
                result = install.install(cache, cache, cache, 4)
                self.assertEqual((cache / 'aarch64').resolve(), root)
                self.assertEqual(result['prefix'], str(cache / 'aarch64'))
                install.install(cache, cache, cache, 4)  # Idempotent same-prefix image layer.
                (cache / 'aarch64').unlink()
                (cache / 'aarch64').mkdir()
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    install.install(cache, cache, cache, 4)

    def test_image_provisions_after_sysroot_without_default_compiler_change(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        self.assertLess(dockerfile.index('setup-sdk-sysroot.sh "$(cat'),
                        dockerfile.index('RUN python3 /usr/local/bin/install-gcc16.py'))
        self.assertIn('ENV SIMA_GCC16_ROOT=/opt/toolchain/gcc16/aarch64', dockerfile)
        wrapper = (ROOT / 'scripts/install-gcc16.py').read_text()
        self.assertNotIn('update-alternatives', wrapper)


if __name__ == '__main__':
    unittest.main()
