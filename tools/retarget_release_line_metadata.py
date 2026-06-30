#!/usr/bin/env python3
"""Retarget an SDK release-line install stub to a tagged SDK image."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def clean_path_part(raw: str, fallback: str) -> str:
    value = raw.strip() or fallback
    value = value.replace("/", "-")
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip(".-")
    if not value:
        raise SystemExit(f"Invalid path component: {raw!r}")
    return value


def s3_cp_args(sse_kms_key_id: str) -> list[str]:
    args = ["--sse", "aws:kms"]
    if sse_kms_key_id:
        args.extend(["--sse-kms-key-id", sse_kms_key_id])
    return args


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict, indent: int) -> None:
    path.write_text(json.dumps(data, indent=indent) + "\n", encoding="utf-8")


def retarget_metadata_resource(metadata_path: Path, image_resource: str) -> None:
    metadata = load_json(metadata_path)
    resources = metadata.get("resources")
    if not isinstance(resources, list):
        raise SystemExit("metadata.json does not contain a resources list")

    replaced = False
    updated_resources = []
    for resource in resources:
        if isinstance(resource, str) and re.fullmatch(r"ghcr:sima-neat/sdk:[^\s]+", resource):
            updated_resources.append(image_resource)
            replaced = True
        else:
            updated_resources.append(resource)

    if not replaced:
        raise SystemExit("metadata.json does not contain a ghcr:sima-neat/sdk:* resource")

    metadata["resources"] = updated_resources
    write_json(metadata_path, metadata, indent=4)


def update_manifest_metadata_entry(manifest_path: Path, metadata_path: Path) -> None:
    manifest = load_json(manifest_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit("manifest.json does not contain an artifacts list")

    metadata_sha = sha256_file(metadata_path)
    metadata_size = metadata_path.stat().st_size
    for artifact in artifacts:
        if artifact.get("path") == "metadata.json":
            artifact["sha256"] = metadata_sha
            artifact["size"] = metadata_size
            break
    else:
        raise SystemExit("manifest.json does not contain metadata.json artifact entry")

    write_json(manifest_path, manifest, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retarget the existing SDK release-line metadata.json resource to a tagged SDK image "
            "without changing latest.tag."
        )
    )
    parser.add_argument("--bucket", required=True, help="Vulcan artifact S3 bucket.")
    parser.add_argument("--repository", default="sdk", help="Repository key under the artifact bucket.")
    parser.add_argument("--release-line-ref", required=True, help="Release-line ref, e.g. release-2.1.")
    parser.add_argument(
        "--image-resource",
        required=True,
        help="Tagged SDK image resource, e.g. ghcr:sima-neat/sdk:v2.1.2.3.",
    )
    parser.add_argument("--sse-kms-key-id", default="", help="Optional KMS key for S3 uploads.")
    parser.add_argument(
        "--cloudfront-distribution-id",
        default="",
        help="Optional CloudFront distribution to invalidate after updating metadata.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.image_resource.startswith("ghcr:sima-neat/sdk:"):
        raise SystemExit(f"--image-resource must target ghcr:sima-neat/sdk, got: {args.image_resource}")

    repo_name = clean_path_part(args.repository, "repository")
    encoded_branch_key = quote(args.release_line_ref, safe="")

    with tempfile.TemporaryDirectory(prefix="sdk-release-line-") as tmp:
        work_dir = Path(tmp)
        latest_path = work_dir / "latest.tag"
        run(
            "aws",
            "s3",
            "cp",
            f"s3://{args.bucket}/{repo_name}/{encoded_branch_key}/latest.tag",
            str(latest_path),
        )

        latest_tag = latest_path.read_text(encoding="utf-8").strip()
        if not latest_tag:
            raise SystemExit(f"Empty latest.tag for {repo_name}/{args.release_line_ref}")

        prefix = f"{repo_name}/{encoded_branch_key}/{latest_tag}"
        metadata_path = work_dir / "metadata.json"
        manifest_path = work_dir / "manifest.json"
        run("aws", "s3", "cp", f"s3://{args.bucket}/{prefix}/metadata.json", str(metadata_path))
        run("aws", "s3", "cp", f"s3://{args.bucket}/{prefix}/manifest.json", str(manifest_path))

        retarget_metadata_resource(metadata_path, args.image_resource)
        update_manifest_metadata_entry(manifest_path, metadata_path)

        upload_args = s3_cp_args(args.sse_kms_key_id)
        run(
            "aws",
            "s3",
            "cp",
            str(metadata_path),
            f"s3://{args.bucket}/{prefix}/metadata.json",
            "--content-type",
            "application/json",
            *upload_args,
        )
        run(
            "aws",
            "s3",
            "cp",
            str(manifest_path),
            f"s3://{args.bucket}/{prefix}/manifest.json",
            "--content-type",
            "application/json",
            *upload_args,
        )

        if args.cloudfront_distribution_id:
            run(
                "aws",
                "cloudfront",
                "create-invalidation",
                "--distribution-id",
                args.cloudfront_distribution_id,
                "--paths",
                f"/{prefix}/metadata.json",
                f"/{prefix}/manifest.json",
            )

        print(f"release_line_ref={args.release_line_ref}")
        print(f"latest_tag={latest_tag}")
        print(f"metadata=s3://{args.bucket}/{prefix}/metadata.json")
        print(f"image_resource={args.image_resource}")


if __name__ == "__main__":
    main()
