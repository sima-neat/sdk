#!/usr/bin/env python3
"""Exercise Agate publication with local substitutes for network services."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
VERSION = "3.0.0~git202609090513.9e68a68-1218"

# Real validation, index preparation, inventory comparison and reporting run.
# Only downloads, AWS and Linux host utilities are replaced.
MOCK = r'''
import json, os, shutil, sys
from pathlib import Path
root = Path(os.environ["MOCK_ROOT"])
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name in ("flock", "getent"):
    sys.exit(0)
if name == "curl":
    assert args[-1] == "http://sw-web.eng.sima.ai/deb/daily/dists/agate/InRelease"
    shutil.copyfile(root / "fixture/dists/agate/InRelease", args[args.index("--output") + 1])
elif name == "apt-mirror2":
    config = Path(args[0]).read_text()
    assert "deb [ arch=arm64 by-hash=no ] http://sw-web.eng.sima.ai/deb/daily agate non-free" in config
    assert f"set mirror_path {root}/work/agate\n" in config
    shutil.copytree(root / "fixture", root / "work/agate/repository", dirs_exist_ok=True)
elif name == "aws":
    def local(value):
        if value.startswith("s3://bucket/"):
            return root / "s3" / value.removeprefix("s3://bucket/")
        return Path(value)
    if args[:2] == ["s3", "cp"]:
        src, dst = map(local, args[2:4])
        if not src.exists(): sys.exit(1)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if "--metadata" in args:
            metadata = dict(x.split("=", 1) for x in args[args.index("--metadata") + 1].split(","))
            dst.with_suffix(".metadata").write_text(json.dumps({"Metadata": metadata}))
    elif args[:2] == ["s3api", "head-object"]:
        path = root / "s3" / args[args.index("--key") + 1]
        if not path.exists(): sys.exit(1)
        metadata = path.with_suffix(".metadata")
        print(metadata.read_text() if metadata.exists() else "{}")
    elif args[:2] == ["s3", "rm"]:
        local(args[2]).unlink(missing_ok=True)
    elif args[:2] not in (["s3", "sync"], ["cloudfront", "create-invalidation"]):
        raise AssertionError(args)
'''


class MirrorSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        binaries = self.root / "bin"
        binaries.mkdir()
        for name in ("curl", "apt-mirror2", "aws", "getent", "flock"):
            path = binaries / name
            path.write_text(f"#!{sys.executable}\n" + MOCK)
            path.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "MOCK_ROOT": str(self.root),
            "VULCAN_DEBIAN_MIRROR_BUCKET": "bucket",
            "VULCAN_DEBIAN_MIRROR_KMS_KEY_ID": "test-key",
            "VULCAN_DEBIAN_MIRROR_CLOUDFRONT_DISTRIBUTION_ID": "test-distribution",
            "DEBIAN_MIRROR_REPORT_DIR": str(self.root / "report"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
        }
        package = self.root / "fixture/pool/non-free/p/palette.deb"
        package.parent.mkdir(parents=True)
        package.write_bytes(b"test package")
        record = (
            f"Package: simaai-palette-modalix\nVersion: {VERSION}\n"
            "Architecture: all\nFilename: pool/non-free/p/palette.deb\n"
            f"Size: {package.stat().st_size}\n"
            f"SHA256: {hashlib.sha256(package.read_bytes()).hexdigest()}\n\n"
        ).encode()
        suite = self.root / "fixture/dists/agate"
        index = suite / "non-free/binary-arm64/Packages.gz"
        index.parent.mkdir(parents=True)
        index.write_bytes(gzip.compress(record, mtime=0))
        release = "Codename: agate\nDate: Wed, 09 Sep 2026 06:45:35 UTC\nArchitectures: arm64\nComponents: non-free\nSHA256:\n"
        for filename, data in [("Packages", record), ("Packages.gz", index.read_bytes())]:
            release += f" {hashlib.sha256(data).hexdigest()} {len(data)} non-free/binary-arm64/{filename}\n"
        for name in ("Release", "InRelease"):
            (suite / name).write_text(release)
        # Old publication and cache must never become Agate's baseline or uploads.
        old = self.root / "s3/pre-release/.mirror/publication.json"
        old.parent.mkdir(parents=True)
        old.write_text('{"source":{"inrelease_sha256":"old-bookworm"}}')
        old_cache = self.root / "work/repository/dists/bookworm/Release"
        old_cache.parent.mkdir(parents=True)
        old_cache.write_text("old bookworm metadata")

    def run_sync(self, *extra):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/sync-debian-pre-release-mirror.sh"),
             "--work-root", str(self.root / "work"), "--minimum-free-gib", "0", *extra],
            env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((self.root / "report/mirror-sync-result.json").read_text())

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]

    def test_publishes_separate_daily_suite_and_then_skips_unchanged(self):
        report = self.run_sync("--publish")
        self.assertEqual(report["result"], "Published")
        self.assertEqual(report["source"]["url"], "http://sw-web.eng.sima.ai/deb/daily")
        self.assertEqual(report["source"]["suite"], "agate")
        self.assertEqual(report["platform"]["versions"], [VERSION])
        self.assertFalse(report["changes"]["baseline_available"])
        release = self.root / "s3/daily/dists/agate/Release"
        self.assertIn("Acquire-By-Hash: yes", release.read_text())
        calls = self.calls()
        self.assertFalse(any("pre-release" in arg or "bookworm" in arg for call in calls for arg in call))
        seeds = [c for c in calls if c[:3] == ["aws", "s3", "sync"] and c[4] == "s3://bucket/daily/dists/"]
        self.assertEqual(len(seeds), 2, "First publication must seed ordinary and by-hash indexes")
        self.assertTrue(any(c[4] == "s3://bucket/daily/pool/" for c in calls if c[:3] == ["aws", "s3", "sync"]))
        (self.root / "calls").write_text("")
        self.assertEqual(self.run_sync("--publish")["result"], "No change")
        self.assertFalse(any(c[0] == "apt-mirror2" or c[:3] == ["aws", "s3", "sync"] for c in self.calls()))

    def test_validation_only_does_not_publish(self):
        report = self.run_sync()
        self.assertEqual(report["result"], "Validated only")
        self.assertEqual(report["platform"]["versions"], [VERSION])
        self.assertFalse((self.root / "s3/daily").exists())
        self.assertFalse(any(c[:3] == ["aws", "s3", "sync"] for c in self.calls()))


if __name__ == "__main__":
    unittest.main()
