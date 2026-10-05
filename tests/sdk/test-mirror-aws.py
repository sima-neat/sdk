import importlib.util
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import botocore.session
import pytest

spec = importlib.util.spec_from_file_location('mirror_aws', Path(__file__).parents[2] / 'scripts/mirror_aws.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def github(monkeypatch):
    values = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123',
              'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://oidc.example/token?request=1&audience=old',
              'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'request-secret',
              'VULCAN_DEBIAN_MIRROR_PUBLISHER_ROLE_ARN': 'arn:aws:iam::123456789012:role/Mirror',
              'AWS_ACCESS_KEY_ID': 'expired-static-key', 'AWS_SECRET_ACCESS_KEY': 'expired-static-secret',
              'AWS_SESSION_TOKEN': 'expired-static-token', 'AWS_REGION': 'us-west-2'}
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_same_s3_client_refreshes_credentials_and_oidc_before_expiry(github, monkeypatch):
    session = botocore.session.get_session()
    create_client = session.create_client
    sts = Mock()
    def response(key, seconds):
        return {'Credentials': {'AccessKeyId': key, 'SecretAccessKey': 'secret',
                                'SessionToken': f'token-{key}',
                                'Expiration': datetime.now(timezone.utc) + timedelta(seconds=seconds)}}
    sts.assume_role_with_web_identity.side_effect = [response('first-key', 60), response('second-key', 3600)]
    def client(service, **kwargs):
        if service == 'sts':
            return sts
        return create_client(service, **kwargs)
    monkeypatch.setattr(session, 'create_client', client)
    loader = Mock(side_effect=['first-jwt', 'second-jwt'])
    monkeypatch.setattr(m, 'github_identity_token', loader)
    s3 = m.s3_client(session)
    # Signing successive multipart requests uses the renewed session on the same
    # client, without waiting an hour or making network requests.
    args = {'Bucket': 'bucket', 'Key': 'image', 'UploadId': 'upload', 'PartNumber': 1}
    first = s3.generate_presigned_url('upload_part', Params=args)
    second = s3.generate_presigned_url('upload_part', Params=dict(args, PartNumber=2))
    assert 'first-key' in first and 'second-key' in second
    assert 'expired-static' not in first + second
    assert loader.call_count == 2
    calls = sts.assume_role_with_web_identity.call_args_list
    assert [call.kwargs['WebIdentityToken'] for call in calls] == ['first-jwt', 'second-jwt']
    assert all(call.kwargs['DurationSeconds'] == 3600 for call in calls)


def test_oidc_request_uses_aws_audience(github, monkeypatch):
    opener = Mock()
    opener.open.return_value = io.BytesIO(json.dumps({'value': 'jwt'}).encode())
    monkeypatch.setattr(m, 'build_opener', lambda *a: opener)
    assert m.github_identity_token() == 'jwt'
    request = opener.open.call_args.args[0]
    assert parse_qs(urlsplit(request.full_url).query) == {'request': ['1'], 'audience': ['sts.amazonaws.com']}
    assert request.get_header('Authorization') == 'Bearer request-secret'


def test_oidc_failure_does_not_leak_response_or_request_secrets(github, monkeypatch):
    opener = Mock()
    opener.open.side_effect = RuntimeError('request-secret response-secret')
    monkeypatch.setattr(m, 'build_opener', lambda *a: opener)
    with pytest.raises(RuntimeError, match='Could not obtain') as error:
        m.github_identity_token()
    assert 'secret' not in str(error.value)


def test_github_missing_oidc_does_not_fall_back_to_expired_environment(github, monkeypatch):
    monkeypatch.delenv('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
    with pytest.raises(RuntimeError, match='requires OIDC'):
        m.s3_client()


def test_local_execution_keeps_normal_provider_chain(monkeypatch):
    import boto3
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    client = Mock()
    monkeypatch.setattr(boto3, 'client', client)
    assert m.s3_client() is client.return_value
    client.assert_called_once_with('s3')
