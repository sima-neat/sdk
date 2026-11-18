"""Regression checks for the SDK port's user workflow and publishing boundaries."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pib'))
from pib import cli
spec = importlib.util.spec_from_file_location('image_config', ROOT / 'ci/image-config.py')
image_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_config)


class Publishing(unittest.TestCase):
    def config(self, ref, **kwargs):
        return image_config.configuration('SiMa-Neat', ref, 'a' * 40, **kwargs)

    def test_sdk_branch_repositories_and_aliases(self):
        for branch, package in (('main', 'palette-image-builder'),
                                ('develop', 'palette-image-builder-develop'),
                                ('release-3.0', 'palette-image-builder-release-3.0'),
                                ('codex/Add PIB', 'palette-image-builder-codex-add-pib')):
            c = self.config('refs/heads/' + branch)
            self.assertEqual(c['repository'], 'ghcr.io/sima-neat/' + package)
            self.assertIn(c['repository'] + ':latest', c['promotion_tags'])
            self.assertIn('ghcr.io/sima-neat/palette-image-builder:' + image_config.slug(branch), c['promotion_tags'])

    def test_release_aliases_and_invalid_tags(self):
        for tag in ('v3.0.0', 'v3.0.0.2'):
            c = self.config('refs/tags/' + tag)
            self.assertEqual(c['repository'], 'ghcr.io/sima-neat/palette-image-builder')
            self.assertEqual(c['promotion_tags'].splitlines(), [c['repository'] + ':' + tag, c['repository'] + ':v3.0-latest'])
            self.assertNotIn(':latest', c['promotion_tags'])
        with self.assertRaises(ValueError):
            self.config('refs/tags/v3.0.0-bad')

    def test_pull_requests_never_publish(self):
        c = self.config('refs/pull/42/merge', event='pull_request', head_ref='codex/pib')
        self.assertEqual(c['publish'], 'false')
        self.assertTrue(c['repository'].endswith('-codex-pib'))


class Workflow(unittest.TestCase):
    def test_build_sign_rejects_throwaway_mode_before_build(self):
        with self.assertRaisesRegex(SystemExit, '--sign cannot be combined with --dev'):
            cli.cmd_build(argparse.Namespace(sign=True, dev=True))

    def test_packaged_example_is_a_valid_complete_project_input(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(dir=str(Path(tmp) / 'project'), example='custom-image',
                                      flavor='palette', target='modalix', release=None, configs=None)
            with patch.object(cli, 'BAKED_CONFIGS', ROOT / 'configs'):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    cli.cmd_init(args)
            project = Path(args.dir)
            self.assertEqual((project / 'image.yaml').read_bytes(),
                             (ROOT / 'examples/custom-image/image.yaml').read_bytes())
            config = cli.load_config(project)
            self.assertEqual(config['release'], (ROOT / 'RELEASE').read_text().strip())
            self.assertEqual(config['packages']['add'], ['pib-example-app'])
            self.assertTrue((project / 'hooks/enable-example.sh').is_file())
            self.assertTrue((project / 'package-root/usr/bin/pib-example-app').stat().st_mode & 0o111)

    def test_verify_selects_current_version_and_adjacent_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            os.chdir(tmp)
            try:
                Path('out').mkdir()
                Path('image.yaml').write_text('base: minimal\ntarget: modalix\nversion: 3.0.0.2\nsigning: {ca: keys/test-ca.crt}\n')
                target = Path('out/elxr-minimal-modalix-3.0.0.2-agate-arm64.swu')
                target.touch()
                target.with_suffix('.manifest.json').touch()
                Path('out/elxr-minimal-modalix-3.0.0.1-agate-arm64.swu').touch()
                Path('out/elxr-minimal-modalix-3.0.0.2-agate-arm64.unsigned.swu').touch()
                args = argparse.Namespace(swu=None, ca=None, manifest=None)
                # Stop at archive reading: this checks input resolution without faking signatures.
                with patch.object(cli, 'read_swu', side_effect=RuntimeError('resolved')):
                    with self.assertRaisesRegex(RuntimeError, 'resolved'):
                        cli.cmd_verify(args)
                self.assertEqual(args.swu, str(target))
                self.assertEqual(args.ca, 'keys/test-ca.crt')
                self.assertEqual(args.manifest, str(target.with_suffix('.manifest.json')))
            finally:
                os.chdir(old)

    def test_copied_launcher_preserves_paths_and_limits_secret_mounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / 'bin'
            binary.mkdir()
            docker = binary / 'docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            docker.chmod(0o755)
            launcher = root / 'pib'
            launcher.write_bytes((ROOT / 'host/pib').read_bytes())
            launcher.chmod(0o755)
            key = root / 'signing key'
            key.write_text('private test data')
            env = {**os.environ, 'PATH': f'{binary}:{os.environ["PATH"]}',
                   'PIB_IMAGE': 'registry/branch:sha', 'SWU_SIGNING_KEY': str(key)}
            def invoke(*args):
                return subprocess.run([str(launcher), *args], cwd=root, env=env,
                                      capture_output=True, text=True, check=True).stdout.splitlines()
            args = invoke('build', '--sign')
            self.assertIn(f'{key}:/keys/SWU_SIGNING_KEY:ro', args)
            self.assertNotIn('private test data', args)
            self.assertIn('--privileged', args)
            self.assertEqual(args[-4:], ['registry/branch:sha', 'pib', 'build', '--sign'])
            args = invoke('verify')
            self.assertNotIn('--privileged', args)
            self.assertNotIn(f'{key}:/keys/SWU_SIGNING_KEY:ro', args)
            args = invoke('shell', '-c', 'echo hello')
            self.assertEqual(args[-4:], ['registry/branch:sha', 'bash', '-c', 'echo hello'])
            env['PIB_DEB_CACHE'] = str(root / 'cached downloads')
            args = invoke('build')
            mount = f'{root / "cached downloads"}:/var/cache/pib-debs'
            self.assertIn(mount, args)
            self.assertIn('PIB_DEB_CACHE_DIR=/var/cache/pib-debs', args)
            self.assertNotIn(mount, invoke('verify'))



class ArtifactDownloads(unittest.TestCase):
    def test_hash_checked_downloads_and_corruption_rejection(self):
        import hashlib
        import io
        import json
        module_spec = importlib.util.spec_from_file_location('fetch_artifacts', ROOT / 'deps/fetch-artifacts.py')
        downloads = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(downloads)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / 'artifacts.json'
            payload = b'pinned artifact contents'
            manifest.write_text(json.dumps({'platform_release': '3.0.0', 'artifacts': [{
                'filename': 'test.whl', 'url': 'https://example.invalid/commit/test.whl',
                'sha256': hashlib.sha256(payload).hexdigest(),
            }]}))
            with patch.object(downloads.urllib.request, 'urlopen', return_value=io.BytesIO(payload)):
                downloads.fetch(manifest, root / 'good', '3.0.0')
            self.assertEqual((root / 'good/test.whl').read_bytes(), payload)
            with patch.object(downloads.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt')):
                with self.assertRaisesRegex(ValueError, 'sha256 mismatch'):
                    downloads.fetch(manifest, root / 'bad', '3.0.0')
            self.assertEqual(list((root / 'bad').iterdir()), [])
            with self.assertRaisesRegex(ValueError, 'artifact release'):
                downloads.fetch(manifest, root / 'mismatched', '3.0.1')

    def test_upstream_inputs_use_one_full_commit(self):
        import json
        lock = json.loads((ROOT / 'deps/artifacts.json').read_text())
        self.assertRegex(lock['upstream']['commit'], r'^[0-9a-f]{40}$')
        self.assertEqual(lock['upstream']['paths'], ['configs', 'files', 'scripts'])
        for artifact in lock['artifacts']:
            self.assertIn('/' + lock['upstream']['commit'] + '/', artifact['url'])
            self.assertRegex(artifact['sha256'], r'^[0-9a-f]{64}$')

    def test_no_wheels_or_binary_archives_in_builder_sources(self):
        self.assertEqual(list(ROOT.rglob('*.whl')), [])
        self.assertEqual(list(ROOT.rglob('*.tar.gz')), [])


if __name__ == '__main__':
    unittest.main()
