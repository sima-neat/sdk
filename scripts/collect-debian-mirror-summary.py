#!/usr/bin/env python3
"""Collect mirror-sync result artifacts from GitHub Actions."""

from __future__ import annotations

import argparse
import datetime as dt
from functools import cmp_to_key
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any, Protocol
import urllib.parse
import zipfile


ARTIFACT_PREFIX = "debian-pre-release-mirror-result-"
RESULT_FILENAME = "mirror-sync-result.json"
ANCHOR_PACKAGE = "simaai-palette-modalix"
ANCHOR_ARCHITECTURE = "arm64"
PLATFORM_VERSION_RE = re.compile(
    r"^[0-9]+(?:[.][0-9]+){2}~(?:pre[0-9]+|git[0-9]{12}[.][0-9a-f]+-[0-9]+)$"
)
DISCOVERY_MARGIN = dt.timedelta(hours=13)
ARTIFACT_RETENTION = dt.timedelta(hours=72)


class CollectionError(RuntimeError):
    """Raised when workflow results cannot be enumerated or read."""


class ResultSource(Protocol):
    def list_runs(self, earliest_started_at: dt.datetime) -> list[dict[str, Any]]: ...

    def read_result(self, run: dict[str, Any]) -> dict[str, Any] | None: ...


def parse_utc(value: str) -> dt.datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def utc_text(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def split_debian_version(value: str) -> tuple[int, str, str]:
    epoch_text, separator, remainder = value.partition(":")
    if separator and epoch_text.isdigit():
        epoch = int(epoch_text)
    else:
        epoch = 0
        remainder = value
    upstream, separator, revision = remainder.rpartition("-")
    return (epoch, upstream, revision) if separator else (epoch, remainder, "")


def non_digit_order(character: str) -> int:
    if character == "~":
        return -1
    if not character:
        return 0
    return ord(character) if character.isalpha() else ord(character) + 256


def compare_debian_part(left: str, right: str) -> int:
    left_index = right_index = 0
    while left_index < len(left) or right_index < len(right):
        while (
            (left_index < len(left) and not left[left_index].isdigit())
            or (right_index < len(right) and not right[right_index].isdigit())
        ):
            left_char = left[left_index] if left_index < len(left) and not left[left_index].isdigit() else ""
            right_char = right[right_index] if right_index < len(right) and not right[right_index].isdigit() else ""
            if non_digit_order(left_char) != non_digit_order(right_char):
                return -1 if non_digit_order(left_char) < non_digit_order(right_char) else 1
            left_index += bool(left_char)
            right_index += bool(right_char)
        while left_index < len(left) and left[left_index] == "0":
            left_index += 1
        while right_index < len(right) and right[right_index] == "0":
            right_index += 1
        left_end, right_end = left_index, right_index
        while left_end < len(left) and left[left_end].isdigit():
            left_end += 1
        while right_end < len(right) and right[right_end].isdigit():
            right_end += 1
        left_digits, right_digits = left[left_index:left_end], right[right_index:right_end]
        if len(left_digits) != len(right_digits):
            return -1 if len(left_digits) < len(right_digits) else 1
        if left_digits != right_digits:
            return -1 if left_digits < right_digits else 1
        left_index, right_index = left_end, right_end
    return 0


def compare_debian_versions(left: str, right: str) -> int:
    left_epoch, left_upstream, left_revision = split_debian_version(left)
    right_epoch, right_upstream, right_revision = split_debian_version(right)
    if left_epoch != right_epoch:
        return -1 if left_epoch < right_epoch else 1
    return compare_debian_part(left_upstream, right_upstream) or compare_debian_part(
        left_revision, right_revision
    )


def sorted_versions(values: list[str] | set[str]) -> list[str]:
    return sorted(set(values), key=cmp_to_key(compare_debian_versions))


class GithubSource:
    def __init__(self, repository: str, workflow: str) -> None:
        self.repository = repository
        self.workflow = workflow

    def _run_json(self, arguments: list[str]) -> Any:
        process = subprocess.run(
            ["gh", "api", *arguments], capture_output=True, text=True, check=False
        )
        if process.returncode:
            raise CollectionError(process.stderr.strip() or "gh api failed")
        if "--paginate" not in arguments:
            return json.loads(process.stdout)
        # Older runner installations support --paginate but not --slurp.
        # gh emits one complete JSON document per page; parse that stream here.
        decoder = json.JSONDecoder()
        remaining = process.stdout.lstrip()
        pages = []
        while remaining:
            page, end = decoder.raw_decode(remaining)
            pages.append(page)
            remaining = remaining[end:].lstrip()
        return pages

    def _json(self, endpoint: str) -> dict[str, Any]:
        document = self._run_json([endpoint])
        if not isinstance(document, dict):
            raise CollectionError(f"GitHub returned a non-object for {endpoint}")
        return document

    def list_runs(self, earliest_started_at: dt.datetime) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "status": "completed",
                "created": f">={utc_text(earliest_started_at)}",
                "per_page": 100,
            }
        )
        endpoint = (
            f"repos/{self.repository}/actions/workflows/{self.workflow}/runs"
            f"?{query}"
        )
        pages = self._run_json(["--paginate", endpoint])
        if not isinstance(pages, list):
            raise CollectionError("GitHub returned invalid workflow-run pagination data")
        return [run for page in pages for run in page.get("workflow_runs", [])]

    def read_result(self, run: dict[str, Any]) -> dict[str, Any] | None:
        run_id = int(run["id"])
        artifacts = self._json(
            f"repos/{self.repository}/actions/runs/{run_id}/artifacts?per_page=100"
        ).get("artifacts", [])
        expected_name = f"{ARTIFACT_PREFIX}{run_id}"
        artifact = next(
            (
                item
                for item in artifacts
                if item.get("name") == expected_name and not item.get("expired", False)
            ),
            None,
        )
        if artifact is None:
            return None
        process = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{self.repository}/actions/artifacts/{int(artifact['id'])}/zip",
            ],
            capture_output=True,
            check=False,
        )
        if process.returncode:
            raise CollectionError(process.stderr.decode(errors="replace").strip())
        with zipfile.ZipFile(io.BytesIO(process.stdout)) as archive:
            matches = [
                name
                for name in archive.namelist()
                if PurePosixPath(name).name == RESULT_FILENAME
                and ".." not in PurePosixPath(name).parts
            ]
            if len(matches) != 1:
                raise CollectionError(
                    f"artifact {artifact['id']} contains {len(matches)} {RESULT_FILENAME} files"
                )
            document = json.loads(archive.read(matches[0]))
        if not isinstance(document, dict):
            raise CollectionError(f"artifact {artifact['id']} result is not a JSON object")
        return document


