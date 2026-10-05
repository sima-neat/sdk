#!/usr/bin/env python3

"""Regression tests for sysroot update progress reporting."""

import contextlib
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.modules.setdefault("apt", types.ModuleType("apt"))
spec = importlib.util.spec_from_file_location(
    "simaai_setup_sdk", ROOT / "scripts" / "simaai_setup_sdk.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeOrigin:
    def __init__(self, origin, site, archive="", label=""):
        self.origin = origin
        self.site = site
        self.archive = archive
        self.label = label


class FakeCandidate:
    def __init__(self, version, uri, origins):
        self.version = version
        self.uri = uri
        self.origins = origins


os.environ["SIMAAI_VALIDATE_TARGET_ORIGIN"] = "1"
try:
    module.validate_target_candidate(
        "libgstreamer1.0-0:arm64",
        FakeCandidate(
            "1.22.0-2+deb12u1",
            "http://deb.debian.org/debian/pool/main/g/gstreamer1.0/package.deb",
            [FakeOrigin("Debian", "deb.debian.org", "bookworm", "Debian")],
        ),
    )

    try:
        module.validate_target_candidate(
            "libgstreamer1.0-0:arm64",
            FakeCandidate(
                "1.24.2-1ubuntu0.1",
                "http://ports.ubuntu.com/ubuntu-ports/pool/main/g/gstreamer1.0/package.deb",
                [FakeOrigin("Ubuntu", "ports.ubuntu.com", "noble-updates", "Ubuntu")],
            ),
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "Refusing host-distribution package libgstreamer1.0-0:arm64" in message
        assert "1.24.2-1ubuntu0.1" in message
        assert "Ubuntu@ports.ubuntu.com" in message
    else:
        raise AssertionError("Ubuntu host package was accepted for the Modalix sysroot")

    # Unknown third-party repositories are not classified as the Ubuntu SDK host.
    module.validate_target_candidate(
        "vendor-library:arm64",
        FakeCandidate(
            "1.0.0",
            "https://packages.vendor.example/pool/vendor-library.deb",
            [FakeOrigin("Vendor", "packages.vendor.example", "stable", "Vendor")],
        ),
    )
finally:
    del os.environ["SIMAAI_VALIDATE_TARGET_ORIGIN"]

# Stable SDK construction and explicit sysroot installs keep their existing
# behavior unless the overlay-update entry point enables the origin gate.
module.validate_target_candidate(
    "libgstreamer1.0-0:arm64",
    FakeCandidate(
        "1.24.2-1ubuntu0.1",
        "http://ports.ubuntu.com/ubuntu-ports/pool/main/g/gstreamer1.0/package.deb",
        [FakeOrigin("Ubuntu", "ports.ubuntu.com", "noble-updates", "Ubuntu")],
    ),
)


output = io.StringIO()
with contextlib.redirect_stdout(output):
    downloads = module.DownloadProgress()
    downloads.begin_batch(["downloaded", "cached"])
    downloads.complete("downloaded", False, 2 * 1024 * 1024)
    downloads.complete("cached", True, 6 * 1024 * 1024)
    downloads.end_batch()
    downloads.finish()

    extraction = module.ExtractionProgress(2)
    extraction.start()
    extraction.begin_package("first.deb")
    extraction.complete_package()
    extraction.begin_package("second.deb")
    extraction.complete_package()
    extraction.finish(True)

text = output.getvalue()
assert "2/2 ready (1 downloaded/2.0 MiB, 1 cached/6.0 MiB)" in text
assert "Package extraction complete: 2/2" in text

sysroot_usr = "/opt/toolchain/aarch64/modalix/usr"
cmake_config = 'set(SIMA_INCLUDE_DIR "/usr/include")\n'
rewritten_config = module.rewrite_config_paths(cmake_config, "/usr", sysroot_usr)
assert rewritten_config == (
    'set(SIMA_INCLUDE_DIR "/opt/toolchain/aarch64/modalix/usr/include")\n'
)
assert (
    module.rewrite_config_paths(rewritten_config, "/usr", sysroot_usr)
    == rewritten_config
)

custom_sysroot_usr = "/usr/local/modalix/usr"
mixed_config = (
    'set(SIMA_INCLUDE_DIR "/usr/include")\n'
    'set(SIMA_LIBRARY_DIR "/usr/local/modalix/usr/lib")\n'
)
custom_rewritten_config = module.rewrite_config_paths(
    mixed_config, "/usr", custom_sysroot_usr
)
assert custom_rewritten_config == (
    'set(SIMA_INCLUDE_DIR "/usr/local/modalix/usr/include")\n'
    'set(SIMA_LIBRARY_DIR "/usr/local/modalix/usr/lib")\n'
)
assert (
    module.rewrite_config_paths(custom_rewritten_config, "/usr", custom_sysroot_usr)
    == custom_rewritten_config
)

with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    downloads = root / "downloads"
    sysroot = root / "sysroot"
    downloads.mkdir()
    (downloads / "alpha.deb").touch()
    (downloads / "beta.deb").touch()
    fields = {
        "alpha.deb": {"Package": "alpha", "Architecture": "arm64", "Version": "1.2.3"},
        "beta.deb": {"Package": "beta", "Architecture": "all", "Version": "4.5.6"},
    }
    original_control_fields = module.package_control_fields
    original_payload_locations = module.package_payload_locations
    module.package_control_fields = lambda path, *wanted: tuple(
        fields[pathlib.Path(path).name][field] for field in wanted
    )
    module.package_payload_locations = lambda path: (
        "/usr/include,/usr/lib/aarch64-linux-gnu"
        if pathlib.Path(path).name == "alpha.deb"
        else "/usr/share"
    )
    try:
        module.write_sysroot_package_inventory(str(downloads), str(sysroot))
    finally:
        module.package_control_fields = original_control_fields
        module.package_payload_locations = original_payload_locations
    inventory = sysroot / "var/lib/sima-sdk/sysroot-packages.tsv"
    assert inventory.read_text(encoding="utf-8") == (
        "alpha\tarm64\t1.2.3\t/usr/include,/usr/lib/aarch64-linux-gnu\n"
        "beta\tall\t4.5.6\t/usr/share\n"
    )

    cached_deb = downloads / "alpha.deb"
    cache_metadata = {
        "architecture": "arm64",
        "package": "alpha",
        "sha256": "abc123",
        "uri": "https://debian.example/alpha.deb",
        "version": "1.2.3",
    }
    module.write_download_cache_metadata(cached_deb, cache_metadata)
    assert module.read_download_cache_metadata(cached_deb) == cache_metadata
    metadata_path = pathlib.Path(module.download_cache_metadata_path(cached_deb))
    metadata_path.write_text("not-json", encoding="utf-8")
    assert module.read_download_cache_metadata(cached_deb) is None

print("sysroot progress tests passed")
