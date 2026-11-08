#!/usr/bin/env python3
"""Exercise validation before component pins can reach a Docker shell."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("pins", ROOT / "scripts/sdk-component-pins.py")
pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pins)


class ComponentPinsTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"code-server": {
            "version": "4.123.1",
            "sha256": {"amd64": "a" * 64, "arm64": "b" * 64},
        }}

    def test_exact_version_and_both_architectures(self):
        self.assertEqual(pins.assignments(self.manifest).splitlines(), [
            "CODE_SERVER_VERSION=4.123.1",
            "CODE_SERVER_SHA256_AMD64=" + "a" * 64,
            "CODE_SERVER_SHA256_ARM64=" + "b" * 64,
        ])

    def test_rejects_mutable_wrong_component_and_shell_versions(self):
        for version in ("latest", "26.1007.21434", "4.123.1;id", "4.123.1\n", None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.manifest["code-server"]["version"] = version
                pins.assignments(self.manifest)

    def test_rejects_missing_or_invalid_checksums(self):
        for arch in ("amd64", "arm64"):
            for checksum in ("latest", "$(id)", "a" * 63, None):
                candidate = copy.deepcopy(self.manifest)
                candidate["code-server"]["sha256"][arch] = checksum
                with self.subTest(arch=arch, checksum=checksum), self.assertRaises(ValueError):
                    pins.assignments(candidate)
            candidate = copy.deepcopy(self.manifest)
            del candidate["code-server"]["sha256"][arch]
            with self.assertRaises(KeyError):
                pins.assignments(candidate)

    def test_repository_manifest_is_valid(self):
        pins.assignments(json.loads((ROOT / "deps/manifest.json").read_text()))


if __name__ == "__main__":
    unittest.main()
