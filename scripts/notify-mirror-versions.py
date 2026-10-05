#!/usr/bin/env python3
"""Notify Slack of newly mirrored platform versions, with a persistent outbox."""
import argparse
import html
import json
import os
import re
import runpy
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

KINDS = {'apt': 'APT', 'packages': 'APT package changes', 'images': 'Device images', 'sysroots': '📦 Sysroot package availability'}
TABLE_CELL_LIMIT = 2000
TABLE_TEXT_LIMIT = 10000
TABLE_CELL_OVERFLOW = '… (see workflow report)'
IMAGE_BUILD_RE = re.compile(r'3[.]0[.]0_daily_[A-Za-z0-9_-]+_B[0-9]+')


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(state, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def load_report(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def sysroot_events(report):
    events = []
    for item in report.get('builds', []):
        internal, external = item['internal']['status'], item['external']['status']
        if external == 'available':
            detail = '✅ Matching external platform package set is available.'
        elif external == 'unknown':
            detail = '❔ External mirror check failed; availability is unknown.'
        elif internal == 'available':
            detail = '⏳ Available internally; external mirror is not ready. You may need to wait for synchronization.'
        elif internal == 'unknown':
            detail = '❔ External package set is not ready; internal availability is unknown.'
        else:
            detail = '⚠️ Matching package set is not yet complete internally or externally.'
        events.append(f"{item['image']}: {detail} (internal: {internal}; external: {external}; package-index check only)")
    return events


def collect(apt, images, readiness=None):
    # Preview-only runs must never announce versions as available.
    result = {
        'apt': [],
        'images': images.get('copied_versions', []) if images.get('result') == 'Published' else [],
    }
    if readiness and images.get('result') == 'Published':
        result['sysroots'] = sysroot_events(readiness)
    changes = apt.get('changes', {})
    if apt.get('result') == 'Published' and changes.get('baseline_available') is True:
        events = []
        covered = set()
        for item in changes.get('version_changes', []):
            before, after = set(item['previous_versions']), set(item['current_versions'])
            details = []
            if after - before:
                details.append('added ' + ', '.join(sorted(after - before)))
            if before - after:
                details.append('removed ' + ', '.join(sorted(before - after)))
            if details:
                events.append(f"{item['package']} ({item['architecture']}): " + '; '.join(details))
                covered.add((item['package'], item['architecture']))
        # Entirely new or removed packages have no version_changes entry.
        for field, action in (('added', 'added'), ('removed', 'removed')):
            opposite = {(v['package'], v['architecture'], v['version']) for v in changes.get('removed' if field == 'added' else 'added', [])}
            for item in changes.get(field, []):
                if (item['package'], item['architecture']) not in covered and (item['package'], item['architecture'], item['version']) not in opposite:
                    events.append(f"{item['package']} ({item['architecture']}): {action} {item['version']}")
        if events:
            result['packages'] = sorted(set(events))
    return result


def format_version(kind, version):
    label = html.escape(version, quote=False)
    match = re.fullmatch(r'3\.0\.0_daily_develop_B([0-9]+)', version)
    if kind == 'images' and match:
        url = f'https://jenkins.eng.sima.ai/job/soc-jobs/job/elxr-builder/{match.group(1)}/console'
        return f'<{url}|{label}>'
    return label


def image_change_artifacts(items, report_dir):
    if report_dir is None:
        return [], {}
    root = report_dir.resolve()
    attachments, summaries = [], {}
    for item in items:
        version = item['version']
        if item['kind'] != 'images' or not IMAGE_BUILD_RE.fullmatch(version):
            continue
        report = (root / f'{version}.html').resolve()
        summary = (root / f'{version}.slack.txt').resolve()
        if report.parent == root and report.is_file():
            attachments.append(report)
        if summary.parent == root and summary.is_file():
            value = summary.read_text(encoding='utf-8').strip()
            if value:
                summaries[version] = html.escape(value[:1400], quote=False)
    return attachments, summaries


def validate_run_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment
            or '/actions/runs/' not in parsed.path or any(c in url for c in '<>|\n\r')):
        raise ValueError('Expected a GitHub Actions run URL')
    return url


def message_blocks(items, run_url, summaries=None, has_attachments=False):
    """Render persisted events without changing their outbox identities."""
    summaries = summaries or {}
    blocks = [{'type': 'header', 'text': {'type': 'plain_text', 'text': 'Mirror changes published'}}]
    packages = sorted(
        (item['version'] for item in items if item['kind'] == 'packages'),
        key=lambda value: (': added ' not in value, value),
    )
    if packages:
        blocks.append({'type': 'section', 'text': {
            'type': 'mrkdwn', 'text': f'*APT package changes: {len(packages)}*',
        }})
        rows = [[{'type': 'raw_text', 'text': label} for label in
                 ('Package', 'Architecture', 'Removed versions', 'Added versions')]]
        table_text_length = sum(len(cell['text']) for cell in rows[0])
        included_packages = 0
        # Slack allows 100 rows including the header, one table per message,
        # and at most 10,000 characters across all cells in that table.
        for event in packages[:99]:
            match = re.fullmatch(r'(.+?) \(([^()]+)\): (.+)', event)
            if match:
                package, architecture, details = match.groups()
                changes = dict(part.split(' ', 1) for part in details.split('; '))
                cells = (package, architecture, changes.get('removed', '—'), changes.get('added', '—'))
            else:
                # Preserve unfamiliar pending events from older producers verbatim.
                cells = (event, '—', '—', '—')
            row = [{'type': 'raw_text', 'text': (
                value if len(value) <= TABLE_CELL_LIMIT else
                value[:TABLE_CELL_LIMIT - len(TABLE_CELL_OVERFLOW)] + TABLE_CELL_OVERFLOW
            )} for value in cells]
            row_text_length = sum(len(cell['text']) for cell in row)
            if table_text_length + row_text_length > TABLE_TEXT_LIMIT:
                break
            rows.append(row)
            table_text_length += row_text_length
            included_packages += 1
        blocks.append({'type': 'table', 'rows': rows,
                       'column_settings': [{'is_wrapped': True} for _ in range(4)]})
        if len(packages) > included_packages:
            blocks.append({'type': 'context', 'elements': [{
                'type': 'mrkdwn',
                'text': f'{len(packages) - included_packages} more changes; see the workflow report.',
            }]})
    for kind in ('apt', 'images', 'sysroots'):
        for item in items:
            if item['kind'] == kind:
                blocks.append({'type': 'section', 'text': {
                    'type': 'mrkdwn',
                    'text': f'*{KINDS[kind]}:* {format_version(kind, item["version"])}',
                }})
                if kind == 'images' and item['version'] in summaries:
                    blocks.append({'type': 'section', 'text': {
                        'type': 'mrkdwn', 'text': summaries[item['version']],
                    }})
    if has_attachments:
        blocks.append({'type': 'context', 'elements': [{
            'type': 'mrkdwn', 'text': 'Detailed HTML source-change report attached in thread.',
        }]})
    blocks.append({'type': 'section', 'text': {
        'type': 'mrkdwn', 'text': f'<{run_url}|View full changes → GitHub workflow run>',
    }})
    return blocks


def notify(state_path, versions, run_url, send, pause_between_sends=None, report_dir=None):
    validate_run_url(run_url)
    state = load_report(state_path) or {'schema_version': 1, 'seen': {}, 'pending': []}
    if state.get('schema_version') != 1:
        raise ValueError('Unsupported mirror notification state schema')
    for kind in KINDS:
        seen = set(state['seen'].get(kind, []))
        pending = {item['version'] for item in state['pending'] if item['kind'] == kind}
        for version in sorted(set(versions.get(kind, [])) - pending):
            identity = run_url + '\n' + version if kind == 'packages' else version
            if kind == 'sysroots':
                image = version.split(': ', 1)[0]
                observations = state.setdefault('sysroot_observations', {})
                if observations.get(image) == version:
                    continue
                observations[image] = version
            elif identity in seen:
                continue
            state['pending'].append({'kind': kind, 'version': version, 'run_url': run_url})
    # Record the original detecting run before contacting Slack. A failed send
    # is retried even if the next mirror run reports no upstream changes.
    save_state(state_path, state)
    if not state['pending']:
        print('No new mirror versions; Slack notification skipped.')
        return
    # Group by original run to preserve provenance when retrying older events.
    groups = {}
    for item in state['pending']:
        groups.setdefault(item['run_url'], []).append(item)
    for group_index, (original_run, items) in enumerate(groups.items()):
        if group_index and pause_between_sends:
            pause_between_sends()
        validate_run_url(original_run)
        lines = ['Mirror changes published']
        for kind, label in KINDS.items():
            values = [format_version(kind, item['version']) for item in items if item['kind'] == kind]
            if values:
                if kind == 'packages':
                    # Favor newly available versions, including retried outbox entries.
                    values.sort(key=lambda value: (': added ' not in value, value))
                    lines.append(f'{label}: {len(values)}')
                    lines.extend('• ' + value[:500] for value in values[:5])
                    if len(values) > 5:
                        lines.append(f'…and {len(values) - 5} more; see the workflow report.')
                else:
                    lines.append(f'{label}: ' + ', '.join(values))
        attachments, summaries = image_change_artifacts(items, report_dir)
        for item in items:
            if item['kind'] == 'images' and item['version'] in summaries:
                lines.extend(['', summaries[item['version']]])
        lines.append(f'<{original_run}|GitHub workflow run>')
        send('\n'.join(lines), blocks=message_blocks(
            items, original_run, summaries, has_attachments=bool(attachments)),
             attachments=attachments)
        for item in items:
            identity = item['run_url'] + '\n' + item['version'] if item['kind'] == 'packages' else item['version']
            if item['kind'] != 'sysroots':
                state['seen'].setdefault(item['kind'], []).append(identity)
            state['pending'].remove(item)
        save_state(state_path, state)


def replay_image_notification(build, run_url, send, report_dir):
    if not IMAGE_BUILD_RE.fullmatch(build):
        raise ValueError('Expected a complete daily image build name')
    report = report_dir / f'{build}.html' if report_dir else None
    if report is None or not report.is_file():
        raise FileNotFoundError(f'HTML source-change report is missing for replay build {build}')
    # Replay must not mutate or depend on the durable scheduled-notification
    # ledger. A temporary state also makes an already-seen image send once.
    with tempfile.TemporaryDirectory(prefix='image-change-replay-') as temporary:
        notify(Path(temporary) / 'state.json', {'images': [build]}, run_url, send,
               report_dir=report_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apt-report', type=Path)
    parser.add_argument('--image-report', type=Path)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--sysroot-report', type=Path)
    parser.add_argument('--image-change-report-dir', type=Path)
    parser.add_argument('--replay-image-build')
    args = parser.parse_args()
    if args.replay_image_build:
        if args.apt_report or args.image_report or args.sysroot_report:
            parser.error('--replay-image-build cannot be combined with mirror result inputs')
        versions = None
    else:
        if not args.apt_report or not args.image_report:
            parser.error('--apt-report and --image-report are required for normal notifications')
        versions = collect(load_report(args.apt_report), load_report(args.image_report),
                           load_report(args.sysroot_report) if args.sysroot_report else None)
    sender = runpy.run_path(str(Path(__file__).with_name('post-debian-mirror-summary.py')))
    post, upload = sender['post_message'], sender['upload_file']

    def send(text, *, blocks, attachments):
        token = os.environ.get('SLACK_BOT_TOKEN', '')
        channel = os.environ.get('SLACK_VULCAN_EVENT_CHANNEL_ID', '')
        if not token or not channel:
            raise ValueError('SLACK_BOT_TOKEN and SLACK_VULCAN_EVENT_CHANNEL_ID are required')
        response = post(token, channel, text, blocks=blocks)
        thread_ts = response.get('ts')
        if attachments and not isinstance(thread_ts, str):
            raise RuntimeError('Slack message response has no timestamp for report attachments')
        for attachment in attachments:
            upload(token, channel, attachment, thread_ts=thread_ts,
                   title=f'SDK image source changes — {attachment.stem}')
        print('Posted new mirror versions to Slack.')

    run_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    # Workflow concurrency serializes writers, and this state lives on the same
    # persistent runner volume as the mirror cache.
    if args.replay_image_build:
        replay_image_notification(args.replay_image_build, run_url, send,
                                  args.image_change_report_dir)
    else:
        notify(args.state, versions, run_url, send,
               pause_between_sends=lambda: time.sleep(1),
               report_dir=args.image_change_report_dir)


if __name__ == '__main__':
    main()
