"""Offline per-user installation of the image-bundled extension."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install-neat-vscode-extension.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class BundledExtensionTest(unittest.TestCase):
    def test_copy_register_repeat_and_upgrade_preserves_other_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed, extensions = root / 'seed', root / 'alice/extensions'
            seed.mkdir()
            (seed / 'package.json').write_text(json.dumps({'publisher': 'sima-neat', 'name': 'sima-neat', 'version': '0.0.1'}))
            (seed / 'extension.js').write_text('first revision')
            other = extensions / 'other.extension-1.0.0'
            other.mkdir(parents=True)
            (other / 'package.json').write_text(json.dumps({'publisher': 'other', 'name': 'extension', 'version': '1.0.0'}))
            installer.install(seed, extensions)
            profile = extensions / 'extensions.json'
            first = json.loads(profile.read_text())
            installer.install(seed, extensions)
            self.assertEqual(first, json.loads(profile.read_text()))
            self.assertEqual(len(first), 2)
            neat = next(entry for entry in first if entry['identifier']['id'] == 'sima-neat.sima-neat')
            self.assertEqual((Path(neat['location']['path']) / 'extension.js').read_text(), 'first revision')
            (seed / 'extension.js').write_text('second revision')
            installer.install(seed, extensions)
            updated = json.loads(profile.read_text())
            self.assertEqual(len(updated), 2)
            self.assertIn(next(entry for entry in first if entry['identifier']['id'] == 'other.extension'), updated)
            neat = next(entry for entry in updated if entry['identifier']['id'] == 'sima-neat.sima-neat')
            self.assertEqual((Path(neat['location']['path']) / 'extension.js').read_text(), 'second revision')
            profile.write_text('broken profile')
            with self.assertRaises(ValueError):
                installer.install(seed, extensions)
            self.assertEqual(profile.read_text(), 'broken profile')


if __name__ == '__main__':
    unittest.main()
