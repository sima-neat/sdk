"""Certificate rotation, validation and publication failure regressions."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from botocore.exceptions import ClientError
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('certificate_sync', ROOT / 'scripts/sync-swupdate-certificate.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


@pytest.fixture(scope='module')
def certificate(tmp_path_factory):
    directory = tmp_path_factory.mktemp('certificate')
    subprocess.run(
        ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
         '-keyout', str(directory / 'key.pem'), '-out', str(directory / 'cert.pem'),
         '-days', '1', '-subj', '/CN=Mirror test'],
        check=True, capture_output=True,
    )
    return (directory / 'cert.pem').read_bytes()


def test_valid_certificate(monkeypatch, certificate):
    opener = Mock(return_value=io.BytesIO(certificate))
    monkeypatch.setattr(sync, 'urlopen', opener)
    data, details = sync.download_certificate()
    assert data == certificate
    assert 'Mirror test' in details and 'Fingerprint=' in details
    opener.assert_called_once_with(sync.SOURCE, timeout=120)


@pytest.mark.parametrize('invalid', [b'', b'<html>error</html>', b'x' * (sync.MAX_BYTES + 1),
    b'-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----'])
def test_invalid_download(monkeypatch, invalid):
    monkeypatch.setattr(sync, 'urlopen', lambda *a, **kw: io.BytesIO(invalid))
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        sync.download_certificate()


def test_reject_extra_pem_and_trailing_content(monkeypatch, certificate):
    for extra in (certificate, b'-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----', b'junk'):
        monkeypatch.setattr(sync, 'urlopen', lambda *a, **kw: io.BytesIO(certificate + extra))
        with pytest.raises(ValueError):
            sync.download_certificate()


def test_preview_does_not_access_s3(certificate):
    client = Mock()
    assert sync.synchronize(client, 'bucket', 'key', certificate)[0] == 'Validated only'
    assert not client.mock_calls


def test_initial_publish(certificate):
    client = Mock()
    client.list_objects_v2.return_value = {}
    assert sync.synchronize(client, 'bucket', 'kms', certificate, True)[0] == 'Published'
    client.list_objects_v2.assert_called_once_with(Bucket='bucket', Prefix=sync.KEY, MaxKeys=1)
    client.get_object.assert_not_called()
    args = client.put_object.call_args.kwargs
    assert args['Body'] == certificate and args['Key'] == 'daily/swupdate-signing-cert.pem'
    assert args['ServerSideEncryption'] == 'aws:kms' and args['SSEKMSKeyId'] == 'kms'
    assert args['CacheControl'] == 'no-cache,no-store,must-revalidate'


def test_rotation_and_no_change(certificate):
    client = Mock()
    client.list_objects_v2.return_value = {'Contents': [{'Key': sync.KEY}]}
    client.get_object.return_value = {'Body': io.BytesIO(b'previous certificate')}
    assert sync.synchronize(client, 'bucket', 'kms', certificate, True)[0] == 'Published'
    client.put_object.assert_called_once()
    client.reset_mock()
    client.get_object.return_value = {'Body': io.BytesIO(certificate)}
    assert sync.synchronize(client, 'bucket', 'kms', certificate, True)[0] == 'No change'
    client.put_object.assert_not_called()


def test_s3_error_does_not_replace(certificate):
    client = Mock()
    client.list_objects_v2.return_value = {'Contents': [{'Key': sync.KEY}]}
    client.get_object.side_effect = ClientError({'Error': {'Code': 'AccessDenied'}}, 'GetObject')
    with pytest.raises(ClientError):
        sync.synchronize(client, 'bucket', 'kms', certificate, True)
    client.put_object.assert_not_called()


def test_download_failure_never_publishes(monkeypatch):
    import mirror_aws
    client_factory = Mock()
    monkeypatch.setattr(mirror_aws, 's3_client', client_factory)
    monkeypatch.setattr(sys, 'argv', ['sync', '--publish'])
    monkeypatch.setattr(sync, 'urlopen', Mock(side_effect=OSError('unreachable')))
    with pytest.raises(OSError):
        sync.main()
    client_factory.assert_not_called()


def test_workflow_runs_independently():
    workflow = yaml.safe_load((ROOT / '.github/workflows/sync-debian-pre-release-mirror.yml').read_text())
    steps = workflow['jobs']['sync']['steps']
    certificate = next(step for step in steps if step['name'] == 'Synchronize SWUpdate verification certificate')
    apt = next(step for step in steps if step['name'] == 'Synchronize and validate mirror')
    assert '!cancelled()' in certificate['if'] and 'mirror_credentials.outcome' in certificate['if']
    assert '!cancelled()' in apt['if']
    assert 'schedule' in certificate['run'] and 'inputs.publish' in certificate['run']
    assert 'sync-swupdate-certificate.py' in certificate['run']
