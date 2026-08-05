#!/usr/bin/env python3
"""Prepare an unsigned, Acquire-By-Hash APT distribution for publication."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import shutil
from pathlib import Path, PurePosixPath


CHECKSUM_HEADERS = {"MD5Sum:", "SHA1:", "SHA256:", "SHA512:"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
HASH_ALGORITHMS = {
    "MD5Sum:": "md5",
    "SHA1:": "sha1",
    "SHA256:": "sha256",
    "SHA512:": "sha512",
}
BY_HASH_NAMES = {
    algorithm: header.removesuffix(":")
    for header, algorithm in HASH_ALGORITHMS.items()
}


def safe_relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe Release path: {value}")
    return Path(*path.parts)


def file_digests(path: Path, algorithms: set[str]) -> dict[str, str]:
    digests = {
        algorithm: hashlib.new(algorithm, usedforsecurity=False)
        for algorithm in algorithms
    }
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            for digest in digests.values():
                digest.update(chunk)
    return {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}


def materialize_uncompressed_package_indexes(
    suite_dir: Path, lines: list[str]
) -> int:
    """Restore logical Packages indexes when only Packages.gz was mirrored."""
    checksum_section: str | None = None
    materialized = 0

    for line in lines:
        if line in CHECKSUM_HEADERS:
            checksum_section = line
            continue
        if checksum_section is None or not line.startswith(" "):
            checksum_section = None
            continue
        if checksum_section != "SHA256:":
            continue

        fields = line.split(maxsplit=2)
        if len(fields) != 3:
            raise ValueError(f"malformed {checksum_section} entry: {line}")
        expected_digest, expected_size_text, relative_text = fields
        relative_path = safe_relative_path(relative_text)
        if relative_path.name != "Packages":
            continue

        destination = suite_dir / relative_path
        if destination.is_file():
            continue

        compressed_source = destination.with_name("Packages.gz")
        if not compressed_source.is_file():
            continue
        if not SHA256_RE.fullmatch(expected_digest):
            raise ValueError(f"invalid SHA256 digest for {relative_text}")
        try:
            expected_size = int(expected_size_text)
        except ValueError as error:
            raise ValueError(
                f"invalid size for {relative_text}: {expected_size_text}"
            ) from error

        temporary = destination.with_name("Packages.tmp")
        try:
            with gzip.open(compressed_source, "rb") as source, temporary.open(
                "wb"
            ) as output:
                shutil.copyfileobj(source, output)
            actual_size = temporary.stat().st_size
            actual_digest = file_digests(temporary, {"sha256"})["sha256"]
            if (
                actual_size != expected_size
                or actual_digest != expected_digest.lower()
            ):
                raise ValueError(
                    f"decompressed index mismatch for {relative_text}: "
                    f"expected {expected_digest.lower()}/{expected_size}, "
                    f"got {actual_digest}/{actual_size}"
                )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        materialized += 1

    return materialized


def prepare_distribution(dists_root: Path, suite: str) -> tuple[int, int]:
    suite_dir = dists_root / suite
    release_path = suite_dir / "Release"
    lines = release_path.read_text(encoding="utf-8").splitlines()

    materialize_uncompressed_package_indexes(suite_dir, lines)

    output: list[str] = []
    checksum_entries: dict[Path, dict[str, tuple[str, int]]] = {}
    checksum_section: str | None = None
    acquire_by_hash_seen = False
    checksum_seen = False

    for line in lines:
        if line.startswith("Acquire-By-Hash:"):
            if not acquire_by_hash_seen:
                output.append("Acquire-By-Hash: yes")
                acquire_by_hash_seen = True
            continue

        if line in CHECKSUM_HEADERS:
            if not checksum_seen and not acquire_by_hash_seen:
                output.append("Acquire-By-Hash: yes")
                acquire_by_hash_seen = True
            checksum_seen = True
            checksum_section = line
            output.append(line)
            continue

        if checksum_section is not None and line.startswith(" "):
            fields = line.split(maxsplit=2)
            if len(fields) != 3:
                raise ValueError(f"malformed {checksum_section} entry: {line}")
            digest, size_text, relative_text = fields
            relative_path = safe_relative_path(relative_text)
            source = suite_dir / relative_path

            # debmirror --nosource intentionally omits source indexes. Remove
            # checksum records for any files that are not in the binary mirror.
            if not source.is_file():
                continue

            output.append(line)
            algorithm = HASH_ALGORITHMS[checksum_section]
            if checksum_section == "SHA256:" and not SHA256_RE.fullmatch(digest):
                raise ValueError(f"invalid SHA256 digest for {relative_text}")
            try:
                size = int(size_text)
            except ValueError as error:
                raise ValueError(
                    f"invalid size for {relative_text}: {size_text}"
                ) from error
            checksum_entries.setdefault(relative_path, {})[algorithm] = (
                digest.lower(),
                size,
            )
            continue

        checksum_section = None
        output.append(line)

    if not checksum_seen or not checksum_entries:
        raise ValueError("Release has no publishable checksum entries")

    total_bytes = 0
    for relative_path, expected_checksums in checksum_entries.items():
        source = suite_dir / relative_path
        expected_sizes = {size for _, size in expected_checksums.values()}
        if len(expected_sizes) != 1:
            raise ValueError(f"inconsistent sizes for {relative_path}")
        expected_size = expected_sizes.pop()
        actual_size = source.stat().st_size
        if actual_size != expected_size:
            raise ValueError(
                f"size mismatch for {relative_path}: "
                f"expected {expected_size}, got {actual_size}"
            )
        actual_digests = file_digests(source, set(expected_checksums))
        for algorithm, (expected_digest, _) in expected_checksums.items():
            actual_digest = actual_digests[algorithm]
            release_algorithm = BY_HASH_NAMES[algorithm]
            if actual_digest != expected_digest:
                raise ValueError(
                    f"{release_algorithm} mismatch for {relative_path}: "
                    f"expected {expected_digest}, got {actual_digest}"
                )

            destination = (
                source.parent / "by-hash" / release_algorithm / expected_digest
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, destination)
            except FileExistsError:
                destination_digest = file_digests(destination, {algorithm})[algorithm]
                if destination_digest != expected_digest:
                    raise ValueError(
                        f"incorrect existing by-hash object: {destination}"
                    )
            except OSError:
                shutil.copyfile(source, destination)
        total_bytes += actual_size

    temporary_release = release_path.with_suffix(".tmp")
    temporary_release.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.replace(temporary_release, release_path)

    # The Release file was transformed, so the upstream signatures no longer
    # describe it. Clients explicitly use [trusted=yes] for this test mirror.
    for signature_name in ("InRelease", "Release.gpg"):
        (suite_dir / signature_name).unlink(missing_ok=True)

    return len(checksum_entries), total_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dists_root", type=Path)
    parser.add_argument("--suite", required=True)
    arguments = parser.parse_args()

    count, total_bytes = prepare_distribution(arguments.dists_root, arguments.suite)
    print(f"Prepared {count} by-hash indexes ({total_bytes} bytes)")


if __name__ == "__main__":
    main()
