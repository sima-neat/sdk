#!/usr/bin/env python3
"""Validate package indexes and every package object in a Debian mirror."""

from __future__ import annotations

import argparse
import bz2
import concurrent.futures
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path
import sys
from typing import Iterable, TextIO


INDEX_NAMES = ("Packages", "Packages.xz", "Packages.gz", "Packages.bz2")


def open_index(path: Path) -> TextIO:
    if path.suffix == ".xz":
        return lzma.open(path, "rt", encoding="utf-8", errors="strict")
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="strict")
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="strict")
    return path.open("r", encoding="utf-8", errors="strict")


def parse_control_records(lines: Iterable[str]) -> Iterable[dict[str, str]]:
    record: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line:
            if record:
                yield record
                record = {}
                current_key = None
            continue
        if line[0].isspace():
            if current_key is not None:
                record[current_key] += "\n" + line
            continue
        if ":" not in line:
            raise ValueError(f"invalid control-file line: {line!r}")
        current_key, value = line.split(":", 1)
        record[current_key] = value.lstrip()
    if record:
        yield record


def find_index(repository: Path, suite: str, component: str, architecture: str) -> Path:
    directory = repository / "dists" / suite / component / f"binary-{architecture}"
    for name in INDEX_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no Packages index found under {directory}")


def package_metadata(
    repository: Path, suite: str, component: str, architectures: list[str]
) -> dict[str, dict[str, object]]:
    packages: dict[str, dict[str, object]] = {}
    for architecture in architectures:
        index_path = find_index(repository, suite, component, architecture)
        with open_index(index_path) as package_index:
            for ordinal, record in enumerate(parse_control_records(package_index), start=1):
                missing = {
                    "Package", "Version", "Architecture", "Filename", "Size", "SHA256"
                } - record.keys()
                if missing:
                    raise ValueError(
                        f"{index_path}: record {ordinal} is missing {sorted(missing)}"
                    )
                filename = record["Filename"]
                relative_path = Path(filename)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ValueError(f"unsafe package filename in {index_path}: {filename}")
                metadata: dict[str, object] = {
                    "package": record["Package"],
                    "version": record["Version"],
                    "architecture": record["Architecture"],
                    "filename": filename,
                    "size": int(record["Size"]),
                    "sha256": record["SHA256"].lower(),
                }
                previous = packages.setdefault(filename, metadata)
                if previous != metadata:
                    raise ValueError(f"conflicting metadata for {filename}")
    return packages


def validate_package(
    repository: Path, item: tuple[str, dict[str, object]]
) -> tuple[str, int]:
    filename, metadata = item
    expected_size = int(metadata["size"])
    expected_sha256 = str(metadata["sha256"])
    package_path = repository / filename
    if not package_path.is_file():
        raise FileNotFoundError(f"referenced package is missing: {filename}")
    actual_size = package_path.stat().st_size
    if actual_size != expected_size:
        raise ValueError(
            f"size mismatch for {filename}: expected {expected_size}, got {actual_size}"
        )
    digest = hashlib.sha256()
    with package_path.open("rb") as package_file:
        for chunk in iter(lambda: package_file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"SHA256 mismatch for {filename}: expected {expected_sha256}, got {actual_sha256}"
        )
    return filename, actual_size


def validate_repository(
    repository: Path,
    suite: str,
    component: str,
    architectures: list[str],
    workers: int,
) -> dict[str, object]:
    inrelease = repository / "dists" / suite / "InRelease"
    if not inrelease.is_file():
        raise FileNotFoundError(f"repository metadata is missing: {inrelease}")

    packages = package_metadata(repository, suite, component, architectures)
    if not packages:
        raise ValueError("package indexes did not reference any packages")

    total_bytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(validate_package, repository, item) for item in packages.items()]
        for future in concurrent.futures.as_completed(futures):
            _, package_size = future.result()
            total_bytes += package_size

    return {
        "architectures": architectures,
        "component": component,
        "package_count": len(packages),
        "packages": sorted(packages.values(), key=lambda package: str(package["filename"])),
        "suite": suite,
        "total_bytes": total_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--suite", default="bookworm")
    parser.add_argument("--component", default="non-free")
    parser.add_argument(
        "--architectures", default="arm64,arc,armhf,i386,amd64"
    )
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")
    architectures = [value.strip() for value in args.architectures.split(",") if value.strip()]
    if not architectures:
        parser.error("--architectures must not be empty")

    try:
        result = validate_repository(
            args.repository.resolve(),
            args.suite,
            args.component,
            architectures,
            args.workers,
        )
    except (OSError, ValueError) as error:
        print(f"mirror validation failed: {error}", file=sys.stderr)
        return 1

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
