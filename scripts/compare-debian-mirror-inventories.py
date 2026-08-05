#!/usr/bin/env python3
"""Compare two validated Debian mirror package inventories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def load_packages(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    packages = document.get("packages")
    if not isinstance(packages, list):
        raise ValueError(f"{path} does not contain a packages array")
    return packages


def compare_inventories(
    previous: list[dict[str, object]], current: list[dict[str, object]], baseline: bool
) -> dict[str, object]:
    previous_by_file = {str(item["filename"]): item for item in previous}
    current_by_file = {str(item["filename"]): item for item in current}

    added = [current_by_file[name] for name in sorted(current_by_file.keys() - previous_by_file)]
    removed = [previous_by_file[name] for name in sorted(previous_by_file.keys() - current_by_file)]

    def versions_by_identity(
        packages: list[dict[str, object]],
    ) -> dict[tuple[str, str], set[str]]:
        result: dict[tuple[str, str], set[str]] = {}
        for package in packages:
            identity = (str(package["package"]), str(package["architecture"]))
            result.setdefault(identity, set()).add(str(package["version"]))
        return result

    previous_versions = versions_by_identity(previous)
    current_versions = versions_by_identity(current)
    version_changes = []
    for identity in sorted(previous_versions.keys() & current_versions):
        before = previous_versions[identity]
        after = current_versions[identity]
        if before != after:
            version_changes.append(
                {
                    "package": identity[0],
                    "architecture": identity[1],
                    "previous_versions": sorted(before),
                    "current_versions": sorted(after),
                }
            )

    return {
        "schema_version": 1,
        "baseline_available": baseline,
        "counts": {
            "added_files": len(added),
            "removed_files": len(removed),
            "version_changes": len(version_changes),
        },
        "added": added,
        "removed": removed,
        "version_changes": version_changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        previous = load_packages(args.previous)
        current = load_packages(args.current)
        result = compare_inventories(previous, current, args.previous is not None)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"inventory comparison failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
