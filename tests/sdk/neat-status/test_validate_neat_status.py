#!/usr/bin/env python3
import unittest

from validate_neat_status import validate_status


def status(version):
    return {
        "schema": "sima.neat.status.v1",
        "environment": {"mode": "elxr-sdk", "sdkVersion": version,
                        "sysroot": "/opt/toolchain/aarch64/modalix"},
        "components": {
            "core": {"name": "Neat core", "version": "0.6.0+develop.e1eddd"},
            "pyneat": {"name": "PyNeat", "version": "0.6.0+develop.e1eddd"},
            "insight": {"name": "neat-insight", "version": "0.0.0+develop.c8e29bb",
                        "tag": "c8e29bb", "venv": "/opt/neat-insight/venv", "serviceState": "Running"},
            "modelCompiler": {"name": "Model Compiler", "installed": False, "version": None},
            "runtime": {"name": "neat-runtime", "version": None},
            "gstPlugins": {"name": "neat-gst-plugins", "version": None},
            "runner": {"name": "simaai-runner", "version": "0.2.0~split1+local.22bf023"},
            "scheduler": {"name": "simaai-scheduler", "version": "0.2.0~split1+local.e5d05db"},
        },
    }


class StatusTests(unittest.TestCase):
    def test_platform3_split_components(self):
        for version in ("3.0.0~pre2372_Palette_SDK_neat_develop", "3.0.0_Palette_SDK"):
            with self.subTest(version=version):
                self.assertEqual(validate_status(status(version)), [])

    def test_platform3_requires_both_providers(self):
        for name in ("runner", "scheduler"):
            for missing in (False, True):
                with self.subTest(name=name, missing=missing):
                    data = status("3.0.0~pre2372_Palette_SDK")
                    if missing:
                        del data["components"][name]
                    else:
                        data["components"][name]["version"] = None
                    self.assertIn(f"Missing components.{name}.version", validate_status(data))

    def test_legacy_still_requires_legacy_packages(self):
        data = status("2.1.3_Palette_SDK")
        errors = validate_status(data)
        for name in ("runtime", "gstPlugins"):
            self.assertIn(f"Missing components.{name}.version", errors)
            data["components"][name]["version"] = "0.5.0"
        self.assertEqual(validate_status(data), [])


if __name__ == "__main__":
    unittest.main()
