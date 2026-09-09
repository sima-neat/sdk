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
        {"id": 104, "conclusion": "failure", "run_started_at": "2026-08-10T23:00:00Z", "html_url": "https://github.com/sima-neat/sdk/actions/runs/104"},
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


def test_agate_platform_summary_and_rendering() -> None:
    previous = "3.0.0~git202609090513.9e68a68-9"
    current = "3.0.0~git202609090513.9e68a68-10"
    # Exercise Debian revision ordering, not lexicographic string ordering.
    assert collector.sorted_versions([current, previous]) == [previous, current]
    for architecture in ("arm64", "all"):
        for before, after in ((previous, current), (None, current), (previous, None), (current, previous)):
            changes = {"added": [], "removed": [], "version_changes": []}
            if before and after:
                changes["version_changes"] = [{
                    "package": "simaai-palette-modalix",
                    "architecture": architecture,
                    "previous_versions": [before],
                    "current_versions": [after],
                }]
            elif before:
                changes["removed"] = [package("simaai-palette-modalix", before, architecture)]
            else:
                changes["added"] = [package("simaai-palette-modalix", after, architecture)]
            publication = result("a" * 64, "2026-09-09T06:45:35Z", after or "", changes)
            publication["platform"]["versions"] = [after] if after else []
            if before == previous and after == current:
                publication["platform"]["versions"] = [current, previous, "invalid-version"]
            publication["_run"] = {"id": 1, "html_url": "https://github.com/sima-neat/sdk/actions/runs/1"}
            context = collector.build_context(
                [publication],
                collector.parse_utc("2026-09-09T00:00:00Z"),
                collector.parse_utc("2026-09-10T00:00:00Z"),
            )
            summary = context["platform"]
            assert summary["previous_version"] == before, (architecture, before, after, summary)
            assert summary["current_version"] == after
            assert summary["changed"] is True
            report = generator.fallback_report(context, 2000)
            if before and after:
                assert f"Platform: `{before}` → `{after}`" in report
            elif before:
                assert f"Platform: `{before}` → removed" in report
            else:
                assert f"Platform: added `{after}`" in report


def test_platform_version_validation() -> None:
    for value in ("2.1.3~pre4766", "3.0.0~git202609090513.9e68a68-1218"):
        assert collector.PLATFORM_VERSION_RE.fullmatch(value)
    for value in ("3.0.0~git", "3.0.0~git202609090513.9e68a68", "3.0.0~git202609090513.bad!-1218", "3.0.0~prex"):
        assert not collector.PLATFORM_VERSION_RE.fullmatch(value)


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


def test_collection_preserves_digest_rollback() -> None:
    versions = ["2.1.3~pre4593", "2.1.3~pre4617", "2.1.3~pre4593"]
    digests = ["a" * 64, "b" * 64, "a" * 64]
    results = []
    runs = []
    for index, (digest, version) in enumerate(zip(digests, versions), start=1):
        previous = versions[index - 2] if index > 1 else "2.1.3~pre4500"
        timestamp = f"2026-08-10T0{index}:00:00Z"
        results.append(
            result(
                digest,
                timestamp,
                version,
                {
                    "counts": {"version_changes": 1},
                    "added": [],
                    "removed": [],
                    "version_changes": [
                        {
                            "package": "simaai-palette-modalix",
                            "architecture": "arm64",
                            "previous_versions": [previous],
                            "current_versions": [version],
                        }
                    ],
                },
            )
        )
        runs.append(
            {
                "id": index,
                "run_started_at": timestamp,
                "html_url": f"https://github.com/sima-neat/sdk/actions/runs/{index}",
            }
        )

    class RollbackSource:
        def list_runs(self, _earliest_started_at: collector.dt.datetime) -> list[dict[str, Any]]:
            return runs

        def read_result(self, run: dict[str, Any]) -> dict[str, Any]:
            return results[int(run["id"]) - 1]

    as_of = collector.parse_utc("2026-08-11T00:00:00Z")
    publications = collector.load_publications(
        RollbackSource(), as_of - collector.dt.timedelta(hours=24), as_of
    )
    assert [item["source"]["inrelease_sha256"] for item in publications] == digests
    context = collector.build_context(
        publications, as_of - collector.dt.timedelta(hours=24), as_of
    )
    assert context["publication_count"] == 3
    assert context["platform"]["timeline"][-1]["version"] == "2.1.3~pre4593"
    assert any(
        item["previous_versions"] == ["2.1.3~pre4617"]
        and item["current_versions"] == ["2.1.3~pre4593"]
        for item in context["package_transitions"]
    )


