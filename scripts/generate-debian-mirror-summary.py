#!/usr/bin/env python3
"""Generate a concise Slack digest from normalized mirror-change context."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def slack_text(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fallback_report(context: dict[str, Any], max_characters: int) -> str:
    window = context.get("window", {})
    platform = context.get("platform", {})
    counts = context.get("counts", {})
    publication_count = int(context.get("publication_count", 0))
    previous = platform.get("previous_version")
    current = platform.get("current_version")

    lines = [
        f"🗞️ *Pre-release mirror summary — last {window.get('hours', 24):g} hours*",
        "",
    ]
    platform_observed = bool(platform.get("timeline"))
    if previous and current and previous != current:
        lines.append(f"• Platform: `{slack_text(previous)}` → `{slack_text(current)}`")
    elif previous and platform_observed and current is None:
        lines.append(f"• Platform: `{slack_text(previous)}` → removed")
    elif platform.get("changed") and previous is None and current:
        lines.append(f"• Platform: added `{slack_text(current)}`")
    elif current:
        lines.append(f"• Platform: `{slack_text(current)}` (unchanged in window)")
    elif platform_observed:
        lines.append("• Platform: anchor package absent in latest publication")
    else:
        lines.append("• Platform: no platform publication detected in window")
    lines.extend(
        [
            f"*{publication_count} publications · {int(counts.get('package_transitions', 0))} package transitions*",
            f"{int(counts.get('added_files', 0))} package files added · "
            f"{int(counts.get('removed_files', 0))} removed from indexes",
        ]
    )
    if not publication_count:
        lines.extend(["", "No mirror publications were found in this window."])

    reports = context.get("reports", [])
    links = []
    for index, report in enumerate(reports[-3:], start=max(1, len(reports) - 2)):
        url = report.get("workflow_run_url") or report.get("change_report_url")
        if url:
            links.append(f"<{url}|report {index}>")
    if links:
        lines.extend(["", f"Source: {' · '.join(links)}"])

    rendered = "\n".join(lines).strip()
    if len(rendered) > max_characters:
        rendered = rendered[: max_characters - 25].rstrip() + "\n…summary truncated"
    return rendered + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-characters", type=int, default=3000)
    args = parser.parse_args()
    if args.max_characters < 500 or args.max_characters > 10000:
        parser.error("--max-characters must be between 500 and 10000")

    context = json.loads(args.context.read_text(encoding="utf-8"))
    report = fallback_report(context, args.max_characters)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
