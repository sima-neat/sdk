#!/usr/bin/env python3
"""Publish the SDK component catalog after a checked main merge, or an explicit test upload."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BUCKET = 'sima-neat-artifacts-production'
ACCOUNT = '069171140053'
DISTRIBUTION = 'E27E9R1IMT1ZSC'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def merged_revision(event, event_name):
    workflow = event.get('workflow_run', {})
    repo = event.get('repository', {}).get('full_name')
    if (event_name != 'workflow_run' or workflow.get('name') != 'Build SDK Docker Image'
            or workflow.get('conclusion') != 'success' or workflow.get('head_branch') != 'main'
            or workflow.get('event') != 'push'
            or workflow.get('head_repository', {}).get('full_name') != repo
            or repo != 'sima-neat/sdk'):
        raise ValueError('Publication requires a successful main SDK build from this repository')
    revision = workflow.get('head_sha', '')
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('Missing main merge revision')
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default='components.json')
    parser.add_argument('--output', default='/tmp/sdk-components-published.json')
    args = parser.parse_args()
    run('node', 'scripts/components-catalog.js', 'validate', args.manifest)
    catalog = json.loads(Path(args.manifest).read_text())
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    revision = merged_revision(event, os.environ.get('GITHUB_EVENT_NAME'))
    latest = run('gh', 'api', 'repos/sima-neat/sdk/commits/main', '--jq', '.sha')
    if revision != latest:
        print('Skipping superseded main build; a newer revision owns publication')
        return
    pulls = json.loads(run('gh', 'api', f'repos/sima-neat/sdk/commits/{revision}/pulls'))
    if not any(p.get('merged_at') and p.get('merge_commit_sha') == revision and p.get('base', {}).get('ref') == 'main' for p in pulls):
        raise ValueError('The source revision must be a reviewed PR merge into main')
    if run('git', 'rev-parse', 'HEAD') != revision:
        raise ValueError('Checkout does not match the validated merge revision')
    committed = run('git', 'show', f'{revision}:components.json')
    if json.loads(committed) != catalog:
        raise ValueError('Manifest differs from the merged main revision')
    import boto3
    session = boto3.Session(region_name='us-west-2')
    identity = session.client('sts').get_caller_identity()
    if identity['Account'] != ACCOUNT:
        raise ValueError('Wrong AWS account for SDK component publication')
    kms_key = os.environ.get('SSE_KMS_KEY_ID', '')
    if not kms_key.startswith('arn:aws:kms:us-west-2:' + ACCOUNT + ':key/'):
        raise ValueError('The Vulcan customer-managed artifact encryption key is required')
    s3 = session.client('s3')
    previous = None
    try:
        previous = s3.get_object(Bucket=BUCKET, Key='sdk/components.json')
    except s3.exceptions.ClientError as error:
        if error.response['Error']['Code'] not in ('NoSuchKey', '404'):
            raise
    condition = {'IfNoneMatch': '*'}
    if previous:
        previous_bytes = previous['Body'].read()
        condition = {'IfMatch': previous['ETag']}
        backup = Path(args.output).with_suffix('.previous.json')
        backup.write_bytes(previous_bytes)
        prior = json.loads(previous_bytes)
        prior_content = {key: value for key, value in prior.items() if key != 'publication'}
        if prior.get('revision') == catalog['revision'] and prior_content != catalog:
            raise ValueError('Changed compatibility data must increase the manifest revision')
        if prior.get('revision', 0) > catalog['revision']:
            raise ValueError('Refusing to replace a newer manifest revision')
        if not prior.get('publication', {}).get('manual_test'):
            source = prior.get('publication', {}).get('source_revision')
            if source and not re.fullmatch(r'[a-f0-9]{40}', source):
                raise ValueError('Previous publication has an invalid source revision')
            if source and source != revision:
                subprocess.run(['git', 'merge-base', '--is-ancestor', source, revision], check=True)
    catalog['publication'] = {
        'source_revision': revision,
        'manual_test': False,
        'published_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'manifest_sha256': hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest(),
    }
    data = (json.dumps(catalog, indent=2) + '\n').encode()
    # Recheck after reads to prevent an older workflow from racing a newer merge.
    if run('gh', 'api', 'repos/sima-neat/sdk/commits/main', '--jq', '.sha') != revision:
        raise ValueError('Main advanced before publication; wait for the newer build')
    result = s3.put_object(Bucket=BUCKET, Key='sdk/components.json', Body=data,
        ContentType='application/json', CacheControl='no-cache, max-age=0, must-revalidate',
        ServerSideEncryption='aws:kms', SSEKMSKeyId=kms_key,
        Metadata={'source-revision': revision, 'manual-test': 'false'}, **condition)
    Path(args.output).write_bytes(data)
    invalidation = session.client('cloudfront').create_invalidation(DistributionId=DISTRIBUTION,
        InvalidationBatch={'Paths': {'Quantity': 1, 'Items': ['/sdk/components.json']},
                           'CallerReference': f'sdk-components-{hashlib.sha256(data).hexdigest()}'})
    print(json.dumps({'url': 'https://artifacts.neat.sima.ai/sdk/components.json',
        'source_revision': revision, 'manual_test': False, 'etag': result['ETag'],
        'version_id': result.get('VersionId'), 'invalidation_id': invalidation['Invalidation']['Id']}))


if __name__ == '__main__':
    main()
