#!/usr/bin/env python3
"""Regress daily virtual dependency resolution using Debian version semantics."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import apt_pkg

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sdk_setup", ROOT / "scripts/simaai_setup_sdk.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PLATFORM = "3.0.0~git202609090513.abcdef0-1369"
ABI = "qt6-base-private-abi"
CORE = "libqt6core6t64"
CORE_VERSION = "6.8.2+dfsg-9+deb13u2"


def dependency(name, version="", relation="="):
    return SimpleNamespace(name=name, version=version, relation=relation)


def candidate(name, version, provides="", dependencies=(), architecture="arm64",
              site="deb.debian.org", codename="trixie"):
    return SimpleNamespace(
        package=SimpleNamespace(name=name), version=version,
        architecture=architecture, record={"Provides": provides},
        origins=[SimpleNamespace(site=site, codename=codename)],
        get_dependencies=lambda _kind: [[dep] for dep in dependencies],
    )


class Cache(dict):
    """Keep package-wide provider lookup distinct from per-version Provides."""
    def __init__(self, candidates):
        super().__init__()
        for item in candidates:
            key = (item.package.name if item.architecture == "all"
                   else f"{item.package.name}:{item.architecture}")
            self.setdefault(key, SimpleNamespace(versions=[])).versions.append(item)

    def open(self, _progress):
        pass

    def get_providing_packages(self, name, candidate_only=True):
        return [package for package in self.values() if any(
            provided_name == module.base_package_name(name)
            for version in (package.versions[:1] if candidate_only else package.versions)
            for group in apt_pkg.parse_depends(version.record.get("Provides", ""))
            for provided_name, _version, _relation in group
        )]


class ResolutionComplete(Exception):
    """Stop main at its first download-directory creation, after runtime resolution."""


class DailyProvidersTest(unittest.TestCase):
    def resolve(self, packages, dependencies):
        palette = candidate("simaai-palette-modalix", PLATFORM,
                            dependencies=dependencies,
                            site="debian.neat.sima.ai", codename="agate")
        cache = Cache([palette, *packages])
        with patch.dict(os.environ, {"SDK_APT_CHANNEL": "daily"}), \
             patch.object(module.apt, "Cache", return_value=cache), \
             patch.object(module, "update_apt_cache"), \
             patch.object(module, "whitelist", [], create=True), \
             patch.object(module.os, "makedirs", side_effect=ResolutionComplete):
            module.main("simaai-palette-modalix:arm64", PLATFORM, "6.18.3-1369",
                        "/unused-downloads", "/unused-sysroot")

    def assert_resolves(self, packages, dependencies):
        with self.assertRaises(ResolutionComplete):
            self.resolve(packages, dependencies)

    def test_matching_provides_accepts_distinct_package_version(self):
        provider = candidate(CORE, CORE_VERSION, f"{ABI} (= 6.8.2)")
        self.assert_resolves([provider], [dependency(ABI, "6.8.2")])
        self.assertEqual(provider.version, CORE_VERSION)

    def test_versioned_requirement_rejects_incompatible_or_unversioned_provides(self):
        for provides in (f"{ABI} (= 6.8.1)", ABI,
                         f"other-abi (= 6.8.2), {ABI} (= 6.8.1)"):
            with self.subTest(provides=provides):
                # Matching package.version must not make a bad Provides acceptable.
                provider = candidate(CORE, "6.8.2", provides)
                with self.assertRaisesRegex(RuntimeError, "No Agate/Trixie candidate"):
                    self.resolve([provider], [dependency(ABI, "6.8.2")])

    def test_unversioned_virtual_dependency_accepts_unversioned_provides(self):
        self.assert_resolves([candidate(CORE, CORE_VERSION, ABI)], [dependency(ABI)])

    def test_each_provider_version_must_itself_provide_the_requested_abi(self):
        for provides in ("", f"{ABI} (= 6.9.0)"):
            with self.subTest(newer_provides=provides):
                newer = candidate(CORE, "6.9.0-1", provides,
                                  dependencies=[dependency("unavailable-package")])
                matching = candidate(CORE, CORE_VERSION, f"{ABI} (= 6.8.2)")
                self.assert_resolves([newer, matching], [dependency(ABI, "6.8.2")])

    def test_provided_version_uses_debian_relations(self):
        provider = candidate(CORE, "0.1-1", f"{ABI} (= 1:6.8.2-1)")
        self.assert_resolves([provider], [dependency(ABI, "1:6.8.2", ">=")])
        with self.assertRaisesRegex(RuntimeError, "No Agate/Trixie candidate"):
            self.resolve([provider], [dependency(ABI, "1:6.8.2", "<<")])

    def test_repeated_virtual_dependency_reuses_real_provider_version(self):
        provider = candidate(CORE, CORE_VERSION, f"{ABI} (= 6.8.2)")
        dbus = candidate("libqt6dbus6", CORE_VERSION,
                         dependencies=[dependency(ABI, "6.8.2")])
        gui = candidate("libqt6gui6", CORE_VERSION,
                        dependencies=[dependency(ABI, "6.8.2")])
        self.assert_resolves([provider, dbus, gui],
                             [dependency("libqt6dbus6"), dependency("libqt6gui6")])

    def test_preselected_provider_satisfies_virtual_requirement(self):
        provider = candidate(CORE, CORE_VERSION, f"{ABI} (= 6.8.2)")
        dbus = candidate("libqt6dbus6", CORE_VERSION,
                         dependencies=[dependency(ABI, "6.8.2")])
        self.assert_resolves([provider, dbus],
                             [dependency(CORE, CORE_VERSION), dependency("libqt6dbus6")])

    def test_new_candidate_cannot_bless_incompatible_preselected_provider(self):
        newer = candidate(CORE, CORE_VERSION, f"{ABI} (= 6.8.2)")
        older = candidate(CORE, "6.8.1-1", f"{ABI} (= 6.8.1)")
        dbus = candidate("libqt6dbus6", CORE_VERSION,
                         dependencies=[dependency(ABI, "6.8.2")])
        with self.assertRaisesRegex(RuntimeError, "Conflicting dependency"):
            self.resolve([newer, older, dbus],
                         [dependency(CORE, older.version), dependency("libqt6dbus6")])

    def test_provider_filters_keep_architecture_origin_and_build_cutoff(self):
        cases = (
            {"architecture": "amd64"},
            {"site": "ports.ubuntu.com", "codename": "noble"},
            {"codename": "bookworm"},
            {"site": "debian.neat.sima.ai", "codename": "agate"},
        )
        for attributes in cases:
            with self.subTest(attributes=attributes):
                provider = candidate(CORE, "6.8.2-1370", f"{ABI} (= 6.8.2)", **attributes)
                with self.assertRaisesRegex(RuntimeError, "No Agate/Trixie candidate"):
                    self.resolve([provider], [dependency(ABI, "6.8.2")])
        allowed = candidate(CORE, "6.8.2-1369", f"{ABI} (= 6.8.2)",
                            site="debian.neat.sima.ai", codename="agate")
        self.assert_resolves([allowed], [dependency(ABI, "6.8.2")])
        independent = candidate(CORE, CORE_VERSION, f"{ABI} (= 6.8.2)", architecture="all")
        self.assert_resolves([independent], [dependency(ABI, "6.8.2")])

    def test_ordinary_dependency_keeps_full_package_version_comparison(self):
        package = candidate(CORE, CORE_VERSION, f"{ABI} (= 6.8.2)")
        self.assert_resolves([package], [dependency(CORE, CORE_VERSION)])
        self.assert_resolves([package], [dependency(CORE, "6.8.2", ">=")])
        with self.assertRaisesRegex(RuntimeError, "No Agate/Trixie candidate"):
            self.resolve([package], [dependency(CORE, "6.8.2")])

    def test_ordinary_preselected_dependency_still_rejects_conflicts(self):
        newer = candidate("library", "2.0")
        older = candidate("library", "1.0")
        consumer = candidate("consumer", "1.0", dependencies=[dependency("library", "2.0")])
        with self.assertRaisesRegex(RuntimeError, "Conflicting dependency"):
            self.resolve([newer, older, consumer],
                         [dependency("library", "1.0"), dependency("consumer")])


if __name__ == "__main__":
    unittest.main()
