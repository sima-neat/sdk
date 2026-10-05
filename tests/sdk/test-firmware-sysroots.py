"""Exact-build readiness and consistent repository snapshots."""
import gzip
import hashlib
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('readiness', Path(__file__).parents[2] / 'scripts/check-firmware-sysroots.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
IMAGE = '3.0.0_daily_develop_B1371'
VERSION = '3.0.0~git202609120138.abcdef-1371'


def package(name=m.ANCHOR, version=VERSION, **fields):
    return {'Package': name, 'Version': version, 'Architecture': 'arm64', **fields}


def test_exact_release_build_and_architecture():
    for version in ('3.0.0~git202609120138.abcdef-1372', '2.1.2~git202609120138.abcdef-1371',
                    VERSION + '0', VERSION + '+neat1'):
        assert m.available([package(version=version)], IMAGE)['status'] == 'missing'
    assert m.available([package()], IMAGE)['status'] == 'available'
    assert m.available([package()], 'unknown')['status'] == 'unknown'


def test_dependency_chain_alternatives_and_cycles():
    anchor = package(Depends='vendor (= 2.1.1+neat1), libc6 (>= 2.36)')
    assert m.available([anchor, package('vendor', '2.1.1')], IMAGE)['status'] == 'incomplete'
    vendor = package('vendor', '2.1.1+neat1', **{'Pre-Depends': 'leaf (= 2) | fallback (= 1)'})
    assert m.available([anchor, vendor], IMAGE)['status'] == 'incomplete'
    leaf = package('fallback', '1', Depends=f'{m.ANCHOR} (= {VERSION})')
    assert m.available([anchor, vendor, leaf], IMAGE)['status'] == 'available'


def test_checks_internal_first_even_if_it_fails():
    calls = []
    def reader(url):
        calls.append(url)
        if url == m.INTERNAL:
            raise TimeoutError()
        return [package()]
    item = m.check([IMAGE], reader)['builds'][0]
    assert calls == [m.INTERNAL, m.EXTERNAL]
    assert item['internal']['status'] == 'unknown'
    assert item['external']['status'] == 'available'


def test_delayed_external_and_missing_internal():
    item = m.check([IMAGE], lambda url: [package()] if url == m.INTERNAL else [])['builds'][0]
    assert item['internal']['status'] == 'available'
    assert item['external']['status'] == 'missing'
    assert m.check([IMAGE], lambda url: [])['builds'][0]['internal']['status'] == 'missing'


def test_bad_metadata_is_unknown():
    item = m.check([IMAGE], lambda url: [package(Depends='broken (')])['builds'][0]
    assert item['internal']['status'] == 'unknown'


def fixture():
    payload = '\n\n'.join('\n'.join(f'{k}: {v}' for k, v in p.items()) for p in
                            [package(), package('foreign', '1', Architecture='amd64')])
    data = gzip.compress(payload.encode())
    release = f'Suite: agate\nSHA256:\n {hashlib.sha256(data).hexdigest()} {len(data)} {m.INDEX}\n'.encode()
    return data, release


def test_index_checksum_and_architecture_filter():
    data, release = fixture()
    records = m.read_index('http://fixture', lambda url: release if url.endswith('/Release') else data)
    assert records == [package()]
    with pytest.raises(ValueError, match='changed during check'):
        m.read_index('http://fixture', lambda url: release if url.endswith('/Release') else data + b'x')


def test_folded_dependencies():
    assert m.paragraphs('Package: example\nDepends: one (= 1),\n two (= 2)\n')[0]['Depends'] == 'one (= 1), two (= 2)'


def test_uses_immutable_by_hash_when_advertised():
    data, release = fixture()
    release = b'Acquire-By-Hash: yes\n' + release
    urls = []
    def get(url):
        urls.append(url)
        if url.endswith('/Release'):
            return release
        assert url.endswith('/by-hash/SHA256/' + hashlib.sha256(data).hexdigest())
        return data
    assert m.read_index('http://fixture', get) == [package()]
    assert len(urls) == 2


@pytest.mark.parametrize('required,candidate', [('1.0', '1.0-0'), ('1.0', '0:1.0'), ('1.01-01', '1.1-1')])
def test_debian_equivalent_dependency_versions(required, candidate):
    records = [package(Depends=f'vendor (= {required})'), package('vendor', candidate)]
    assert m.available(records, IMAGE)['status'] == 'available'


@pytest.mark.parametrize('candidate', ['1.0-1', '1:1.0', '1.0~rc1', '1.1'])
def test_debian_unequal_dependency_versions(candidate):
    records = [package(Depends='vendor (= 1.0)'), package('vendor', candidate)]
    assert m.available(records, IMAGE)['status'] == 'incomplete'


def test_equivalent_transitive_alternative_and_cycle():
    records = [package(Depends='absent (= 1) | vendor (= 1.0)'),
               package('vendor', '1.0-0', Depends='leaf (= 2.0)'),
               package('leaf', '0:2.0', Depends='vendor (= 1.0)')]
    assert m.available(records, IMAGE)['status'] == 'available'
    records.pop()
    assert m.available(records, IMAGE)['status'] == 'incomplete'


def test_all_equivalent_candidates_are_considered():
    records = [package(Depends='vendor (= 1.0)'),
               package('vendor', '1.0', Depends='missing (= 1)'),
               package('vendor', '1.0-0')]
    assert m.available(records, IMAGE)['status'] == 'available'


@pytest.mark.parametrize('failure', [OSError(), m.subprocess.TimeoutExpired('dpkg', 5), None])
def test_comparator_failure_reports_unknown(monkeypatch, failure):
    from types import SimpleNamespace
    m.versions_equal.cache_clear()
    def run(*args, **kwargs):
        if failure is not None:
            raise failure
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(m.subprocess, 'run', run)
    records = [package(Depends='vendor (= 1.0)'), package('vendor', '1.0-0')]
    report = m.check([IMAGE], lambda url: records)
    assert report['builds'][0]['internal']['status'] == 'unknown'
    assert report['builds'][0]['external']['status'] == 'unknown'


def test_comparisons_are_cached_and_literal_equality_is_fast(monkeypatch):
    from unittest.mock import Mock
    from types import SimpleNamespace
    m.versions_equal.cache_clear()
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(m.subprocess, 'run', run)
    assert m.versions_equal('1.0', '1.0')
    run.assert_not_called()
    assert m.versions_equal('1.0-0', '1.0')
    assert m.versions_equal('1.0-0', '1.0')
    run.assert_called_once()
    m.versions_equal.cache_clear()
