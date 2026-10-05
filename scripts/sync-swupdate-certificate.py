#!/usr/bin/env python3
"""Mirror the build-signing public certificate independently of APT metadata."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen

SOURCE = 'http://sw-web.eng.sima.ai/deb/swupdate-signing-cert.pem'
KEY = 'daily/swupdate-signing-cert.pem'
MAX_BYTES = 64 * 1024


def download_certificate():
    with urlopen(SOURCE, timeout=120) as response:
        certificate = response.read(MAX_BYTES + 1)
    if not certificate or len(certificate) > MAX_BYTES:
        raise ValueError('Empty or oversized SWUpdate certificate')
    # Require exactly one public certificate, without a private key or other
    # trailing PEM objects. OpenSSL alone accepts trailing arbitrary content.
    pem = certificate.strip()
    begin = b'-----BEGIN CERTIFICATE-----'
    end = b'-----END CERTIFICATE-----'
    if (not pem.startswith(begin) or not pem.endswith(end)
            or pem.count(b'-----BEGIN ') != 1 or pem.count(b'-----END ') != 1):
        raise ValueError('Expected exactly one PEM public certificate')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'certificate.pem'
        path.write_bytes(certificate)
        details = subprocess.run(
            ['openssl', 'x509', '-in', str(path), '-noout', '-subject',
             '-dates', '-fingerprint', '-sha256'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    return certificate, details


def synchronize(s3, bucket, kms_key, certificate, publish=False):
    digest = hashlib.sha256(certificate).hexdigest()
    if not publish:
        return 'Validated only', digest
    # List the exact prefix first: prefix-scoped ListBucket permissions can
    # make GetObject on a missing key return AccessDenied instead of NoSuchKey.
    listing = s3.list_objects_v2(Bucket=bucket, Prefix=KEY, MaxKeys=1)
    if any(item['Key'] == KEY for item in listing.get('Contents', [])):
        previous = s3.get_object(Bucket=bucket, Key=KEY)
        with previous['Body'] as body:
            if body.read(MAX_BYTES + 1) == certificate:
                return 'No change', digest
    s3.put_object(
        Bucket=bucket, Key=KEY, Body=certificate,
        ServerSideEncryption='aws:kms', SSEKMSKeyId=kms_key,
        ContentType='application/x-pem-file',
        CacheControl='no-cache,no-store,must-revalidate',
        Metadata={'sha256': digest, 'source-url': SOURCE},
    )
    return 'Published', digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    certificate, details = download_certificate()
    s3 = None
    bucket = os.environ.get('VULCAN_DEBIAN_MIRROR_BUCKET', 'sima-neat-debian-production')
    kms_key = os.environ.get('VULCAN_DEBIAN_MIRROR_KMS_KEY_ID', '')
    if args.publish:
        if not kms_key:
            parser.error('VULCAN_DEBIAN_MIRROR_KMS_KEY_ID is required for publication')
        from mirror_aws import s3_client
        s3 = s3_client()
    result, digest = synchronize(s3, bucket, kms_key, certificate, args.publish)
    summary = (f'SWUpdate certificate: {result}\n'
               f'Source: {SOURCE}\nDestination: s3://{bucket}/{KEY}\n'
               f'File SHA256: {digest}\n{details}\n')
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write('## SWUpdate verification certificate\n\n```text\n' + summary + '```\n')


if __name__ == '__main__':
    main()
