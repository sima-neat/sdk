#!/usr/bin/env python3
"""Mirror verified Artifactory daily builds; index publication precedes retention."""
import argparse
import base64
import netrc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCE = 'https://artifacts.eng.sima.ai/artifactory'
ROOT = 'soc-images/elxr/bsp/modalix'
BUCKET = 'sima-neat-artifacts-production'
PREFIX = 'daily-platform-images/'
BUILD = re.compile(r'3\.0\.0_daily_[A-Za-z0-9_-]+_B([0-9]+)\Z')
IMAGES = ('.wic', '.wic.gz', '.wic.xz', '.wic.zst', '.img', '.img.gz', '.img.xz', '.img.zst', '.iso')
KEEP = 20


def rank(name):
    match = BUILD.fullmatch(name)
    if not match:
        raise ValueError(f'Invalid daily build name: {name}')
    return int(match[1]), name


def safe_path(value):
    if not value or value.startswith('/') or '\\' in value or any(
        part in ('', '.', '..') for part in value.split('/')
    ):
        raise ValueError(f'Unsafe artifact path: {value!r}')
    return value


class IncompleteBuild(ValueError):
    """A visible build is not yet a complete image inventory."""


class BuildReadiness:
    """Require the same complete inventory across runs at least 30 minutes apart."""
    def __init__(self, root, clock=time.time):
        self.root = Path(root) / 'daily-image-readiness'
        self.clock = clock

    def observe(self, build, files):
        rank(build)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f'{build}.json'
        fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        now = self.clock()
        previous = json.loads(path.read_text()) if path.exists() else None
        if (previous and previous['fingerprint'] == fingerprint
                and now >= previous['first_seen']):
            return now - previous['first_seen'] >= 30 * 60
        with tempfile.NamedTemporaryFile(mode='w', dir=self.root, delete=False) as output:
            json.dump({'fingerprint': fingerprint, 'first_seen': now}, output)
            temporary = output.name
        os.replace(temporary, path)
        return False

    def reset(self, build):
        rank(build)
        (self.root / f'{build}.json').unlink(missing_ok=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Artifactory redirects are not allowed')


class Artifactory:
    def __init__(self, netrc_path=None):
        host = urlparse(SOURCE).hostname
        try:
            credentials = netrc.netrc(netrc_path).authenticators(host)
        except (OSError, netrc.NetrcParseError):
            raise ValueError('Cannot read runner .netrc credentials for Artifactory') from None
        if not credentials or not credentials[0] or not credentials[2]:
            raise ValueError(f'Runner .netrc requires login and password for {host}')
        login, _, password = credentials
        encoded = base64.b64encode(f'{login}:{password}'.encode()).decode('ascii')
        self.authorization = f'Basic {encoded}'
        self.opener = build_opener(NoRedirect())

    def open(self, path):
        return self.opener.open(Request(
            f'{SOURCE}/{path}', headers={'Authorization': self.authorization}
        ), timeout=120)

    def info(self, path):
        with self.open('api/storage/' + quote(path, safe='/')) as response:
            return json.load(response)

    def builds(self):
        return {child['uri'].removeprefix('/') for child in self.info(ROOT)['children']
                if child['folder'] and BUILD.fullmatch(child['uri'].removeprefix('/'))}

    def files(self, build):
        files = []
        def walk(relative=''):
            folder = f'{ROOT}/{build}' + (f'/{relative}' if relative else '')
            for child in self.info(folder)['children']:
                name = safe_path(child['uri'].removeprefix('/'))
                path = safe_path(f'{relative}/{name}' if relative else name)
                if child['folder']:
                    walk(path)
                else:
                    data = self.info(f'{ROOT}/{build}/{path}')
                    sha = data.get('checksums', {}).get('sha256', '')
                    size = int(data['size'])
                    if not re.fullmatch('[a-fA-F0-9]{64}', sha) or size <= 0:
                        raise IncompleteBuild(f'Missing SHA256 or empty artifact: {build}/{path}')
                    files.append({'path': path, 'size': size, 'sha256': sha.lower()})
        walk()
        if not any(f['path'].endswith(IMAGES) for f in files):
            raise IncompleteBuild(f'No platform image found in {build}; waiting for upload')
        if any(f['path'] == 'manifest.json' for f in files):
            raise ValueError('Source uses reserved manifest.json name')
        return sorted(files, key=lambda f: f['path'])

    def download(self, build, artifact, target):
        digest = hashlib.sha256()
        size = 0
        with self.open(quote(f'{ROOT}/{build}/{artifact["path"]}', safe='/')) as response, open(target, 'wb') as output:
            while chunk := response.read(8 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
        if size != artifact['size'] or digest.hexdigest() != artifact['sha256']:
            raise ValueError(f'Checksum/size mismatch: {build}/{artifact["path"]}')


def read_json(s3, key):
    from botocore.exceptions import ClientError
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)['Body'].read())
    except ClientError as exc:
        if exc.response['Error']['Code'] in ('NoSuchKey', '404'):
            return None
        raise


def put_json(s3, key, data):
    s3.put_object(Bucket=BUCKET, Key=key, Body=(json.dumps(data, indent=2) + '\n').encode(),
                  ContentType='application/json', CacheControl='no-cache, max-age=0',
                  ServerSideEncryption='aws:kms', SSEKMSKeyId='alias/sima-neat-artifacts-production')


def existing_builds(s3):
    names = set()
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=PREFIX, Delimiter='/'):
        for entry in page.get('CommonPrefixes', []):
            name = entry['Prefix'][len(PREFIX):].rstrip('/')
            if BUILD.fullmatch(name):
                names.add(name)
    return names


