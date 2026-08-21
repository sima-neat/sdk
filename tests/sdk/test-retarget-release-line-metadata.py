#!/usr/bin/env python3
"""Unit tests for SDK release-line metadata retargeting."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "tools" / "retarget_release_line_metadata.py"
SPEC = importlib.util.spec_from_file_location("retarget_release_line_metadata", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
RETARGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RETARGET)


class RetargetMetadataResourceTests(unittest.TestCase):
    def retarget(
        self, resources: list[str], release_line_ref: str = "release-2.1"
    ) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "metadata.json"
            metadata_path.write_text(json.dumps({"resources": resources}), encoding="utf-8")
            RETARGET.retarget_metadata_resource(
                metadata_path,
                "ghcr:sima-neat/sdk:v2.1.3.0",
                release_line_ref,
            )
            return json.loads(metadata_path.read_text(encoding="utf-8"))["resources"]

    def test_retargets_canonical_release_line_tag(self) -> None:
        self.assertEqual(
            self.retarget(["install_sdk_stub.sh", "ghcr:sima-neat/sdk:release-2.1"]),
            ["install_sdk_stub.sh", "ghcr:sima-neat/sdk:v2.1.3.0"],
        )

    def test_retargets_offline_bundle_release_line_repository(self) -> None:
        self.assertEqual(
            self.retarget(
                ["install_sdk_stub.sh", "ghcr:sima-neat/sdk-release-2.1:latest"]
            ),
            ["install_sdk_stub.sh", "ghcr:sima-neat/sdk:v2.1.3.0"],
        )

    def test_does_not_retarget_a_different_release_line_repository(self) -> None:
        with self.assertRaisesRegex(SystemExit, "release-line SDK image resource"):
            self.retarget(["ghcr:sima-neat/sdk-release-2.0:latest"])


if __name__ == "__main__":
    unittest.main()
