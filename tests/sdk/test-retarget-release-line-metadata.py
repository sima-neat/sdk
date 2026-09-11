#!/usr/bin/env python3
"""Exercise release promotion with both legacy and Studio-enabled packages."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[2] / "tools/retarget_release_line_metadata.py"
SPEC = importlib.util.spec_from_file_location("retarget", MODULE_PATH)
retarget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retarget)


class RetargetTests(unittest.TestCase):
    def test_promote_metadata_and_manifest(self):
        for studio in (False, True):
            with self.subTest(studio=studio):
                names = ["metadata.json"]
                if studio:
                    names.append("metadata-edgematic-studio.json")
                metadata = {
                    name: {
                        "resources": ["install_sdk_stub.sh", "ghcr:sima-neat/sdk:release-2.1"],
                        "installation": {"script": "./install_sdk_stub.sh" + (
                            " --edgematic-studio" if name != "metadata.json" else ""
                        )},
                    }
                    for name in names
                }
                manifest = {"artifacts": [
                    {"path": name, "size": 0, "sha256": "old"} for name in names
                ] + [{"path": "install_sdk_stub.sh", "size": 42, "sha256": "unchanged"}]}
                uploaded = {}
                invalidations = []

                def fake_run(*args):
                    if args[:3] == ("aws", "cloudfront", "create-invalidation"):
                        invalidations.extend(args[args.index("--paths") + 1:])
                        return
                    self.assertEqual(args[:3], ("aws", "s3", "cp"))
                    source, destination = args[3:5]
                    if source.startswith("s3://"):
                        name = source.rsplit("/", 1)[1]
                        data = "package-version\n" if name == "latest.tag" else json.dumps(
                            manifest if name == "manifest.json" else metadata[name]
                        )
                        Path(destination).write_text(data)
                    else:
                        uploaded[destination.rsplit("/", 1)[1]] = Path(source).read_bytes()

                args = argparse.Namespace(
                    bucket="test", repository="sdk", release_line_ref="release-2.1",
                    image_resource="ghcr:sima-neat/sdk:v2.1.3.3", sse_kms_key_id="",
                    cloudfront_distribution_id="test-distribution",
                )
                with patch.object(retarget, "parse_args", return_value=args), patch.object(
                    retarget, "run", side_effect=fake_run
                ):
                    retarget.main()

                self.assertEqual(set(uploaded), set(names + ["manifest.json"]))
                promoted_manifest = json.loads(uploaded["manifest.json"])
                for name in names:
                    promoted = json.loads(uploaded[name])
                    self.assertEqual(promoted["resources"], ["install_sdk_stub.sh", args.image_resource])
                    self.assertEqual(promoted["installation"], metadata[name]["installation"])
                    entry = next(a for a in promoted_manifest["artifacts"] if a["path"] == name)
                    self.assertEqual(entry["size"], len(uploaded[name]))
                    self.assertEqual(entry["sha256"], hashlib.sha256(uploaded[name]).hexdigest())
                    self.assertIn(f"/sdk/release-2.1/package-version/{name}", invalidations)
                self.assertEqual(promoted_manifest["artifacts"][-1], manifest["artifacts"][-1])


if __name__ == "__main__":
    unittest.main()
