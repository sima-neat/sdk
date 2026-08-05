#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPARATOR = ROOT / "scripts" / "compare-debian-mirror-inventories.py"
SPEC = importlib.util.spec_from_file_location("debian_mirror_changes", COMPARATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def package(name: str, version: str, architecture: str = "arm64") -> dict[str, object]:
    return {
        "package": name,
        "version": version,
        "architecture": architecture,
        "filename": f"pool/{name}_{version}_{architecture}.deb",
        "size": 1,
        "sha256": "0" * 64,
    }


class DebianMirrorChangesTest(unittest.TestCase):
    def test_reports_added_removed_and_version_changes(self) -> None:
        result = MODULE.compare_inventories(
            [package("upgrade", "1"), package("removed", "1")],
            [package("upgrade", "2"), package("added", "1")],
            True,
        )
        self.assertEqual(result["counts"], {
            "added_files": 2,
            "removed_files": 2,
            "reused_file_content": 0,
            "version_changes": 1,
        })
        self.assertEqual(result["version_changes"][0]["package"], "upgrade")

    def test_initial_inventory_marks_every_file_added(self) -> None:
        result = MODULE.compare_inventories([], [package("first", "1")], False)
        self.assertFalse(result["baseline_available"])
        self.assertEqual(result["counts"]["added_files"], 1)

    def test_reports_changed_content_at_same_pool_filename(self) -> None:
        previous = package("reused", "1")
        current = dict(previous, size=2, sha256="1" * 64)
        result = MODULE.compare_inventories([previous], [current], True)

        self.assertEqual(result["counts"]["reused_file_content"], 1)
        self.assertEqual(
            result["reused_file_content"][0]["filename"], previous["filename"]
        )


if __name__ == "__main__":
    unittest.main()