def test_collection_collapses_adjacent_changed_retry() -> None:
    digest = "d" * 64
    changes = {
        "counts": {"added_files": 1, "removed_files": 0, "version_changes": 0},
        "added": [package("foo", "1.1", "arm64")],
        "removed": [],
        "version_changes": [],
    }
    publications_by_run = {
        401: result(digest, "2026-08-10T05:00:00Z", "2.1.3~pre4617", changes),
        402: result(digest, "2026-08-10T05:10:00Z", "2.1.3~pre4617", changes),
    }

    class RetrySource:
        def list_runs(self, _earliest_started_at: collector.dt.datetime) -> list[dict[str, Any]]:
            return [
                {
                    "id": run_id,
                    "run_started_at": publication["publication"]["published_at"],
                    "html_url": f"https://github.com/sima-neat/sdk/actions/runs/{run_id}",
                }
                for run_id, publication in publications_by_run.items()
            ]

        def read_result(self, run: dict[str, Any]) -> dict[str, Any]:
            return publications_by_run[int(run["id"])]

    as_of = collector.parse_utc("2026-08-11T00:00:00Z")
    publications = collector.load_publications(
        RetrySource(), as_of - collector.dt.timedelta(hours=24), as_of
    )
    assert len(publications) == 1
    assert publications[0]["_run"]["id"] == 401
    context = collector.build_context(
        publications, as_of - collector.dt.timedelta(hours=24), as_of
    )
    assert context["publication_count"] == 1
    assert context["counts"]["added_files"] == 1


def test_platform_summary_reports_anchor_removal() -> None:
    publication = result(
        "c" * 64,
        "2026-08-10T04:00:00Z",
        "ignored",
        {
            "counts": {"removed_files": 1, "version_changes": 0},
            "added": [],
            "removed": [package("simaai-palette-modalix", "2.1.3~pre4617", "arm64")],
            "version_changes": [],
        },
    )
    publication["platform"]["versions"] = []
    publication["_run"] = {
        "id": 301,
        "html_url": "https://github.com/sima-neat/sdk/actions/runs/301",
        "started_at": "2026-08-10T04:00:00Z",
    }

    summary = collector.platform_summary([publication])
    assert summary["previous_version"] == "2.1.3~pre4617"
    assert summary["current_version"] is None
    assert summary["changed"] is True
    assert summary["timeline"][-1]["version"] is None
    context = collector.build_context(
        [publication],
        collector.parse_utc("2026-08-10T00:00:00Z"),
        collector.parse_utc("2026-08-11T00:00:00Z"),
    )
    assert "`2.1.3~pre4617` → removed" in generator.fallback_report(context, 1000)


def test_platform_summary_reports_anchor_addition() -> None:
    publication = result(
        "e" * 64,
        "2026-08-10T04:00:00Z",
        "2.1.3~pre4617",
        {
            "counts": {"added_files": 1, "version_changes": 0},
            "added": [package("simaai-palette-modalix", "2.1.3~pre4617", "arm64")],
            "removed": [],
            "version_changes": [],
        },
    )
    publication["_run"] = {
        "id": 302,
        "html_url": "https://github.com/sima-neat/sdk/actions/runs/302",
        "started_at": "2026-08-10T04:00:00Z",
    }

    summary = collector.platform_summary([publication])
    assert summary["previous_version"] is None
    assert summary["current_version"] == "2.1.3~pre4617"
    assert summary["changed"] is True
    context = collector.build_context(
        [publication],
        collector.parse_utc("2026-08-10T00:00:00Z"),
        collector.parse_utc("2026-08-11T00:00:00Z"),
    )
    assert "Platform: added `2.1.3~pre4617`" in generator.fallback_report(
        context, 1000
    )


