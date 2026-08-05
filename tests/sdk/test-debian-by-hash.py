#!/usr/bin/env python3

import gzip
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "prepare-debian-by-hash.py"
SPEC = importlib.util.spec_from_file_location("prepare_debian_by_hash", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareDebianByHashTests(unittest.TestCase):
    def make_distribution(self, root: Path, digest: str) -> tuple[Path, Path]:
        suite = root / "bookworm"
        index = suite / "non-free" / "binary-amd64" / "Packages.gz"
        index.parent.mkdir(parents=True)
        package_index = b"Package: example\nVersion: 1.0\nArchitecture: amd64\n\n"
        index.write_bytes(gzip.compress(package_index, mtime=0))
        package_digest = hashlib.sha256(package_index).hexdigest()
        missing_digest = hashlib.sha256(b"missing source index\n").hexdigest()
        (suite / "Release").write_text(
            "Origin: Test\n"
            "Architectures: amd64\n"
            "Components: non-free\n"
            "SHA256:\n"
            f" {package_digest} {len(package_index)} non-free/binary-amd64/Packages\n"
            f" {digest} {index.stat().st_size} non-free/binary-amd64/Packages.gz\n"
            f" {missing_digest} 21 non-free/source/Sources.gz\n",
            encoding="utf-8",
        )
        (suite / "InRelease").write_text("signed", encoding="utf-8")
        (suite / "Release.gpg").write_text("signature", encoding="utf-8")
        return suite, index

    def test_prepares_by_hash_and_unsigned_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_index = b"Package: example\nVersion: 1.0\nArchitecture: amd64\n\n"
            digest = hashlib.sha256(gzip.compress(package_index, mtime=0)).hexdigest()
            suite, index = self.make_distribution(root, digest)

            count, total_bytes = MODULE.prepare_distribution(root, "bookworm")

            release = (suite / "Release").read_text(encoding="utf-8")
            self.assertIn("Acquire-By-Hash: yes\n", release)
            self.assertNotIn("non-free/source/Sources.gz", release)
            self.assertFalse((suite / "InRelease").exists())
            self.assertFalse((suite / "Release.gpg").exists())
            uncompressed = index.with_name("Packages")
            self.assertEqual(uncompressed.read_bytes(), package_index)
            by_hash = index.parent / "by-hash" / "SHA256" / digest
            self.assertEqual(by_hash.read_bytes(), index.read_bytes())
            uncompressed_digest = hashlib.sha256(package_index).hexdigest()
            uncompressed_by_hash = (
                index.parent / "by-hash" / "SHA256" / uncompressed_digest
            )
            self.assertEqual(uncompressed_by_hash.read_bytes(), package_index)
            self.assertIn("non-free/binary-amd64/Packages\n", release)
            self.assertEqual(count, 2)
            self.assertEqual(total_bytes, index.stat().st_size + len(package_index))

    def test_rejects_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_distribution(root, "0" * 64)
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                MODULE.prepare_distribution(root, "bookworm")


if __name__ == "__main__":
    unittest.main()
