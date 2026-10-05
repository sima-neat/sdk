#!/usr/bin/env python3
"""Verify generated install commands work after downloads lose executable mode.

Requires sima-cli on PATH, as does tools/prepare_s3_artifacts.sh.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PackageTests(unittest.TestCase):
    def test_downloaded_installer_without_executable_mode(self):
        with tempfile.TemporaryDirectory(prefix="sdk-package-test-") as tmp:
            tmp_path = Path(tmp)
            package = tmp_path / "package"
            subprocess.run([
                "bash", str(ROOT / "tools/prepare_s3_artifacts.sh"),
                "--output-dir", str(package),
                "--image-resource", "ghcr:sima-neat/sdk:develop",
                "--version", "develop", "--release", "develop",
            ], check=True, capture_output=True, text=True)
            (package / "install_sdk_stub.sh").chmod(0o644)
            cli = tmp_path / "sima-cli"
            log = tmp_path / "arguments"
            cli.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$SDK_TEST_LOG"\n')
            cli.chmod(0o755)
            env = dict(os.environ, SIMA_CLI=str(cli), SDK_TEST_LOG=str(log))

            for name, studio_args in [
                ("metadata.json", []),
                ("metadata-edgematic-studio.json", ["--edgematic-studio"]),
            ]:
                metadata = json.loads((package / name).read_text())
                for pairing in (False, True):
                    with self.subTest(metadata=name, pairing=pairing):
                        result = subprocess.run(
                            metadata["installation"]["script"], shell=True,
                            cwd=package, env=env,
                            input="y\n10.0.0.244\n" if pairing else "n\n",
                            text=True, capture_output=True,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        expected = ["sdk", "setup"]
                        if pairing:
                            expected += ["--devkit", "10.0.0.244"]
                        self.assertEqual(log.read_text().splitlines(), expected + studio_args)


if __name__ == "__main__":
    unittest.main()
