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
HTML = '''<head><link rel="icon" href="{{BASE}}/_static/src/browser/media/favicon-dark-support.svg" />
<link rel="alternate icon" href="{{BASE}}/_static/src/browser/media/favicon.ico" type="image/x-icon" />
<link rel="apple-touch-icon" href="{{BASE}}/_static/src/browser/media/pwa-icon-192.png" /></head>'''


class BrandingTest(unittest.TestCase):
    def test_brand_repeat_and_incompatible_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / 'src/browser/media'
            media.mkdir(parents=True)
            for name in TEMPLATES:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text((ROOT / "tests/fixtures/code-server-login.html").read_text() if name == TEMPLATES[0] else HTML)
            command = [sys.executable, str(ROOT / 'tools/brand_code_server.py'), '--server-dir', str(root), '--icon', str(ICON)]
            subprocess.run(command, check=True, capture_output=True)
            expected = 'neat-favicon-' + hashlib.sha256(ICON.read_bytes()).hexdigest()[:12] + '.png'
            self.assertEqual((media / expected).read_bytes(), ICON.read_bytes())
            first = [(root / name).read_text() for name in TEMPLATES]
            for index, html in enumerate(first):
                self.assertEqual(html.count(expected), 3 if index == 0 else 2)
                self.assertEqual(html.count('type="image/png"'), 2)
                self.assertIn('pwa-icon-192.png', html)
            self.assertIn('sima-cli sdk neat printenv CODE_SERVER_PASSWORD', first[0])
            self.assertIn('name="password"', first[0])
            self.assertIn('{{ERROR}}', first[0])
            self.assertIn('neat-workbench.css', first[-1])
            for font in (ICON.parent / 'fonts').glob('*.woff2'):
                self.assertEqual((media / font.name).read_bytes(), font.read_bytes())
            self.assertIn('font-family:Roboto', (media / 'neat-workbench.css').read_text())
            self.assertNotIn('{{PASSWORD_MSG}}', first[0])
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(first, [(root / name).read_text() for name in TEMPLATES])
            (root / TEMPLATES[-1]).write_text('<html>upstream changed</html>')
            (root / TEMPLATES[0]).write_text((ROOT / "tests/fixtures/code-server-login.html").read_text())
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Expected two favicon links', result.stderr)
            self.assertEqual((root / TEMPLATES[0]).read_text(), (ROOT / "tests/fixtures/code-server-login.html").read_text())


if __name__ == '__main__':
    unittest.main()
