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
            self.assertEqual(c['version'], branch.replace('/', '_') + '-' + 'a' * 7)
            self.assertIn(c['repository'] + ':latest', c['promotion_tags'])
            self.assertIn('ghcr.io/sima-neat/palette-image-builder:' + image_config.slug(branch), c['promotion_tags'])
            # pib sbp's image next to each tag, as the launcher derives it from PIB_IMAGE
            self.assertEqual(c['sbp_promotion_tags'].splitlines(),
                             [t + '-sbp' for t in c['promotion_tags'].splitlines()])
            self.assertEqual(c['sbp_staged'], c['staged'] + '-sbp')
        # canonical:develop-sbp is develop's pib-sbp alias, so branch develop-sbp gets no canonical alias
        c = self.config('refs/heads/develop-sbp')
        self.assertEqual(c['promotion_tags'].splitlines(), ['ghcr.io/sima-neat/palette-image-builder-develop-sbp:latest'])
        self.assertNotIn('ghcr.io/sima-neat/palette-image-builder:develop-sbp', c['promotion_tags'] + c['sbp_promotion_tags'])

    def test_release_aliases_and_invalid_tags(self):
        for tag in ('v3.0.0', 'v3.0.0.2'):
            c = self.config('refs/tags/' + tag)
            self.assertEqual(c['repository'], 'ghcr.io/sima-neat/palette-image-builder')
            self.assertEqual(c['version'], tag)
            self.assertEqual(c['promotion_tags'].splitlines(), [c['repository'] + ':' + tag, c['repository'] + ':v3.0-latest'])
            self.assertNotIn(':latest', c['promotion_tags'])
            self.assertEqual(c['sbp_promotion_tags'].splitlines(),
                             [c['repository'] + ':' + tag + '-sbp', c['repository'] + ':v3.0-latest-sbp'])
        with self.assertRaises(ValueError):
            self.config('refs/tags/v3.0.0-bad')

    def test_pull_requests_never_publish(self):
        c = self.config('refs/pull/42/merge', event='pull_request', head_ref='codex/pib')
        self.assertEqual(c['publish'], 'false')
        self.assertEqual(c['version'], 'codex_pib-' + 'a' * 7)
        self.assertTrue(c['repository'].endswith('-codex-pib'))


