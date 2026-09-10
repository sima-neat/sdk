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


class Ready:
    def observe(self, build, files):
        return True

    def reset(self, build):
        pass


def mirror(*args, **kwargs):
    # Existing transfer/retention cases start with an already stable inventory.
    kwargs.setdefault('readiness', Ready())
    return m.mirror(*args, **kwargs)


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
    result = mirror(source, s3, True)
    assert [b['name'] for b in result['builds']] == [name(n) for n in range(1014, 994, -1)]
    assert len(source.downloads) == 20
    version = s3.head_object(Bucket=m.BUCKET, Key=m.PREFIX + 'index.json')['VersionId']
    mirror(source, s3, True)
    assert len(source.downloads) == 20
    assert s3.head_object(Bucket=m.BUCKET, Key=m.PREFIX + 'index.json')['VersionId'] == version


def test_retention_deletes_versions_markers_and_partial_builds_only(s3):
    mirror(Source(range(1, 21)), s3, True)
    old_key = m.PREFIX + name(1) + '/image.wic.gz'
    s3.put_object(Bucket=m.BUCKET, Key=old_key, Body=b'obsolete')
    s3.delete_object(Bucket=m.BUCKET, Key=old_key)
    partial = m.PREFIX + name(0) + '/partial.wic'
    s3.put_object(Bucket=m.BUCKET, Key=partial, Body=b'partial')
    protected = [m.PREFIX + '2.0.0_daily_develop_B1/image.wic', 'sdk/keep', m.PREFIX + 'notes.txt']
    for key in protected:
        s3.put_object(Bucket=m.BUCKET, Key=key, Body=b'keep')
    result = mirror(Source(range(2, 22)), s3, True)
    assert len(result['builds']) == 20
    versions = s3.list_object_versions(Bucket=m.BUCKET)
    keys = {o['Key'] for o in versions.get('Versions', []) + versions.get('DeleteMarkers', [])}
    assert old_key not in keys and partial not in keys
    assert set(protected) <= keys


def test_failed_upload_preserves_index_and_old_builds(s3):
    mirror(Source(range(1, 21)), s3, True)
    before = m.read_json(s3, m.PREFIX + 'index.json')
    source = Source(range(2, 22))
    source.fail = True
    with pytest.raises(ValueError, match='Interrupted'):
        mirror(source, s3, True)
    assert m.read_json(s3, m.PREFIX + 'index.json') == before
    assert name(1) in m.existing_builds(s3)


def test_preview_and_empty_source_never_write(s3):
    assert len(mirror(Source([1]), s3)['builds']) == 1
    assert s3.list_objects_v2(Bucket=m.BUCKET)['KeyCount'] == 0
    with pytest.raises(ValueError, match='No 3.0.0'):
        mirror(Source([]), s3, True)


def test_upstream_removal_keeps_recent_successful_builds(s3):
    mirror(Source([1, 2]), s3, True)
    assert len(mirror(Source([3]), s3, True)['builds']) == 3


def test_changed_published_build_is_not_overwritten(s3):
    source = Source([1])
    mirror(source, s3, True)
    source.files = lambda build: [{'path': 'image.wic.gz', 'size': 7, 'sha256': '0' * 64}]
    with pytest.raises(ValueError, match='changed upstream'):
        mirror(source, s3, True)


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
    mirror(Source(range(1, 21)), s3, True)
    original = m.put_json
    def put(client, key, data):
        if key.endswith('/index.json'):
            raise RuntimeError('Index write failed')
        original(client, key, data)
    monkeypatch.setattr(m, 'put_json', put)
    with pytest.raises(RuntimeError, match='Index write failed'):
        mirror(Source(range(2, 22)), s3, True)
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


