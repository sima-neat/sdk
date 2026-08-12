#!/usr/bin/env python3

"""Regression tests for sysroot update progress reporting."""

import contextlib
import importlib.util
import io
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


output = io.StringIO()
with contextlib.redirect_stdout(output):
    downloads = module.DownloadProgress()
    downloads.begin_batch(["downloaded", "cached"])
    downloads.complete("downloaded", False)
    downloads.complete("cached", True)
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
assert "2/2 ready (1 downloaded, 1 cached)" in text
assert "Package extraction complete: 2/2" in text

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

print("sysroot progress tests passed")
