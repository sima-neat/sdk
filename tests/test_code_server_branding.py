"""Validate favicon replacement and fail-before-write behavior for image builds."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / 'vscode-extension/media/neat-logo.png'
TEMPLATES = ['src/browser/pages/login.html', 'src/browser/pages/error.html',
             'lib/vscode/out/vs/code/browser/workbench/workbench.html']
HTML = '''<link rel="icon" href="{{BASE}}/_static/src/browser/media/favicon-dark-support.svg" />
<link rel="alternate icon" href="{{BASE}}/_static/src/browser/media/favicon.ico" type="image/x-icon" />
<link rel="apple-touch-icon" href="{{BASE}}/_static/src/browser/media/pwa-icon-192.png" />'''


class BrandingTest(unittest.TestCase):
    def test_brand_repeat_and_incompatible_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / 'src/browser/media'
            media.mkdir(parents=True)
            for name in TEMPLATES:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(HTML)
            command = [sys.executable, str(ROOT / 'tools/brand_code_server.py'), '--server-dir', str(root), '--icon', str(ICON)]
            subprocess.run(command, check=True, capture_output=True)
            expected = 'neat-favicon-' + hashlib.sha256(ICON.read_bytes()).hexdigest()[:12] + '.png'
            self.assertEqual((media / expected).read_bytes(), ICON.read_bytes())
            first = [(root / name).read_text() for name in TEMPLATES]
            for html in first:
                self.assertEqual(html.count(expected), 2)
                self.assertEqual(html.count('type="image/png"'), 2)
                self.assertIn('pwa-icon-192.png', html)
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(first, [(root / name).read_text() for name in TEMPLATES])
            (root / TEMPLATES[-1]).write_text('<html>upstream changed</html>')
            (root / TEMPLATES[0]).write_text(HTML)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Expected two favicon links', result.stderr)
            self.assertEqual((root / TEMPLATES[0]).read_text(), HTML)


if __name__ == '__main__':
    unittest.main()
