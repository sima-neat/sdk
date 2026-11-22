#!/usr/bin/env python3
"""Verify setup's installed extensions as the configured editor user.

This only inspects installation; it never repairs a missing extension.
"""
import json
import subprocess
import sys


def validate(expected, listing):
    installed = {}
    for line in listing.splitlines():
        extension_id, separator, version = line.strip().rpartition("@")
        if separator:
            installed[extension_id.lower()] = version
    for extension_id in ("openai.chatgpt", "anthropic.claude-code"):
        version = expected["extensions"][extension_id]
        if installed.get(extension_id) != version:
            raise ValueError(
                f"{extension_id}: expected {version}, installed "
                f"{installed.get(extension_id, 'missing')}"
            )
    if "sima-neat.sima-neat" not in installed:
        raise ValueError("SiMa Neat extension is missing")
    return installed


def main():
    expected = json.loads(subprocess.check_output(
        ["sdk-components", "resolve", "--json"], text=True
    ))
    if expected.get("available") is not True:
        raise ValueError("SDK qualified component versions are unavailable")
    listing = subprocess.check_output([
        "/opt/code-server/bin/code-server", "--config", "/dev/null",
        "--extensions-dir", sys.argv[1], "--list-extensions", "--show-versions",
    ], text=True)
    installed = validate(expected, listing)
    for extension_id in ("sima-neat.sima-neat", "openai.chatgpt", "anthropic.claude-code"):
        print(f"Verified setup extension: {extension_id}@{installed[extension_id]}")


if __name__ == "__main__":
    main()