class BuildIdentity(unittest.TestCase):
    def test_embedded_identity_and_unbuilt_source_fallback(self):
        from pib import build_version
        with tempfile.TemporaryDirectory() as tmp:
            version_file = Path(tmp) / 'pib-version'
            self.assertEqual(build_version(version_file), 'unknown-nogit')
            for expected in ('develop-abc1234', 'codex_feature-abc1234', 'v3.0.0.2'):
                version_file.write_text(expected + '\n')
                self.assertEqual(build_version(version_file), expected)


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
                Path('out/elxr-minimal-modalix-3.0.0.2-dev-agate-arm64.swu').touch()
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

    def test_duplicate_package_versions_name_both_files_before_repo_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            debs = root / cli.DEBS
            debs.mkdir()
            for filename in ('app-1.deb', 'app-2.deb'):
                (debs / filename).touch()
            def metadata(cmd):
                version = '1' if Path(cmd[2]).name == 'app-1.deb' else '2'
                return f'Package: my-app\nVersion: {version}\nArchitecture: all\n'
            with patch.object(cli, 'run', side_effect=metadata), patch.object(cli, 'check_deb_signature'):
                for invoke in (lambda: cli.check_unique_debs(sorted(debs.glob('*.deb'))),
                               lambda: cli.check_debs(root, {'target': 'modalix', 'debs': {'key': 'key'}})):
                    with self.assertRaisesRegex(SystemExit, r'duplicate custom package my-app: app-1.deb \(1\) and app-2.deb \(2\)'):
                        invoke()

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

    def test_sbp_comes_from_the_pinned_commit_when_it_carries_it(self):
        """fetch_sbp, the work of deps/fetch-artifacts.py --sbp: from a commit with sbp and its package
        configs, just those two (and a SOURCE line naming the commit); from one with neither,
        nothing; either one alone fails."""
        module_spec = importlib.util.spec_from_file_location('fetch_artifacts', ROOT / 'deps/fetch-artifacts.py')
        downloads = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(downloads)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / 'swsoc-simaai-elxr-doc'
            def git(*args):
                return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                                      text=True).stdout.strip()
            def commit(files):
                for rel, text in files.items():
                    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                    (repo / rel).write_text(text)
                git('add', '-A')
                git('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'x')
                return git('rev-parse', 'HEAD')
            repo.mkdir()
            git('init', '-q')
            git('config', 'uploadpack.allowFilter', 'true')  # the fetch is blob-filtered, as from GitHub
            board = commit({'RELEASE': '3.0.0\n', 'configs/images/image-palette-modalix.yaml': 'x\n',
                            'files/f': 'f\n'})
            half = commit({'pkgbuild/sbp/cli.py': '', 'pkgbuild/README.md': 'sbp\n'})
            whole = commit({'configs/packages/packages.yaml': '', 'configs/packages/kernel/linux.yaml': 'k\n'})
            git('rm', '-r', '-q', 'pkgbuild')
            alone = commit({})  # the package configs without sbp
            pin = lambda c: {'repository': repo.as_uri(), 'commit': c, 'paths': ['configs']}  # noqa: E731
            # only the https check is skipped: the rest is the real sparse fetch of one commit
            with patch.object(downloads, 'pinned', lambda s: (s['repository'], s['commit'])):
                self.assertFalse(downloads.fetch_sbp(pin(board), root / 'none'))
                self.assertFalse((root / 'none').exists())
                with self.assertRaisesRegex(ValueError, 'carries only part of sbp: it has no configs/packages/packages.yaml'):
                    downloads.fetch_sbp(pin(half), root / 'half')
                self.assertFalse((root / 'half').exists())
                with self.assertRaisesRegex(ValueError, 'carries only part of sbp: it has no pkgbuild/sbp/cli.py$'):
                    downloads.fetch_sbp(pin(alone), root / 'alone')
                self.assertFalse((root / 'alone').exists())
                self.assertTrue(downloads.fetch_sbp(pin(whole), root / 'sbp-src'))
                downloads.fetch_source(pin(whole), root / 'board')
            tree = root / 'sbp-src'
            self.assertEqual(sorted(str(f.relative_to(tree)) for f in tree.rglob('*') if f.is_file()),
                             ['SOURCE', 'configs/packages/kernel/linux.yaml', 'configs/packages/packages.yaml',
                              'pkgbuild/README.md', 'pkgbuild/sbp/cli.py'])
            self.assertEqual((tree / 'SOURCE').read_text(), f'{repo.as_uri()} {whole}\n')
            # the board inputs' configs/ holds configs/packages too: the Dockerfile leaves it out
            self.assertTrue((root / 'board/configs/packages/packages.yaml').is_file())
            for bad in ({'repository': 'http://example.invalid/x.git', 'commit': whole},
                        {'repository': 'https://example.invalid/x.git', 'commit': whole[:12]}):
                with self.assertRaisesRegex(ValueError, 'HTTPS repository and a full commit SHA'):
                    downloads.fetch_sbp(bad, root / 'bad')

    def test_fetch_artifacts_takes_one_mode_at_a_time(self):
        """deps/fetch-artifacts.py takes --sbp DIR alone, or --destination, --release and --codename
        together: a mix, an empty --sbp or a missing option stops before anything is fetched."""
        for args, error in (
                (['--sbp', '/nonexistent/sbp', '--release', '3.0.0'], '--sbp takes a directory and no other option'),
                (['--sbp', ''], '--sbp takes a directory and no other option'),
                (['--sbp', '', '--destination', '/nonexistent/d', '--release', '3.0.0', '--codename', 'agate'],
                 '--sbp takes a directory and no other option'),
                (['--destination', '/nonexistent/d', '--release', '3.0.0'], 'required: --codename (or --sbp DIR alone)'),
                ([], 'required: --destination, --release, --codename (or --sbp DIR alone)')):
            r = subprocess.run([sys.executable, str(ROOT / 'deps/fetch-artifacts.py'), *args],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, (args, r.stderr))
            self.assertIn(error, r.stderr, args)
            self.assertEqual(r.stdout, '', 'nothing was fetched')

    def test_no_wheels_or_binary_archives_in_builder_sources(self):
        self.assertEqual(list(ROOT.rglob('*.whl')), [])
        self.assertEqual(list(ROOT.rglob('*.tar.gz')), [])


if __name__ == '__main__':
    unittest.main()
