#!/usr/bin/env python3
"""Check exact firmware platform package sets in internal and external indexes.

This checks the palette anchor and its exact-version dependency closure. It is
not an APT solver or a verification of package payloads or unversioned base OS
requirements. Index bytes are checked against Release metadata for consistency;
this is not signature authentication of the internal HTTP repository.
"""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

INTERNAL = 'http://sw-web.eng.sima.ai/deb/daily'
EXTERNAL = 'https://debian.neat.sima.ai/daily'
INDEX = 'non-free/binary-arm64/Packages.gz'
ANCHOR = 'simaai-palette-modalix'
LIMIT = 128 * 1024 * 1024
IMAGE = re.compile(r'(3\.0\.0)_daily_[A-Za-z0-9_-]+_B([0-9]+)\Z')
RELATION = re.compile(r'([a-z0-9][a-z0-9+.-]*)(?::(?:any|native|arm64))?\s*(?:\((<<|<=|=|>=|>>)\s*([^()\s]+)\))?\Z')


def fetch(url):
    with urlopen(Request(url, headers={'Cache-Control': 'no-cache'}), timeout=45) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Index exceeds size limit')
    return data


def paragraphs(text):
    records = []
    for block in text.strip().split('\n\n'):
        fields = {}
        last = None
        for line in block.splitlines():
            if line.startswith((' ', '\t')) and last:
                fields[last] += ' ' + line.strip()
            else:
                last, value = line.split(':', 1)
                fields[last] = value.strip()
        records.append(fields)
    return records


def read_index(base, get=fetch):
    release = get(base + '/dists/agate/Release').decode()
    sha_lines = release.split('SHA256:\n', 1)[1].split('\n')
    expected = None
    for line in sha_lines:
        if not line.startswith(' '):
            break
        digest, size, path = line.split()
        if path == INDEX:
            expected = digest, int(size)
    if expected is None:
        raise ValueError('Release does not advertise the ARM64 index')
    index_path = INDEX
    if 'Acquire-By-Hash: yes' in release.splitlines():
        index_path = INDEX.rsplit('/', 1)[0] + '/by-hash/SHA256/' + expected[0]
    compressed = get(base + '/dists/agate/' + index_path)
    if (hashlib.sha256(compressed).hexdigest(), len(compressed)) != expected:
        raise ValueError('Repository index changed during check')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        payload = stream.read(LIMIT + 1)
    if len(payload) > LIMIT:
        raise ValueError('Expanded index exceeds size limit')
    records = paragraphs(payload.decode())
    if not records or not all({'Package', 'Version', 'Architecture'} <= p.keys() for p in records):
        raise ValueError('Invalid package index')
    return [p for p in records if p['Architecture'] in ('arm64', 'all')]


def available(records, image):
    match = IMAGE.fullmatch(image)
    if not match:
        return {'status': 'unknown', 'reason': 'Unrecognized firmware version'}
    release, build = match.groups()
    version_re = re.compile(re.escape(release) + r'~git[0-9]+\.[A-Za-z0-9]+-' + re.escape(build) + r'\Z')
    anchors = [p for p in records if p['Package'] == ANCHOR and version_re.fullmatch(p['Version'])]
    if not anchors:
        return {'status': 'missing', 'reason': 'Exact release/build palette package is absent'}
    by_key = {(p['Package'], p['Version']): p for p in records}

    def gaps(package, visiting):
        key = package['Package'], package['Version']
        if key in visiting:
            return []
        visiting = visiting | {key}
        missing = []
        for field in ('Pre-Depends', 'Depends'):
            for group in filter(None, package.get(field, '').split(',')):
                alternatives = [RELATION.fullmatch(part.strip()) for part in group.split('|')]
                if not all(alternatives):
                    raise ValueError('Unsupported dependency syntax')
                # Only exact pins define the vendor cohort. General base OS
                # constraints require a full SDK APT solve, outside this check.
                if any(item[2] != '=' for item in alternatives):
                    continue
                choices = [by_key.get((item[1], item[3])) for item in alternatives]
                if not any(p is not None and not gaps(p, visiting) for p in choices):
                    missing.append(group.strip())
        return missing

    failures = []
    for anchor in anchors:
        missing = gaps(anchor, set())
        if not missing:
            return {'status': 'available', 'version': anchor['Version']}
        failures.extend(missing)
    return {'status': 'incomplete', 'reason': 'Exact-version dependency chain is incomplete',
            'missing_dependencies': sorted(set(failures))}


def check(images, reader=read_index):
    results = {name: {'image': name} for name in images}
    # Keep both observations independent: external can still be ready if the
    # internal service is unavailable or has already pruned an older build.
    for label, url in (('internal', INTERNAL), ('external', EXTERNAL)):
        try:
            records = reader(url)
        except Exception:
            for item in results.values():
                item[label] = {'status': 'unknown', 'reason': 'Repository could not be checked'}
            continue
        for name, item in results.items():
            try:
                item[label] = available(records, name)
            except ValueError:
                item[label] = {'status': 'unknown', 'reason': 'Unsupported package metadata'}
    return {'schema_version': 1, 'scope': 'anchor-and-exact-dependency-index-availability',
            'builds': list(results.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-report', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.report.unlink(missing_ok=True)
    images = json.loads(args.image_report.read_text())
    if images.get('result') != 'Published':
        return
    report = check(images['versions'])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
