#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "validate-debian-mirror.py"
SPEC = importlib.util.spec_from_file_location("debian_mirror_validator", VALIDATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DebianMirrorValidatorTest(unittest.TestCase):
    def create_repository(self, root: Path, checksum: str | None = None) -> Path:
        repository = root / "repository"
        package = repository / "pool" / "non-free" / "h" / "hello" / "hello.deb"
        package.parent.mkdir(parents=True)
        package.write_bytes(b"package bytes")
        digest = checksum or hashlib.sha256(package.read_bytes()).hexdigest()
        record = (
            "Package: hello\n"
            "Version: 1.0\n"
            "Architecture: amd64\n"
            "Filename: pool/non-free/h/hello/hello.deb\n"
            f"Size: {package.stat().st_size}\n"
            f"SHA256: {digest}\n\n"
        )
        index = repository / "dists" / "bookworm" / "non-free" / "binary-amd64" / "Packages.gz"
        index.parent.mkdir(parents=True)
        with gzip.open(index, "wt", encoding="utf-8") as package_index:
            package_index.write(record)
        (repository / "dists" / "bookworm" / "InRelease").write_text("signed metadata\n")
        return repository

    def test_validates_indexed_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.validate_repository(
                self.create_repository(Path(directory)),
                "bookworm",
                "non-free",
                ["amd64"],
                1,
            )
        self.assertEqual(result["package_count"], 1)
        self.assertEqual(result["total_bytes"], len(b"package bytes"))
        self.assertEqual(result["packages"][0]["version"], "1.0")

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self.create_repository(Path(directory), checksum="0" * 64)
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                MODULE.validate_repository(repository, "bookworm", "non-free", ["amd64"], 1)


if __name__ == "__main__":
    unittest.main()
