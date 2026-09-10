#!/usr/bin/env python3
"""Notify Slack of newly mirrored platform versions, with a persistent outbox."""
import argparse
import html
import json
import os
from pathlib import Path
import runpy
import tempfile
from urllib.parse import urlparse


KINDS = {'apt': 'APT', 'images': 'Device images'}


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
    return {
        'apt': apt.get('platform', {}).get('versions', []) if apt.get('result') == 'Published' else [],
        'images': images.get('versions', []) if images.get('result') == 'Published' else [],
    }


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
        for version in sorted(set(versions.get(kind, [])) - seen - pending):
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
        lines = ['New mirror versions detected']
        for kind, label in KINDS.items():
            values = [html.escape(item['version'], quote=False) for item in items if item['kind'] == kind]
            if values:
                lines.append(f'{label}: ' + ', '.join(values))
        lines.append(f'<{original_run}|GitHub workflow run>')
        send('\n'.join(lines))
        for item in items:
            state['seen'].setdefault(item['kind'], []).append(item['version'])
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