def test_scheduled_cutoff_is_stable() -> None:
    schedule = "10 15 * * *"
    delayed = collector.parse_utc("2026-08-11T15:20:00Z")
    early = collector.parse_utc("2026-08-11T15:05:00Z")
    assert collector.utc_text(collector.scheduled_cutoff(delayed, schedule)) == (
        "2026-08-11T15:10:00Z"
    )
    assert collector.utc_text(collector.scheduled_cutoff(early, schedule)) == (
        "2026-08-10T15:10:00Z"
    )


def test_collection_uses_half_open_windows() -> None:
    lower = "2026-08-10T15:10:00Z"
    upper = "2026-08-11T15:10:00Z"
    publications_by_run = {
        501: result("5" * 64, lower, "2.1.3~pre4617", {"counts": {}}),
        502: result("6" * 64, upper, "2.1.3~pre4625", {"counts": {}}),
    }

    class BoundarySource:
        def list_runs(self, _earliest_started_at: collector.dt.datetime) -> list[dict[str, Any]]:
            return [
                {
                    "id": run_id,
                    "run_started_at": publication["publication"]["published_at"],
                    "updated_at": publication["publication"]["published_at"],
                    "html_url": f"https://github.com/sima-neat/sdk/actions/runs/{run_id}",
                }
                for run_id, publication in publications_by_run.items()
            ]

        def read_result(self, run: dict[str, Any]) -> dict[str, Any]:
            return publications_by_run[int(run["id"])]

    publications = collector.load_publications(
        BoundarySource(), collector.parse_utc(lower), collector.parse_utc(upper)
    )
    assert [item["_run"]["id"] for item in publications] == [502]


def test_late_artifact_moves_publication_to_next_window() -> None:
    publication = result(
        "7" * 64,
        "2026-08-10T15:09:00Z",
        "2.1.3~pre4617",
        {"counts": {}, "added": [], "removed": [], "version_changes": []},
    )

    class DelayedArtifactSource:
        def list_runs(self, _earliest_started_at: collector.dt.datetime) -> list[dict[str, Any]]:
            return [
                {
                    "id": 601,
                    "run_started_at": "2026-08-10T14:47:00Z",
                    "updated_at": "2026-08-10T15:12:00Z",
                    "html_url": "https://github.com/sima-neat/sdk/actions/runs/601",
                }
            ]

        def read_result(self, _run: dict[str, Any]) -> dict[str, Any]:
            return publication

    source = DelayedArtifactSource()
    first_cutoff = collector.parse_utc("2026-08-10T15:10:00Z")
    first = collector.load_publications(
        source, first_cutoff - collector.dt.timedelta(hours=24), first_cutoff
    )
    assert first == []

    second_cutoff = collector.parse_utc("2026-08-11T15:10:00Z")
    second = collector.load_publications(
        source, second_cutoff - collector.dt.timedelta(hours=24), second_cutoff
    )
    assert len(second) == 1
    assert second[0]["_run"]["reported_at"] == "2026-08-10T15:12:00Z"