def prune(s3, retained):
    # Materialize before deleting so version pagination cannot skip objects.
    doomed = []
    for page in s3.get_paginator('list_object_versions').paginate(Bucket=BUCKET, Prefix=PREFIX + '3.0.0_daily_'):
        for obj in page.get('Versions', []) + page.get('DeleteMarkers', []):
            name = obj['Key'][len(PREFIX):].split('/')[0]
            if BUILD.fullmatch(name) and name not in retained:
                doomed.append({'Key': obj['Key'], 'VersionId': obj['VersionId']})
    for offset in range(0, len(doomed), 1000):
        result = s3.delete_objects(Bucket=BUCKET, Delete={'Objects': doomed[offset:offset + 1000], 'Quiet': True})
        if result.get('Errors'):
            raise RuntimeError(f'Retention failed: {result["Errors"]}')
    return len(doomed)


def mirror(source, s3, publish=False, work_root=None, report_path=None, readiness=None):
    if readiness is None:
        if work_root is None:
            raise ValueError("A persistent work root is required for build readiness")
        readiness = BuildReadiness(work_root)
    upstream = source.builds()
    if not upstream:
        raise ValueError('No 3.0.0 daily builds found; refusing publication and deletion')
    stored = existing_builds(s3)
    # Keep successful builds even if Artifactory has already removed them.
    manifests = {name: read_json(s3, f'{PREFIX}{name}/manifest.json') for name in stored}
    candidates = sorted(upstream | {name for name, manifest in manifests.items() if manifest}, key=rank, reverse=True)
    snapshots = {}
    names = []
    for name in candidates:
        if name in upstream:
            try:
                files = source.files(name)
            except IncompleteBuild as exc:
                readiness.reset(name)
                if manifests.get(name):
                    raise ValueError(f'Published build became incomplete: {name}') from exc
                print(f'{name}: pending ({exc})', flush=True)
                continue
            if not manifests.get(name) and not readiness.observe(name, files):
                print(f'{name}: waiting for a stable inventory for 30 minutes', flush=True)
                continue
            snapshots[name] = files
        names.append(name)
        if len(names) == KEEP:
            break
    if not names:
        print('No stable completed builds; leaving S3 and index unchanged', flush=True)
        return None
    builds = []
    for name in names:
        files = snapshots[name] if name in snapshots else manifests[name]['files']
        files = [dict(f, key=f'{PREFIX}{name}/{safe_path(f["path"])}',
                      s3_uri=f's3://{BUCKET}/{PREFIX}{name}/{safe_path(f["path"])}') for f in files]
        manifest = {'name': name, 'build_number': rank(name)[0], 'source_url': f'{SOURCE}/{ROOT}/{name}/', 'files': files}
        if manifests.get(name) and manifests[name] != manifest:
            raise ValueError(f'Published build changed upstream: {name}; refusing to overwrite')
        print(f'{name}: {len(files)} artifacts', flush=True)
        if not publish:
            builds.append(manifest)
            continue
        from botocore.exceptions import ClientError
        for artifact in files:
            try:
                head = s3.head_object(Bucket=BUCKET, Key=artifact['key'])
                if head['ContentLength'] == artifact['size'] and head.get('Metadata', {}).get('sha256') == artifact['sha256']:
                    continue
            except ClientError as exc:
                if exc.response['Error']['Code'] not in ('404', 'NoSuchKey'):
                    raise
            if name not in upstream:
                raise ValueError(f'Stored image missing or corrupt and unavailable upstream: {name}')
            with tempfile.TemporaryDirectory(dir=work_root) as tmp:
                if shutil.disk_usage(tmp).free < artifact['size'] + 1024**3:
                    raise ValueError(f'Insufficient disk space for {name}/{artifact["path"]}')
                target = os.path.join(tmp, 'artifact')
                source.download(name, artifact, target)
                s3.upload_file(target, BUCKET, artifact['key'], ExtraArgs={
                    'ServerSideEncryption': 'aws:kms', 'SSEKMSKeyId': 'alias/sima-neat-artifacts-production',
                    'Metadata': {'sha256': artifact['sha256']},
                })
        builds.append(manifest)
    index = {'schema_version': 1, 'platform': 'modalix', 'version_prefix': '3.0.0_daily_',
             'bucket': BUCKET, 'prefix': PREFIX, 'retention_count': KEEP, 'builds': builds}
    if publish:
        # A directory can gain supporting files during a long transfer. Recheck
        # every selected upstream inventory before writing any completion marker.
        for name, snapshot in snapshots.items():
            try:
                current = source.files(name)
            except IncompleteBuild:
                readiness.reset(name)
                raise
            if current != snapshot:
                readiness.reset(name)
                readiness.observe(name, current)
                raise ValueError(f'Build changed during transfer: {name}; publication deferred')
        for manifest in builds:
            name = manifest['name']
            if manifests.get(name) != manifest:
                put_json(s3, f'{PREFIX}{name}/manifest.json', manifest)
        old = read_json(s3, PREFIX + 'index.json')
        if old is None or {k: v for k, v in old.items() if k != 'generated_at'} != index:
            put_json(s3, PREFIX + 'index.json', dict(index, generated_at=datetime.now(timezone.utc).isoformat()))
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({
                'schema_version': 1, 'result': 'Published', 'versions': names,
            }, indent=2) + '\n')
        protected = set(names) | {name for name in upstream if rank(name) > rank(names[-1])}
        print(f'Removed {prune(s3, protected)} expired object versions')
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='Upload, publish index, and permanently prune older builds')
    parser.add_argument('--work-root', required=True, help='Persistent inventory observations and download workspace')
    parser.add_argument('--report', type=Path, help='Published image versions for notifications')
    args = parser.parse_args()
    import boto3
    mirror(Artifactory(), boto3.client('s3'), args.publish, args.work_root, args.report)


if __name__ == '__main__':
    main()
