"""Refresh AWS web-identity credentials throughout long-running image transfers."""
import json
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoCredentialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('GitHub OIDC redirects are not allowed')


def github_identity_token():
    url = urlsplit(os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'])
    if url.scheme != 'https' or not url.netloc:
        raise RuntimeError('GitHub OIDC requires an HTTPS endpoint')
    query = [(key, value) for key, value in parse_qsl(url.query) if key != 'audience']
    query.append(('audience', 'sts.amazonaws.com'))
    request = Request(
        urlunsplit(url._replace(query=urlencode(query))),
        headers={'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']},
    )
    try:
        with build_opener(NoCredentialRedirect()).open(request, timeout=30) as response:
            token = json.load(response).get('value')
    except Exception:
        # Do not echo endpoint query parameters, response bodies, or credentials.
        raise RuntimeError('Could not obtain a fresh GitHub OIDC token') from None
    if not isinstance(token, str) or not token:
        raise RuntimeError('GitHub OIDC response did not contain a token')
    return token


def s3_client(session=None):
    import boto3
    import botocore.session
    from botocore.credentials import (
        AssumeRoleWithWebIdentityCredentialFetcher, DeferredRefreshableCredentials,
    )

    if os.environ.get('GITHUB_ACTIONS') != 'true':
        return boto3.client('s3')
    required = ('ACTIONS_ID_TOKEN_REQUEST_URL', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN',
                'VULCAN_DEBIAN_MIRROR_PUBLISHER_ROLE_ARN', 'GITHUB_RUN_ID')
    if any(not os.environ.get(key) for key in required):
        raise RuntimeError('GitHub image mirroring requires OIDC and the publisher role configuration')
    session = session or botocore.session.get_session()
    session.set_config_variable('region', os.environ.get('AWS_REGION', 'us-west-2'))
    fetcher = AssumeRoleWithWebIdentityCredentialFetcher(
        client_creator=session.create_client,
        web_identity_token_loader=github_identity_token,
        role_arn=os.environ['VULCAN_DEBIAN_MIRROR_PUBLISHER_ROLE_ARN'],
        extra_args={'RoleSessionName': f"sdk-daily-images-{os.environ['GITHUB_RUN_ID']}",
                    'DurationSeconds': 3600},
    )
    # Override static credentials exported by configure-aws-credentials. Botocore
    # refreshes under its credential lock before signing requests (including
    # multipart UploadPart calls), fetching a new GitHub token on every renewal.
    session._credentials = DeferredRefreshableCredentials(
        refresh_using=fetcher.fetch_credentials, method='assume-role-with-web-identity',
    )
    return boto3.Session(botocore_session=session).client('s3')