class FixtureSource:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs = json.loads((root / "runs.json").read_text(encoding="utf-8"))

    def list_runs(self, earliest_started_at: dt.datetime) -> list[dict[str, Any]]:
        return [
            run
            for run in self.runs
            if parse_utc(str(run.get("run_started_at") or run.get("created_at")))
            >= earliest_started_at
        ]

    def read_result(self, run: dict[str, Any]) -> dict[str, Any] | None:
        result_file = run.get("result_file")
        if not result_file:
            return None
        document = json.loads((self.root / str(result_file)).read_text(encoding="utf-8"))
        return document if isinstance(document, dict) else None


def load_publications(
    source: ResultSource, since: dt.datetime, as_of: dt.datetime
) -> list[dict[str, Any]]:
    publications: list[dict[str, Any]] = []
    earliest_started_at = since - DISCOVERY_MARGIN
    for run in source.list_runs(earliest_started_at):
        timestamp_text = run.get("run_started_at") or run.get("created_at")
        if not timestamp_text:
            continue
        started_at = parse_utc(str(timestamp_text))
        if started_at < earliest_started_at:
            continue
        completed_text = run.get("updated_at") or timestamp_text
        completed_at = parse_utc(str(completed_text))
        result = source.read_result(run)
        if not result or result.get("result") != "Published":
            continue
        published_text = result.get("publication", {}).get("published_at")
        if not published_text:
            raise CollectionError(f"run {run.get('id')} has no publication timestamp")
        published_at = parse_utc(str(published_text))
        # A result cannot be reported until both the mirror publication and its
        # workflow artifact exist. Assign it to the first half-open digest
        # window whose upper boundary includes that discoverability time. This
        # prevents a pre-cutoff publication from being lost when its workflow
        # finishes after the cutoff.
        reported_at = max(published_at, completed_at)
        if reported_at <= since - DISCOVERY_MARGIN or reported_at > as_of:
            continue
        digest = str(result.get("source", {}).get("inrelease_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CollectionError(f"run {run.get('id')} has an invalid source digest")
        result["_run"] = {
            "id": int(run["id"]),
            "html_url": run.get("html_url"),
            "started_at": utc_text(started_at),
            "completed_at": utc_text(completed_at),
            "reported_at": utc_text(reported_at),
        }
        publications.append(result)

    ordered = sorted(
        publications,
        key=lambda item: (
            parse_utc(str(item["publication"]["published_at"])),
            parse_utc(str(item["_run"]["started_at"])),
        ),
    )
    deduplicated: list[dict[str, Any]] = []
    for publication in ordered:
        digest = str(publication["source"]["inrelease_sha256"])
        if (
            deduplicated
            and digest == deduplicated[-1]["source"]["inrelease_sha256"]
        ):
            # A retry after the Release boundary can emit the same changed
            # report again when publication.json was not updated. Collapse
            # only adjacent identical generations; a nonadjacent A -> B -> A
            # rollback remains visible.
            continue
        deduplicated.append(publication)
    return [
        publication
        for publication in deduplicated
        if parse_utc(str(publication["_run"]["reported_at"])) > since
    ]


def grouped_package_files(publications: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for publication in publications:
        for item in publication.get("changes", {}).get(field, []):
            key = (str(item.get("package", "unknown")), str(item.get("version", "unknown")))
            entry = grouped.setdefault(
                key,
                {"package": key[0], "version": key[1], "architectures": set(), "files": 0},
            )
            entry["architectures"].add(str(item.get("architecture", "unknown")))
            entry["files"] += 1
    return [
        {**entry, "architectures": sorted(entry["architectures"])}
        for _, entry in sorted(grouped.items())
    ]


def grouped_transitions(publications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    for publication in publications:
        digest = str(publication["source"]["inrelease_sha256"])
        for item in publication.get("changes", {}).get("version_changes", []):
            previous = tuple(sorted_versions([str(value) for value in item.get("previous_versions", [])]))
            current = tuple(sorted_versions([str(value) for value in item.get("current_versions", [])]))
            key = (str(item.get("package", "unknown")), previous, current)
            entry = grouped.setdefault(
                key,
                {"package": key[0], "previous_versions": list(previous), "current_versions": list(current), "architectures": set(), "publication_digests": set()},
            )
            entry["architectures"].add(str(item.get("architecture", "unknown")))
            entry["publication_digests"].add(digest)
    return sorted(
        [
            {**entry, "architectures": sorted(entry["architectures"]), "publication_digests": sorted(entry["publication_digests"])}
            for entry in grouped.values()
        ],
        key=lambda entry: (entry["package"], entry["architectures"]),
    )


def platform_summary(publications: list[dict[str, Any]]) -> dict[str, Any]:
    timeline = []
    for publication in publications:
        versions = sorted_versions(
            [
                str(value)
                for value in publication.get("platform", {}).get("versions", [])
                if PLATFORM_VERSION_RE.fullmatch(str(value))
            ]
        )
        timeline.append(
            {
                "published_at": publication["publication"]["published_at"],
                "version": versions[-1] if versions else None,
                "digest": publication["source"]["inrelease_sha256"],
            }
        )
    previous_version = timeline[0]["version"] if timeline else None
    baseline_found = False
    for index, publication in enumerate(publications):
        for item in publication.get("changes", {}).get("version_changes", []):
            if item.get("package") == ANCHOR_PACKAGE and item.get("architecture") in (ANCHOR_ARCHITECTURE, "all"):
                previous = sorted_versions([str(value) for value in item.get("previous_versions", []) if PLATFORM_VERSION_RE.fullmatch(str(value))])
                if previous:
                    previous_version = previous[-1]
                    baseline_found = True
                    break
        if not baseline_found and index == 0:
            removed_versions = sorted_versions(
                [
                    str(item.get("version"))
                    for item in publication.get("changes", {}).get("removed", [])
                    if item.get("package") == ANCHOR_PACKAGE
                    and item.get("architecture") in (ANCHOR_ARCHITECTURE, "all")
                    and PLATFORM_VERSION_RE.fullmatch(str(item.get("version")))
                ]
            )
            if removed_versions:
                previous_version = removed_versions[-1]
                baseline_found = True
            elif any(
                item.get("package") == ANCHOR_PACKAGE
                and item.get("architecture") in (ANCHOR_ARCHITECTURE, "all")
                for item in publication.get("changes", {}).get("added", [])
            ):
                # The first publication introduced the anchor, so its state at
                # the beginning of the reporting window was absent.
                previous_version = None
                baseline_found = True
        if baseline_found:
            break
    current_version = timeline[-1]["version"] if timeline else None
    return {
        "anchor_package": ANCHOR_PACKAGE,
        "architecture": ANCHOR_ARCHITECTURE,
        "previous_version": previous_version,
        "current_version": current_version,
        "changed": bool(timeline) and previous_version != current_version,
        "timeline": timeline,
    }


def build_context(publications: list[dict[str, Any]], since: dt.datetime, as_of: dt.datetime) -> dict[str, Any]:
    transitions = grouped_transitions(publications)
    added = grouped_package_files(publications, "added")
    removed = grouped_package_files(publications, "removed")
    reports = [
        {
            "digest": item["source"]["inrelease_sha256"],
            "published_at": item["publication"]["published_at"],
            "reported_at": item["_run"].get(
                "reported_at", item["publication"]["published_at"]
            ),
            "source_date": item["source"].get("date"),
            "workflow_run_url": item["_run"].get("html_url"),
            "counts": item.get("changes", {}).get("counts", {}),
        }
        for item in publications
    ]
    return {
        "schema_version": 1,
        "window": {"since": utc_text(since), "as_of": utc_text(as_of), "hours": round((as_of - since).total_seconds() / 3600, 3)},
        "publication_count": len(publications),
        "platform": platform_summary(publications),
        "counts": {"package_transitions": len(transitions), "added_package_groups": len(added), "removed_package_groups": len(removed), "added_files": sum(int(item["files"]) for item in added), "removed_files": sum(int(item["files"]) for item in removed)},
        "package_transitions": transitions,
        "added_packages": added,
        "removed_packages": removed,
        "reports": reports,
    }


def scheduled_cutoff(now: dt.datetime, schedule: str) -> dt.datetime:
    fields = schedule.split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        raise ValueError(f"unsupported summary schedule: {schedule}")
    try:
        minute = int(fields[0])
        hour = int(fields[1])
    except ValueError as error:
        raise ValueError(f"unsupported summary schedule: {schedule}") from error
    if not 0 <= minute <= 59 or not 0 <= hour <= 23:
        raise ValueError(f"unsupported summary schedule: {schedule}")
    cutoff = now.astimezone(dt.timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if cutoff > now:
        cutoff -= dt.timedelta(days=1)
    return cutoff


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repository", default=None)
    source.add_argument("--fixture-root", type=Path)
    parser.add_argument("--workflow", default="sync-debian-pre-release-mirror.yml")
    parser.add_argument("--window-hours", type=int, default=24)
    cutoff = parser.add_mutually_exclusive_group()
    cutoff.add_argument("--as-of")
    cutoff.add_argument("--schedule")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.window_hours < 1 or args.window_hours > 72:
        parser.error("--window-hours must be between 1 and 72")
    now = dt.datetime.now(dt.timezone.utc)
    as_of = (
        parse_utc(args.as_of)
        if args.as_of
        else scheduled_cutoff(now, args.schedule)
        if args.schedule
        else now
    )
    since = as_of - dt.timedelta(hours=args.window_hours)
    if as_of > now + dt.timedelta(minutes=5):
        parser.error("--as-of cannot be in the future")
    if since < now - ARTIFACT_RETENTION:
        parser.error(
            "the requested replay window starts outside the 72-hour artifact retention period"
        )
    result_source: ResultSource = FixtureSource(args.fixture_root) if args.fixture_root else GithubSource(args.repository, args.workflow)
    try:
        publications = load_publications(result_source, since, as_of)
        context = build_context(publications, since, as_of)
    except (CollectionError, OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(f"mirror summary collection failed: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
