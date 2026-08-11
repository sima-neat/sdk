#!/usr/bin/env python3
"""Regression tests for the daily Debian mirror summary tooling."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collector = load_script("mirror_summary_collector", "collect-debian-mirror-summary.py")
generator = load_script("mirror_summary_generator", "generate-debian-mirror-summary.py")
poster = load_script("mirror_summary_poster", "post-debian-mirror-summary.py")


def package(name: str, version: str, architecture: str) -> dict[str, Any]:
    return {
        "package": name,
        "version": version,
        "architecture": architecture,
        "filename": f"pool/{name}_{version}_{architecture}.deb",
    }


def result(
    digest: str,
    timestamp: str,
    platform_version: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "result": "Published",
        "source": {"date": timestamp, "inrelease_sha256": digest},
        "publication": {"published_at": timestamp},
        "platform": {
            "anchor_package": "simaai-palette-modalix",
            "architecture": "arm64",
            "versions": [platform_version],
        },
        "changes": changes,
    }


def build_fixture(root: Path) -> None:
    first, second = "1" * 64, "2" * 64
    runs = [
        {"id": 101, "conclusion": "success", "run_started_at": "2026-08-09T23:50:00Z", "html_url": "https://github.com/sima-neat/sdk/actions/runs/101", "result_file": "101.json"},
        {"id": 102, "conclusion": "success", "run_started_at": "2026-08-10T22:00:00Z", "html_url": "https://github.com/sima-neat/sdk/actions/runs/102", "result_file": "102.json"},
        {"id": 105, "conclusion": "success", "run_started_at": "2026-08-10T22:10:00Z", "html_url": "https://github.com/sima-neat/sdk/actions/runs/105", "result_file": "105.json"},
        {"id": 103, "conclusion": "success", "run_started_at": "2026-08-08T22:00:00Z", "html_url": "https://github.com/sima-neat/sdk/actions/runs/103", "result_file": "missing.json"},
        {"id": 104, "conclusion": "failure", "run_started_at": "2026-08-10T23:00:00Z", "html_url": "https://github.com/sima-neat/sdk/actions/runs/104", "result_file": "missing.json"},
    ]
    (root / "runs.json").write_text(json.dumps(runs), encoding="utf-8")
    first_changes = {
        "counts": {"added_files": 1, "removed_files": 0, "version_changes": 1},
        "added": [package("foo", "1.1", "arm64")],
        "removed": [],
        "version_changes": [{"package": "foo", "architecture": "arm64", "previous_versions": ["1.0"], "current_versions": ["1.1"]}],
    }
    second_changes = {
        "counts": {"added_files": 3, "removed_files": 1, "version_changes": 3},
        "added": [package("foo", "1.1", "amd64"), package("simaai-palette-modalix", "2.1.3~pre4617", "arm64"), package("simaai-palette-modalix", "2.1.3~pre4617", "amd64")],
        "removed": [package("obsolete", "0.9", "arm64")],
        "version_changes": [
            {"package": "foo", "architecture": "amd64", "previous_versions": ["1.0"], "current_versions": ["1.1"]},
            {"package": "simaai-palette-modalix", "architecture": "arm64", "previous_versions": ["2.1.3~pre4593"], "current_versions": ["2.1.3~pre4617"]},
            {"package": "simaai-palette-modalix", "architecture": "amd64", "previous_versions": ["2.1.3~pre4593"], "current_versions": ["2.1.3~pre4617"]},
        ],
    }
    (root / "101.json").write_text(json.dumps(result(first, "2026-08-10T12:05:00Z", "2.1.3~pre4593", first_changes)), encoding="utf-8")
    (root / "102.json").write_text(json.dumps(result(second, "2026-08-10T22:05:00Z", "2.1.3~pre4617", second_changes)), encoding="utf-8")
    (root / "105.json").write_text(
        json.dumps(
            result(
                second,
                "2026-08-10T22:15:00Z",
                "2.1.3~pre4617",
                {
                    "counts": {"added_files": 0, "removed_files": 0, "version_changes": 0},
                    "added": [],
                    "removed": [],
                    "version_changes": [],
                },
            )
        ),
        encoding="utf-8",
    )


def test_version_ordering() -> None:
    values = ["2.1.3~pre10", "2.1.3", "2.1.3~pre9", "1:1.0", "2.1.3~rc1"]
    assert collector.sorted_versions(values) == ["2.1.3~pre9", "2.1.3~pre10", "2.1.3~rc1", "2.1.3", "1:1.0"]


def test_collection_and_fallback() -> None:
    with tempfile.TemporaryDirectory() as directory:
        build_fixture(Path(directory))
        source = collector.FixtureSource(Path(directory))
        as_of = collector.parse_utc("2026-08-11T00:00:00Z")
        since = as_of - collector.dt.timedelta(hours=24)
        publications = collector.load_publications(source, since, as_of)
        assert len(publications) == 2
        assert publications[-1]["_run"]["id"] == 102
        context = collector.build_context(publications, since, as_of)
        assert context["platform"]["previous_version"] == "2.1.3~pre4593"
        assert context["platform"]["current_version"] == "2.1.3~pre4617"
        assert context["counts"] == {"package_transitions": 2, "added_package_groups": 2, "removed_package_groups": 1, "added_files": 4, "removed_files": 1}
        foo = next(item for item in context["package_transitions"] if item["package"] == "foo")
        assert foo["architectures"] == ["amd64", "arm64"]
        report = generator.fallback_report(context, 1000)
        assert "2.1.3~pre4593" in report and "2.1.3~pre4617" in report
        assert "`foo`" in report and len(report) <= 1000
        empty_report = generator.fallback_report(collector.build_context([], since, as_of), 1000)
        assert "No mirror publications were found" in empty_report


def test_platform_summary_preserves_earliest_baseline() -> None:
    publications = []
    for index, (previous, current) in enumerate(
        [(None, "2.1.3~pre4593"), ("2.1.3~pre4593", "2.1.3~pre4617"), ("2.1.3~pre4617", "2.1.3~pre4625")],
        start=1,
    ):
        changes = {"version_changes": []}
        if previous:
            changes["version_changes"].append(
                {
                    "package": "simaai-palette-modalix",
                    "architecture": "arm64",
                    "previous_versions": [previous],
                    "current_versions": [current],
                }
            )
        publication = result(
            str(index) * 64,
            f"2026-08-10T0{index}:00:00Z",
            current,
            changes,
        )
        publication["_run"] = {
            "id": index,
            "html_url": f"https://github.com/sima-neat/sdk/actions/runs/{index}",
            "started_at": f"2026-08-10T0{index}:00:00Z",
        }
        publications.append(publication)

    summary = collector.platform_summary(publications)
    assert summary["previous_version"] == "2.1.3~pre4593"
    assert summary["current_version"] == "2.1.3~pre4625"


class FakeResponse:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.document).encode("utf-8")


def test_slack_validation_and_dry_run() -> None:
    original_urlopen = poster.urllib.request.urlopen
    try:
        poster.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse({"ok": True, "ts": "1.2"})
        assert poster.post_message("secret", "C123", "hello")["ts"] == "1.2"
        poster.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse({"ok": False, "error": "channel_not_found"})
        try:
            poster.post_message("secret", "bad", "hello")
        except RuntimeError as error:
            assert "channel_not_found" in str(error)
        else:
            raise AssertionError("Slack ok:false response was accepted")

        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            report.write_text("dry-run report\n", encoding="utf-8")
            poster.urllib.request.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dry run attempted a Slack request"))
            original_argv = sys.argv
            sys.argv = ["post-debian-mirror-summary.py", "--report", str(report), "--dry-run"]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    assert poster.main() == 0
            finally:
                sys.argv = original_argv
    finally:
        poster.urllib.request.urlopen = original_urlopen


def main() -> int:
    test_version_ordering()
    test_collection_and_fallback()
    test_platform_summary_preserves_earliest_baseline()
    test_slack_validation_and_dry_run()
    print("Debian mirror summary tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
