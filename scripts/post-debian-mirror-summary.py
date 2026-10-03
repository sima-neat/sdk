#!/usr/bin/env python3
"""Post a generated Debian mirror digest to Slack."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SLACK_API_URL = "https://slack.com/api/chat.postMessage"
SLACK_API_ROOT = "https://slack.com/api/"


def post_message(token: str, channel: str, text: str, *, blocks: list[dict] | None = None) -> dict[str, object]:
    payload = json.dumps(
        {
            "channel": channel,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
            **({"blocks": blocks} if blocks is not None else {}),
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


def slack_api(token: str, method: str, payload: dict[str, object], *, form_encoded: bool = False) -> dict[str, object]:
    if form_encoded:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        content_type = "application/x-www-form-urlencoded; charset=utf-8"
    else:
        data = json.dumps(payload).encode("utf-8")
        content_type = "application/json; charset=utf-8"
    request = urllib.request.Request(
        SLACK_API_ROOT + method,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Slack {method} request failed: {error}") from error
    if not document.get("ok"):
        messages = document.get("response_metadata", {}).get("messages", [])
        detail = "; ".join(str(message) for message in messages[:3]) if isinstance(messages, list) else ""
        suffix = f" ({detail})" if detail else ""
        raise RuntimeError(
            f"Slack {method} rejected the request: {document.get('error', 'unknown_error')}{suffix}"
        )
    return document


def upload_file(token: str, channel: str, path: Path, *, thread_ts: str, title: str) -> dict[str, object]:
    """Upload a file through Slack's supported external upload sequence."""
    data = path.read_bytes()
    upload = slack_api(
        token,
        "files.getUploadURLExternal",
        {"filename": path.name, "length": len(data)},
        # This method's simple scalar arguments are most compatible with
        # Slack workspaces when sent using its documented form encoding.
        form_encoded=True,
    )
    upload_url, file_id = upload.get("upload_url"), upload.get("file_id")
    if not isinstance(upload_url, str) or not isinstance(file_id, str):
        raise RuntimeError("Slack files.getUploadURLExternal returned no upload URL or file ID")
    parsed = urllib.parse.urlparse(upload_url)
    if parsed.scheme != "https" or parsed.hostname not in {"files.slack.com", "slack-files.com"}:
        raise RuntimeError("Slack returned an unexpected file upload URL")
    request = urllib.request.Request(
        upload_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                raise RuntimeError(f"Slack file upload failed with HTTP {response.status}")
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Slack file upload failed: {error}") from error
    return slack_api(token, "files.completeUploadExternal", {
        "files": [{"id": file_id, "title": title}],
        "channel_id": channel,
        "thread_ts": thread_ts,
    })


def digest_blocks(text: str) -> list[dict]:
    # Separate paragraphs preserve links and keep each section below Slack's
    # 3,000-character limit. The generated digest is deliberately short.
    sections = text.split("\n\n")
    if any(len(section) > 3000 for section in sections):
        raise RuntimeError("Mirror digest paragraph exceeds Slack's section limit")
    return [
        {"type": "divider"},
        *[{"type": "section", "text": {"type": "mrkdwn", "text": section}}
          for section in sections if section],
        {"type": "divider"},
    ]


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
        response = post_message(token, channel, text, blocks=digest_blocks(text))
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Posted mirror summary to Slack (timestamp {response.get('ts', 'unknown')}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
