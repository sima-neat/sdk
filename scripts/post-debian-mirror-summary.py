#!/usr/bin/env python3
"""Post a generated Debian mirror digest to Slack."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request


SLACK_API_URL = "https://slack.com/api/chat.postMessage"


def post_message(token: str, channel: str, text: str) -> dict[str, object]:
    payload = json.dumps(
        {
            "channel": channel,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        SLACK_API_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Slack request failed: {error}") from error
    if not document.get("ok"):
        raise RuntimeError(f"Slack rejected the message: {document.get('error', 'unknown_error')}")
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    text = args.report.read_text(encoding="utf-8").strip()
    if not text:
        print("mirror summary report is empty", file=sys.stderr)
        return 1
    if args.dry_run:
        print("DRY RUN: would post the following mirror summary to Slack:\n")
        print(text)
        return 0

    token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_CHANNEL_ID", "")
    if not token or not channel:
        print("SLACK_BOT_TOKEN and SLACK_CHANNEL_ID are required", file=sys.stderr)
        return 1
    try:
        response = post_message(token, channel, text)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Posted mirror summary to Slack (timestamp {response.get('ts', 'unknown')}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
