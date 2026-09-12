#!/usr/bin/env python3
"""Test daily package selection using Debian's actual version comparisons."""
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('sdk_setup', ROOT / 'scripts/simaai_setup_sdk.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PLATFORM = '3.0.0~git202609090513.9e68a68-1218'


def candidate(version, site='debian.neat.sima.ai', codename='agate'):
    return SimpleNamespace(version=version, origins=[SimpleNamespace(site=site, codename=codename)])


class DailySelectionTest(unittest.TestCase):
    def test_independent_component_version_and_build_cutoff(self):
        future = candidate('2.2.0~git202609100513.abcdef0-1220')
        selected = candidate('2.2.0~git202609090513.abcdef0-1218')
        older = candidate('2.2.0~git202609080513.abcdef0-1211')
        self.assertIs(module.daily_candidate([future, selected, older], PLATFORM), selected)
        self.assertIs(module.daily_candidate([future, older], PLATFORM), older)
        self.assertIsNone(module.daily_candidate([future], PLATFORM))

    def test_all_package_native_cache_key_without_host_arch_fallback(self):
        all_package = SimpleNamespace(architecture="all")
        host_package = SimpleNamespace(architecture="amd64")
        target_package = SimpleNamespace(architecture="arm64")
        cache = {"palette": SimpleNamespace(versions=[all_package]),
                 "library": SimpleNamespace(versions=[host_package]),
                 "library:arm64": SimpleNamespace(versions=[target_package])}
        self.assertEqual(module.daily_package_versions(cache, "palette:arm64"), [all_package])
        self.assertEqual(module.daily_package_versions(cache, "library:arm64"), [target_package])
        self.assertEqual(module.daily_package_versions(cache, "library"), [target_package])
        del cache["library:arm64"]
        self.assertEqual(module.daily_package_versions(cache, "library:arm64"), [])

    def test_exact_and_minimum_dependency_constraints(self):
        versions = [candidate('3.0.0~git202609090513.abc1234-1218'), candidate('3.0.0~git202609080513.abc1234-1211')]
        self.assertIs(module.daily_candidate(versions, PLATFORM, versions[1].version), versions[1])
        self.assertIs(module.daily_candidate(versions, PLATFORM, versions[1].version, '>='), versions[0])
        self.assertIsNone(module.daily_candidate(versions, PLATFORM, '9.0', '>='))

    def test_debian13_only_and_daily_kernel_headers_preferred(self):
        host = candidate('99.0', 'ports.ubuntu.com', 'noble')
        bookworm = candidate('2.36', 'deb.debian.org', 'bookworm')
        trixie = candidate('2.41', 'deb.debian.org', 'trixie')
        self.assertIs(module.daily_candidate([host, trixie, bookworm], PLATFORM), trixie)
        self.assertIsNone(module.daily_candidate([host, bookworm], PLATFORM))
        headers = candidate('6.18.3-1218')
        self.assertIs(module.daily_candidate([candidate('6.19', 'deb.debian.org', 'trixie'), headers], PLATFORM), headers)

    def test_floating_daily_selector_uses_debian_ordering(self):
        with tempfile.TemporaryDirectory() as directory:
            packages = Path(directory) / "Packages"
            versions = ["3.0.0~git202609090513.9e68a68-9", "3.0.0~git202609090513.9e68a68-10"]
            packages.write_text("".join(f"Package: simaai-palette-modalix\nVersion: {v}\nArchitecture: all\n\n" for v in versions))
            env = {**os.environ, "PRE_RELEASE_BASE": "3.0.0", "GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "3.0.0-prep", "PRE_RELEASE_PACKAGES_FILE": str(packages)}
            output = subprocess.check_output(["bash", str(ROOT / "scripts/resolve-platform-config.sh")], env=env, text=True)
            self.assertIn("sdk_apt_channel=daily\n", output)
            self.assertIn(f"base_sdk_version={versions[1]}\n", output)

    def test_finalize_overlay_preserves_headers_without_downloading_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            libdir = root / "usr/lib/aarch64-linux-gnu"
            (libdir / "openblas-pthread").mkdir(parents=True)
            for name in ("libblas.so.3", "liblapack.so.3", "libopenblas.so.0"):
                (libdir / "openblas-pthread" / name).write_text("target library")
            header = root / "usr/include/linux/version.h"
            header.parent.mkdir(parents=True)
            header.write_text("Agate UAPI headers")
            apt = root / "apt-get"
            apt.write_text("#!/bin/sh\nexit 87\n")
            apt.chmod(0o755)
            subprocess.run(["bash", str(ROOT / "scripts/install-sysroot-overlay.sh"),
                            str(root), "--finalize-only"],
                           env={**os.environ, "PATH": f"{root}:" + os.environ["PATH"]}, check=True)
            self.assertEqual(header.read_text(), "Agate UAPI headers")
            for name in ("libblas.so", "liblapack.so", "libopenblas.so"):
                self.assertEqual((libdir / name).read_text(), "target library")

    def test_daily_sdk_rejects_legacy_install_before_apt(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / "sdk-release"
            metadata.write_text("Platform Base = 3.0.0\nPlatform Channel = daily\n")
            result = subprocess.run(["bash", str(ROOT / "scripts/sysroot.sh"), "install", "libpgm-dev"],
                                    env={**os.environ, "SDK_RELEASE_FILE": str(metadata)},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("rebuild with BASE_SDK_VERSION and SDK_PKG_LIST", result.stderr)

    def test_wrapper_keeps_kernel_version_and_extra_packages_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "args.json"
            python = root / "capture-python"
            python.write_text("#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\nPath(" + repr(str(capture)) + ").write_text(json.dumps(sys.argv[1:]))\n")
            python.chmod(0o755)
            validator = root / "validate-sysroot-package-versions.sh"
            validator.write_text("#!/bin/sh\nexit 0\n")
            validator.chmod(0o755)
            env = {**os.environ, "PATH": f"{root}:" + os.environ["PATH"],
                   "SDK_APT_CHANNEL": "daily", "SDK_SYSROOT_PYTHON": str(python),
                   "SYSROOT": str(root / "sysroot"), "SYSROOT_UPDATE_DOWNLOAD_DIR": str(root),
                   "SDK_LINUX_LIBC_VERSION": "6.18.3-1218", "MINIMAL_IMAGE": "0"}
            subprocess.run(["bash", str(ROOT / "scripts/setup-sdk-sysroot.sh"), PLATFORM, "libgrpc-dev"], env=env, check=True)
            args = json.loads(capture.read_text())
            self.assertEqual(args[1:4], ["modalix", PLATFORM, "6.18.3-1218"])
            self.assertIn("libgrpc-dev", args[4].split(","))
            self.assertIn("python3-dev", args[4].split(","))


if __name__ == '__main__':
    unittest.main()
