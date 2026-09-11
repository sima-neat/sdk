#!/usr/bin/env python3
"""Notify Slack of newly mirrored platform versions, with a persistent outbox."""
import argparse
import html
import json
import os
import re
from pathlib import Path
import runpy
import tempfile
from urllib.parse import urlparse


KINDS = {'apt': 'APT', 'packages': 'APT package changes', 'images': 'Device images'}


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


def collect(apt, images):
    # Preview-only runs must never announce versions as available.
    result = {
        'apt': [],
        'images': images.get('copied_versions', []) if images.get('result') == 'Published' else [],
    }
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


def validate_run_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment
            or '/actions/runs/' not in parsed.path or any(c in url for c in '<>|\n\r')):
        raise ValueError('Expected a GitHub Actions run URL')
    return url


def notify(state_path, versions, run_url, send):
    validate_run_url(run_url)
    state = load_report(state_path) or {'schema_version': 1, 'seen': {}, 'pending': []}
    if state.get('schema_version') != 1:
        raise ValueError('Unsupported mirror notification state schema')
    for kind in KINDS:
        seen = set(state['seen'].get(kind, []))
        pending = {item['version'] for item in state['pending'] if item['kind'] == kind}
        for version in sorted(set(versions.get(kind, [])) - pending):
            identity = run_url + '\n' + version if kind == 'packages' else version
            if identity in seen:
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
    for original_run, items in groups.items():
        validate_run_url(original_run)
        lines = ['Mirror changes published']
        for kind, label in KINDS.items():
            values = [format_version(kind, item['version']) for item in items if item['kind'] == kind]
            if values:
                if kind == 'packages':
                    lines.append(f'{label}: {len(values)}')
                    lines.extend('• ' + value[:500] for value in values[:5])
                    if len(values) > 5:
                        lines.append(f'…and {len(values) - 5} more; see the workflow report.')
                else:
                    lines.append(f'{label}: ' + ', '.join(values))
        lines.append(f'<{original_run}|GitHub workflow run>')
        send('\n'.join(lines))
        for item in items:
            identity = item['run_url'] + '\n' + item['version'] if item['kind'] == 'packages' else item['version']
            state['seen'].setdefault(item['kind'], []).append(identity)
            state['pending'].remove(item)
        save_state(state_path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apt-report', type=Path, required=True)
    parser.add_argument('--image-report', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    versions = collect(load_report(args.apt_report), load_report(args.image_report))
    post = runpy.run_path(str(Path(__file__).with_name('post-debian-mirror-summary.py')))['post_message']

    def send(text):
        token = os.environ.get('SLACK_BOT_TOKEN', '')
        channel = os.environ.get('SLACK_VULCAN_EVENT_CHANNEL_ID', '')
        if not token or not channel:
            raise ValueError('SLACK_BOT_TOKEN and SLACK_VULCAN_EVENT_CHANNEL_ID are required')
        post(token, channel, text)
        print('Posted new mirror versions to Slack.')

    run_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    # Workflow concurrency serializes writers, and this state lives on the same
    # persistent runner volume as the mirror cache.
    notify(args.state, versions, run_url, send)


if __name__ == '__main__':
    main()
