"""Exercise real S3 operations against Moto, including permanent version retention."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock

import boto3
from moto import mock_aws
import pytest

spec = importlib.util.spec_from_file_location('daily_images', Path(__file__).parents[2] / 'scripts/sync-daily-platform-images.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def name(number):
    return f'3.0.0_daily_develop_B{number}'


class Source:
    def __init__(self, numbers):
        self.names = {name(n) for n in numbers}
        self.downloads = []
        self.fail = False

    def builds(self):
        return self.names

    def files(self, build):
        return [{'path': 'image.wic.gz', 'size': 5, 'sha256': hashlib.sha256(b'image').hexdigest()}]

    def download(self, build, artifact, target):
        self.downloads.append(build)
        if self.fail:
            raise ValueError('Interrupted download')
        Path(target).write_bytes(b'image')


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client('s3', region_name='us-east-1')
        client.create_bucket(Bucket=m.BUCKET)
        client.put_bucket_versioning(Bucket=m.BUCKET, VersioningConfiguration={'Status': 'Enabled'})
        yield client


def test_latest_twenty_numeric_order_and_noop(s3):
    source = Source(range(990, 1015))
    result = m.mirror(source, s3, True)
    assert [b['name'] for b in result['builds']] == [name(n) for n in range(1014, 994, -1)]
    assert len(source.downloads) == 20
    version = s3.head_object(Bucket=m.BUCKET, Key=m.PREFIX + 'index.json')['VersionId']
    m.mirror(source, s3, True)
    assert len(source.downloads) == 20
    assert s3.head_object(Bucket=m.BUCKET, Key=m.PREFIX + 'index.json')['VersionId'] == version


def test_retention_deletes_versions_markers_and_partial_builds_only(s3):
    m.mirror(Source(range(1, 21)), s3, True)
    old_key = m.PREFIX + name(1) + '/image.wic.gz'
    s3.put_object(Bucket=m.BUCKET, Key=old_key, Body=b'obsolete')
    s3.delete_object(Bucket=m.BUCKET, Key=old_key)
    partial = m.PREFIX + name(0) + '/partial.wic'
    s3.put_object(Bucket=m.BUCKET, Key=partial, Body=b'partial')
    protected = [m.PREFIX + '2.0.0_daily_develop_B1/image.wic', 'sdk/keep', m.PREFIX + 'notes.txt']
    for key in protected:
        s3.put_object(Bucket=m.BUCKET, Key=key, Body=b'keep')
    result = m.mirror(Source(range(2, 22)), s3, True)
    assert len(result['builds']) == 20
    versions = s3.list_object_versions(Bucket=m.BUCKET)
    keys = {o['Key'] for o in versions.get('Versions', []) + versions.get('DeleteMarkers', [])}
    assert old_key not in keys and partial not in keys
    assert set(protected) <= keys


def test_failed_upload_preserves_index_and_old_builds(s3):
    m.mirror(Source(range(1, 21)), s3, True)
    before = m.read_json(s3, m.PREFIX + 'index.json')
    source = Source(range(2, 22))
    source.fail = True
    with pytest.raises(ValueError, match='Interrupted'):
        m.mirror(source, s3, True)
    assert m.read_json(s3, m.PREFIX + 'index.json') == before
    assert name(1) in m.existing_builds(s3)


def test_preview_and_empty_source_never_write(s3):
    assert len(m.mirror(Source([1]), s3)['builds']) == 1
    assert s3.list_objects_v2(Bucket=m.BUCKET)['KeyCount'] == 0
    with pytest.raises(ValueError, match='No 3.0.0'):
        m.mirror(Source([]), s3, True)


def test_upstream_removal_keeps_recent_successful_builds(s3):
    m.mirror(Source([1, 2]), s3, True)
    assert len(m.mirror(Source([3]), s3, True)['builds']) == 3


def test_changed_published_build_is_not_overwritten(s3):
    source = Source([1])
    m.mirror(source, s3, True)
    source.files = lambda build: [{'path': 'image.wic.gz', 'size': 7, 'sha256': '0' * 64}]
    with pytest.raises(ValueError, match='changed upstream'):
        m.mirror(source, s3, True)


@pytest.mark.parametrize('path', ['../evil', '/tmp/evil', 'x/../evil', 'x//evil', 'x\\evil'])
def test_unsafe_source_paths(path):
    with pytest.raises(ValueError):
        m.safe_path(path)


def test_checksum_mismatch(tmp_path):
    source = m.Artifactory('test-token')
    source.open = lambda path: io.BytesIO(b'bad image')
    with pytest.raises(ValueError, match='Checksum/size mismatch'):
        source.download(name(1), Source([1]).files(name(1))[0], tmp_path / 'image')


def test_listing_filters_other_release_lines():
    source = m.Artifactory('test-token')
    source.info = lambda path: {'children': [
        {'uri': '/' + name(1168), 'folder': True},
        {'uri': '/3.1.0_daily_develop_B1169', 'folder': True},
        {'uri': '/3.0.0_release_B1170', 'folder': True},
        {'uri': '/' + name(1171), 'folder': False},
    ]}
    assert source.builds() == {name(1168)}


def test_missing_image_fails_closed():
    source = m.Artifactory('test-token')
    source.info = lambda path: {'children': []}
    with pytest.raises(ValueError, match='No platform image'):
        source.files(name(1))


def test_retention_reports_partial_delete_errors():
    s3 = Mock()
    s3.get_paginator.return_value.paginate.return_value = [{'Versions': [
        {'Key': m.PREFIX + name(1) + '/image.wic', 'VersionId': 'old'}]}]
    s3.delete_objects.return_value = {'Errors': [{'Code': 'AccessDenied'}]}
    with pytest.raises(RuntimeError, match='Retention failed'):
        m.prune(s3, set())


def test_failed_index_publication_never_prunes(s3, monkeypatch):
    m.mirror(Source(range(1, 21)), s3, True)
    original = m.put_json
    def put(client, key, data):
        if key.endswith('/index.json'):
            raise RuntimeError('Index write failed')
        original(client, key, data)
    monkeypatch.setattr(m, 'put_json', put)
    with pytest.raises(RuntimeError, match='Index write failed'):
        m.mirror(Source(range(2, 22)), s3, True)
    assert name(1) in m.existing_builds(s3)
    assert len(m.read_json(s3, m.PREFIX + 'index.json')['builds']) == 20


def test_workflow_runs_image_phase_on_same_runner_and_publish_gate():
    import yaml
    workflow = yaml.safe_load((Path(__file__).parents[2] / '.github/workflows/sync-debian-pre-release-mirror.yml').read_text())
    assert list(workflow['jobs']) == ['sync']
    job = workflow['jobs']['sync']
    assert job['runs-on'] == ['self-hosted', 'Linux', 'X64', 'apt-mirror']
    step = next(s for s in job['steps'] if 'sync-daily-platform-images.py' in s.get('run', ''))
    assert 'daily_credentials.outcome' in step['if']
    assert 'github.event_name' in step['run'] and 'inputs.publish' in step['run']
    assert step['env']['ARTIFACTORY_READ_TOKEN'] == '${{ secrets.ARTIFACTORY_READ_TOKEN }}'


def test_retention_spans_version_pages_and_delete_batches():
    s3 = Mock()
    versions = [{'Key': m.PREFIX + name(1) + f'/{n}.wic', 'VersionId': str(n)} for n in range(1001)]
    s3.get_paginator.return_value.paginate.return_value = [
        {'Versions': versions[:1000]}, {'Versions': versions[1000:]}]
    s3.delete_objects.return_value = {}
    assert m.prune(s3, {name(2)}) == 1001
    assert [len(call.kwargs['Delete']['Objects']) for call in s3.delete_objects.call_args_list] == [1000, 1]
