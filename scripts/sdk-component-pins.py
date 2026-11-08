#!/usr/bin/env python3
"""Validate editor pins and emit shell assignments for the Docker install layer."""
import json
import re
import sys


def assignments(manifest):
    component = manifest["code-server"]
    version = component["version"]
    if not isinstance(version, str) or not re.fullmatch(r"4\.[0-9]+\.[0-9]+", version):
        raise ValueError("code-server.version must be an exact 4.x release")
    result = [f"CODE_SERVER_VERSION={version}"]
    for arch in ("amd64", "arm64"):
        checksum = component["sha256"][arch]
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError(f"code-server.sha256.{arch} must be a SHA-256 digest")
        result.append(f"CODE_SERVER_SHA256_{arch.upper()}={checksum}")
    return "\n".join(result)


if __name__ == "__main__":
    try:
        with open(sys.argv[1], encoding="utf-8") as source:
            print(assignments(json.load(source)))
    except (KeyError, ValueError, TypeError, OSError) as error:
        sys.exit(f"Invalid SDK component pins: {error}")
