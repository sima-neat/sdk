#!/usr/bin/env python3
"""Update one SDK cache label in Vulcan's production Terraform variables."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


VARIABLE_START = re.compile(r'^variable\s+"runner_sdk_cache_snapshots"\s*\{\s*$')
ALLOWLIST_VARIABLE_START = re.compile(
    r'^variable\s+"runner_default_allowed_sdk_cache_labels"\s*\{\s*$'
)
DEFAULT_MAP_START = re.compile(r"^\s*default\s*=\s*\{\s*$")
DEFAULT_LIST = re.compile(
    r"^(?P<prefix>\s*default\s*=\s*\[)(?P<values>.*)(?P<suffix>]\s*)$"
)
MAP_END = re.compile(r"^\s*}\s*$")
SNAPSHOT_ID = re.compile(r"^snap-[0-9a-f]{8,}$")
SDK_CACHE_LABEL = re.compile(r"^sdk-[0-9]+\.[0-9]+\.[0-9]+-(?:develop|official)$")


def update_snapshot_mapping(
    path: Path, label: str, snapshot_id: str
) -> dict[str, object]:
    if not SDK_CACHE_LABEL.fullmatch(label):
        raise ValueError(
            "label must match sdk-X.Y.Z-develop or sdk-X.Y.Z-official"
        )
    if not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError("snapshot id must look like snap-0123456789abcdef0")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    variable_index = next(
        (
            index
            for index, line in enumerate(lines)
            if VARIABLE_START.match(line.rstrip("\n"))
        ),
        None,
    )
    if variable_index is None:
        raise ValueError('variable "runner_sdk_cache_snapshots" was not found')

    map_start = next(
        (
            index
            for index in range(variable_index + 1, len(lines))
            if DEFAULT_MAP_START.match(lines[index].rstrip("\n"))
        ),
        None,
    )
    if map_start is None:
        raise ValueError("runner_sdk_cache_snapshots default map was not found")

    map_end = next(
        (
            index
            for index in range(map_start + 1, len(lines))
            if MAP_END.match(lines[index].rstrip("\n"))
        ),
        None,
    )
    if map_end is None:
        raise ValueError("runner_sdk_cache_snapshots default map is not closed")

    entry_pattern = re.compile(
        rf'^(?P<indent>\s*)"{re.escape(label)}"(?P<separator>\s*=\s*)'
        rf'"(?P<snapshot>snap-[0-9a-f]+)"(?P<suffix>\s*)$'
    )
    previous_snapshot_id: str | None = None
    mapping_changed = True

    for index in range(map_start + 1, map_end):
        original = lines[index]
        newline = "\n" if original.endswith("\n") else ""
        match = entry_pattern.match(original.rstrip("\n"))
        if match is None:
            continue
        previous_snapshot_id = match.group("snapshot")
        if previous_snapshot_id == snapshot_id:
            mapping_changed = False
        else:
            lines[index] = (
                f'{match.group("indent")}"{label}"{match.group("separator")}"{snapshot_id}"'
                f'{match.group("suffix")}{newline}'
            )
        break
    else:
        lines.insert(map_end, f'    "{label}" = "{snapshot_id}"\n')

    allowlist_variable_index = next(
        (
            index
            for index, line in enumerate(lines)
            if ALLOWLIST_VARIABLE_START.match(line.rstrip("\n"))
        ),
        None,
    )
    if allowlist_variable_index is None:
        raise ValueError(
            'variable "runner_default_allowed_sdk_cache_labels" was not found'
        )

    allowlist_changed = False
    for index in range(allowlist_variable_index + 1, len(lines)):
        original = lines[index]
        match = DEFAULT_LIST.match(original.rstrip("\n"))
        if match is not None:
            labels = re.findall(r'"([^"]+)"', match.group("values"))
            if label not in labels:
                separator = ", " if match.group("values").strip() else ""
                newline = "\n" if original.endswith("\n") else ""
                lines[index] = (
                    f'{match.group("prefix")}{match.group("values")}{separator}'
                    f'"{label}"{match.group("suffix")}{newline}'
                )
                allowlist_changed = True
            break
        if MAP_END.match(original.rstrip("\n")):
            raise ValueError(
                "runner_default_allowed_sdk_cache_labels default list was not found"
            )
    else:
        raise ValueError("runner_default_allowed_sdk_cache_labels is not closed")

    changed = mapping_changed or allowlist_changed
    if changed:
        path.write_text("".join(lines), encoding="utf-8")

    return {
        "label": label,
        "snapshot_id": snapshot_id,
        "previous_snapshot_id": previous_snapshot_id,
        "mapping_changed": mapping_changed,
        "allowlist_changed": allowlist_changed,
        "changed": changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()

    try:
        result = update_snapshot_mapping(args.file, args.label, args.snapshot_id)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