def test_retry_is_deduplicated_across_window_boundary() -> None:
    digest = "8" * 64
    changes = {
        "counts": {"added_files": 1},
        "added": [package("foo", "1.1", "arm64")],
        "removed": [],
        "version_changes": [],
    }
    publications_by_run = {
        701: result(digest, "2026-08-10T15:00:00Z", "2.1.3~pre4617", changes),
        702: result(digest, "2026-08-10T15:15:00Z", "2.1.3~pre4617", changes),
    }
    completion_by_run = {
        701: "2026-08-10T15:09:00Z",
        702: "2026-08-10T15:20:00Z",
    }

    class CrossWindowRetrySource:
        def list_runs(self, _earliest_started_at: collector.dt.datetime) -> list[dict[str, Any]]:
            return [
                {
                    "id": run_id,
                    "run_started_at": publication["publication"]["published_at"],
                    "updated_at": completion_by_run[run_id],
                    "html_url": f"https://github.com/sima-neat/sdk/actions/runs/{run_id}",
                }
                for run_id, publication in publications_by_run.items()
            ]

        def read_result(self, run: dict[str, Any]) -> dict[str, Any]:
            return publications_by_run[int(run["id"])]

    cutoff = collector.parse_utc("2026-08-10T15:10:00Z")
    first = collector.load_publications(
        CrossWindowRetrySource(), cutoff - collector.dt.timedelta(hours=24), cutoff
    )
    assert [item["_run"]["id"] for item in first] == [701]

    next_cutoff = cutoff + collector.dt.timedelta(hours=24)
    second = collector.load_publications(
        CrossWindowRetrySource(), cutoff, next_cutoff
    )
    assert second == []


def test_failed_run_after_publication_is_included() -> None:
    published = result(
        "4" * 64,
        "2026-08-10T12:05:00Z",
        "2.1.3~pre4617",
        {"counts": {}, "added": [], "removed": [], "version_changes": []},
    )

    class FailedRunSource:
        def list_runs(self, _earliest_started_at: collector.dt.datetime) -> list[dict[str, Any]]:
            return [
                {
                    "id": 201,
                    "conclusion": "failure",
                    "run_started_at": "2026-08-10T12:00:00Z",
                    "html_url": "https://github.com/sima-neat/sdk/actions/runs/201",
                }
            ]

        def read_result(self, _run: dict[str, Any]) -> dict[str, Any]:
            return published

    as_of = collector.parse_utc("2026-08-11T00:00:00Z")
    publications = collector.load_publications(
        FailedRunSource(), as_of - collector.dt.timedelta(hours=24), as_of
    )
    assert len(publications) == 1
    assert publications[0]["_run"]["id"] == 201


def test_expired_replay_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "runs.json").write_text("[]\n", encoding="utf-8")
        original_argv = sys.argv
        sys.argv = [
            "collect-debian-mirror-summary.py",
            "--fixture-root",
            str(root),
            "--window-hours",
            "24",
            "--as-of",
            "2020-01-02T00:00:00Z",
            "--output",
            str(root / "context.json"),
        ]
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    collector.main()
                except SystemExit as error:
                    assert error.code == 2
                else:
                    raise AssertionError("expired replay window was accepted")
        finally:
            sys.argv = original_argv


def test_github_run_query_is_time_bounded() -> None:
    source = collector.GithubSource("sima-neat/sdk", "sync.yml")
    calls: list[list[str]] = []

    def fake_run_json(arguments: list[str]) -> list[dict[str, Any]]:
        calls.append(arguments)
        return [{"workflow_runs": []}]

    source._run_json = fake_run_json
    earliest = collector.parse_utc("2026-08-09T02:10:00Z")
    assert source.list_runs(earliest) == []
    assert calls == [
        [
            "--paginate",
            "--slurp",
            "repos/sima-neat/sdk/actions/workflows/sync.yml/runs?"
            "status=completed&created=%3E%3D2026-08-09T02%3A10%3A00Z&per_page=100",
        ]
    ]


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
    test_agate_platform_summary_and_rendering()
    test_platform_version_validation()
    test_collection_and_fallback()
    test_platform_summary_preserves_earliest_baseline()
    test_collection_preserves_digest_rollback()
    test_collection_collapses_adjacent_changed_retry()
    test_platform_summary_reports_anchor_removal()
    test_platform_summary_reports_anchor_addition()
    test_scheduled_cutoff_is_stable()
    test_collection_uses_half_open_windows()
    test_late_artifact_moves_publication_to_next_window()
    test_retry_is_deduplicated_across_window_boundary()
    test_failed_run_after_publication_is_included()
    test_expired_replay_is_rejected()
    test_github_run_query_is_time_bounded()
    test_slack_validation_and_dry_run()
    print("Debian mirror summary tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
