"""Verify Pages assembly preserves the production and preview boundaries."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('publication', Path(__file__).with_name('assemble-publication.py'))
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


class Publication(unittest.TestCase):
    def test_combined_site_preserves_main_and_preview_and_owns_one_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main, develop, output = (root / name for name in ('main', 'develop', 'output'))
            for source, marker in ((main, 'released'), (develop, 'unreleased')):
                source.mkdir()
                (source / 'index.html').write_text(marker)
                (source / 'CNAME').write_text('sdk.neat.sima.ai')
            publication.assemble(main, develop, output)
            self.assertEqual((output / 'index.html').read_text(), 'released')
            self.assertEqual((output / 'staging-preview/index.html').read_text(), 'unreleased')
            self.assertFalse((output / 'staging-preview/CNAME').exists())
            self.assertIn('Disallow: /staging-preview/', (output / 'robots.txt').read_text())

    def test_develop_can_preview_before_main_site_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            develop = root / 'develop'
            develop.mkdir()
            (develop / 'index.html').write_text('unreleased instructions')
            publication.assemble(None, develop, root / 'output')
            self.assertNotIn('unreleased instructions', (root / 'output/index.html').read_text())
            self.assertEqual((root / 'output/staging-preview/index.html').read_text(), 'unreleased instructions')

    def test_production_cannot_supply_preview_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'main/staging-preview').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'must not contain'):
                publication.assemble(root / 'main', None, root / 'output')


if __name__ == '__main__':
    unittest.main()
