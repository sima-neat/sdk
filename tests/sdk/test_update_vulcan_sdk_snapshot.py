#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from tools.update_vulcan_sdk_snapshot import update_snapshot_mapping


TERRAFORM = '''variable "runner_sdk_cache_snapshots" {
  description = "Approved snapshots."
  type        = map(string)
  default = {
    "sdk-latest"       = "snap-aaaaaaaaaaaaaaaaa"
    "sdk-2.1.3-develop" = "snap-bbbbbbbbbbbbbbbbb"
  }
}

variable "runner_default_allowed_sdk_cache_labels" {
  description = "Approved labels."
  type        = list(string)
  default     = ["sdk-latest", "sdk-2.1.3-develop"]
}
'''


class UpdateVulcanSdkSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "variables.tf"
        self.path.write_text(TERRAFORM, encoding="utf-8")

    def test_replaces_existing_label_and_reports_previous_snapshot(self) -> None:
        result = update_snapshot_mapping(
            self.path,
            "sdk-2.1.3-develop",
            "snap-ccccccccccccccccc",
        )

        self.assertEqual(result["previous_snapshot_id"], "snap-bbbbbbbbbbbbbbbbb")
        self.assertTrue(result["changed"])
        updated = self.path.read_text(encoding="utf-8")
        self.assertIn(
            '"sdk-2.1.3-develop" = "snap-ccccccccccccccccc"', updated
        )
        self.assertNotIn("snap-bbbbbbbbbbbbbbbbb", updated)

    def test_adds_new_label_inside_default_map(self) -> None:
        result = update_snapshot_mapping(
            self.path,
            "sdk-2.1.4-official",
            "snap-ddddddddddddddddd",
        )

        self.assertIsNone(result["previous_snapshot_id"])
        updated = self.path.read_text(encoding="utf-8")
        self.assertIn(
            '    "sdk-2.1.4-official" = "snap-ddddddddddddddddd"\n  }',
            updated,
        )
        self.assertIn('"sdk-2.1.4-official"]', updated)
        self.assertTrue(result["allowlist_changed"])

    def test_rejects_unversioned_or_unqualified_labels(self) -> None:
        for label in ("sdk-develop", "2.1.3-develop", "sdk-2.1.3-nightly"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                update_snapshot_mapping(
                    self.path,
                    label,
                    "snap-eeeeeeeeeeeeeeeee",
                )


if __name__ == "__main__":
    unittest.main()
