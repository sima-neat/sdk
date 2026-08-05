#!/usr/bin/env python3
"""Prepare an unsigned, Acquire-By-Hash APT distribution for publication."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
from pathlib import Path, PurePosixPath


CHECKSUM_HEADERS = {"MD5Sum:", "SHA1:", "SHA256:", "SHA512:"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def safe_relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe Release path: {value}")
    return Path(*path.parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_distribution(dists_root: Path, suite: str) -> tuple[int, int]:
    suite_dir = dists_root / suite
    release_path = suite_dir / "Release"
    lines = release_path.read_text(encoding="utf-8").splitlines()

    output: list[str] = []
    sha256_entries: list[tuple[str, int, Path]] = []
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
            if checksum_section == "SHA256:":
                if not SHA256_RE.fullmatch(digest):
                    raise ValueError(f"invalid SHA256 digest for {relative_text}")
                try:
                    size = int(size_text)
                except ValueError as error:
                    raise ValueError(
                        f"invalid size for {relative_text}: {size_text}"
                    ) from error
                sha256_entries.append((digest.lower(), size, relative_path))
            continue

        checksum_section = None
        output.append(line)

    if not checksum_seen or not sha256_entries:
        raise ValueError("Release has no publishable SHA256 entries")

    total_bytes = 0
    for expected_digest, expected_size, relative_path in sha256_entries:
        source = suite_dir / relative_path
        actual_size = source.stat().st_size
        if actual_size != expected_size:
            raise ValueError(
                f"size mismatch for {relative_path}: "
                f"expected {expected_size}, got {actual_size}"
            )
        actual_digest = sha256_file(source)
        if actual_digest != expected_digest:
            raise ValueError(
                f"SHA256 mismatch for {relative_path}: "
                f"expected {expected_digest}, got {actual_digest}"
            )

        destination = source.parent / "by-hash" / "SHA256" / expected_digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
        except FileExistsError:
            if sha256_file(destination) != expected_digest:
                raise ValueError(f"incorrect existing by-hash object: {destination}")
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

    return len(sha256_entries), total_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dists_root", type=Path)
    parser.add_argument("--suite", required=True)
    arguments = parser.parse_args()

    count, total_bytes = prepare_distribution(arguments.dists_root, arguments.suite)
    print(f"Prepared {count} by-hash indexes ({total_bytes} bytes)")


if __name__ == "__main__":
    main()