def test_image_report_survives_retention_failure(s3, tmp_path, monkeypatch):
    report = tmp_path / 'result.json'
    monkeypatch.setattr(m, 'prune', Mock(side_effect=RuntimeError('Retention failed')))
    with pytest.raises(RuntimeError, match='Retention failed'):
        mirror(Source([1]), s3, True, report_path=report)
    assert json.loads(report.read_text())['versions'] == [name(1)]
    assert m.read_json(s3, m.PREFIX + 'index.json') is not None


def test_failed_download_and_preview_do_not_report_published_images(s3, tmp_path):
    report = tmp_path / 'result.json'
    source = Source([1])
    mirror(source, s3, report_path=report)
    assert not report.exists()
    source.fail = True
    with pytest.raises(ValueError, match='Interrupted'):
        mirror(source, s3, True, report_path=report)
    assert not report.exists()


def test_partial_inventory_must_stabilize_across_runs(s3, tmp_path):
    now = [0]
    readiness = m.BuildReadiness(tmp_path, clock=lambda: now[0])
    source = Source([1])
    assert mirror(source, s3, True, readiness=readiness) is None
    assert source.downloads == []
    # The image appeared first; a supporting file arrives before the next run.
    files = source.files(name(1))
    files.append(dict(files[0], path='support.txt'))
    source.files = lambda build: files
    now[0] = 1800
    assert mirror(source, s3, True, readiness=readiness) is None
    assert m.read_json(s3, m.PREFIX + 'index.json') is None
    # A fresh process loads the persisted observation and still waits 30 min.
    readiness = m.BuildReadiness(tmp_path, clock=lambda: now[0])
    now[0] = 3599
    assert mirror(source, s3, True, readiness=readiness) is None
    now[0] = 3600
    result = mirror(source, s3, True, readiness=readiness)
    assert len(result['builds'][0]['files']) == 2


def test_pending_new_build_does_not_evict_completed_builds(s3, tmp_path):
    mirror(Source(range(1, 21)), s3, True)
    result = mirror(Source(range(1, 22)), s3, True, readiness=m.BuildReadiness(tmp_path))
    assert [b['name'] for b in result['builds']] == [name(n) for n in range(20, 0, -1)]
    assert name(1) in m.existing_builds(s3)
    assert name(21) not in m.existing_builds(s3)


def test_listing_changed_during_transfer_does_not_publish_manifest_or_index(s3, tmp_path):
    mirror(Source([1]), s3, True)
    previous = m.read_json(s3, m.PREFIX + 'index.json')
    source = Source([2])
    original_files = source.files
    def download(build, artifact, target):
        Path(target).write_bytes(b'image')
        source.files = lambda build: original_files(build) + [dict(original_files(build)[0], path='late.txt')]
    source.download = download
    with pytest.raises(ValueError, match='Build changed during transfer'):
        mirror(source, s3, True, readiness=Ready())
    assert m.read_json(s3, m.PREFIX + name(2) + '/manifest.json') is None
    assert m.read_json(s3, m.PREFIX + 'index.json') == previous
    assert name(1) in m.existing_builds(s3)


def test_no_image_resets_stability_and_does_not_block_other_builds(s3, tmp_path):
    readiness = m.BuildReadiness(tmp_path, clock=lambda: 0)
    source = Source([1, 2])
    files = source.files(name(2))
    readiness.observe(name(2), files)
    def listing(build):
        if build == name(2):
            raise m.IncompleteBuild('Image still uploading')
        return files
    source.files = listing
    assert mirror(source, s3, True, readiness=readiness) is None
    assert not (readiness.root / f'{name(2)}.json').exists()
    assert (readiness.root / f'{name(1)}.json').exists()


def test_checksum_change_restarts_stability_timer(tmp_path):
    now = [0]
    readiness = m.BuildReadiness(tmp_path, clock=lambda: now[0])
    files = Source([1]).files(name(1))
    assert not readiness.observe(name(1), files)
    now[0] = 1800
    changed = [dict(files[0], sha256='0' * 64)]
    assert not readiness.observe(name(1), changed)
    now[0] = 3600
    assert readiness.observe(name(1), changed)
