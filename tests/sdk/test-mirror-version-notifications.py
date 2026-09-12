"""Version notification grouping, quiet runs, and durable failure recovery."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location('notifications', ROOT / 'scripts/notify-mirror-versions.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
RUN = 'https://github.com/sima-neat/sdk/actions/runs/123'
NEXT_RUN = 'https://github.com/sima-neat/sdk/actions/runs/456'


def test_combines_versions_with_run_link_and_deduplicates(tmp_path):
    state = tmp_path / 'state.json'
    send = Mock()
    versions = {'apt': ['3.0.0-1168', '3.0.0-1168'], 'images': ['3.0.0_daily_develop_B1168']}
    m.notify(state, versions, RUN, send)
    assert send.call_args.args[0] == (
        'Mirror changes published\nAPT: 3.0.0-1168\n'
        'Device images: <https://jenkins.eng.sima.ai/job/soc-jobs/job/elxr-builder/1168/console|3.0.0_daily_develop_B1168>\n'
        f'<{RUN}|GitHub workflow run>'
    )
    m.notify(state, versions, NEXT_RUN, send)
    m.notify(state, {'apt': [], 'images': []}, NEXT_RUN, send)
    send.assert_called_once()


def test_new_version_only_and_independent_categories(tmp_path):
    state = tmp_path / 'state.json'
    send = Mock()
    m.notify(state, {'apt': ['v1']}, RUN, send)
    m.notify(state, {'apt': ['v1', 'v2'], 'images': ['v1']}, NEXT_RUN, send)
    assert 'APT: v2\nDevice images: v1\n' in send.call_args.args[0]
    assert NEXT_RUN in send.call_args.args[0]


def test_failure_retries_on_no_change_preserving_detecting_run(tmp_path):
    state = tmp_path / 'state.json'
    with pytest.raises(RuntimeError, match='Slack unavailable'):
        m.notify(state, {'apt': ['v1']}, RUN, Mock(side_effect=RuntimeError('Slack unavailable')))
    data = json.loads(state.read_text())
    assert data['pending'] == [{'kind': 'apt', 'version': 'v1', 'run_url': RUN}]
    assert not data['seen']
    send = Mock()
    m.notify(state, {}, NEXT_RUN, send)
    assert RUN in send.call_args.args[0] and NEXT_RUN not in send.call_args.args[0]
    assert not json.loads(state.read_text())['pending']


def test_pending_and_new_events_keep_separate_original_run_links(tmp_path):
    state = tmp_path / 'state.json'
    with pytest.raises(RuntimeError):
        m.notify(state, {'apt': ['v1']}, RUN, Mock(side_effect=RuntimeError()))
    send = Mock()
    m.notify(state, {'apt': ['v1', 'v2']}, NEXT_RUN, send)
    assert len(send.call_args_list) == 2
    assert RUN in send.call_args_list[0].args[0]
    assert NEXT_RUN in send.call_args_list[1].args[0]


def test_reports_only_successful_publications():
    assert m.collect({'result': 'Published', 'platform': {'versions': ['v1']}},
                     {'result': 'Published', 'versions': ['old', 'image1'], 'copied_versions': ['image1']}) == {'apt': [], 'images': ['image1']}
    for result in ('Validated only', 'No change', 'Failed'):
        assert m.collect({'result': result, 'platform': {'versions': ['v1']}}, {}) == {'apt': [], 'images': []}
    assert m.collect({}, {'result': 'Published', 'versions': ['old', 'image1'], 'copied_versions': ['image1']}) == {'apt': [], 'images': ['image1']}


def test_empty_run_never_needs_slack_credentials(tmp_path):
    send = Mock()
    m.notify(tmp_path / 'state.json', {}, RUN, send)
    send.assert_not_called()


def test_versions_cannot_inject_slack_mentions(tmp_path):
    send = Mock()
    m.notify(tmp_path / 'state.json', {'apt': ['<!channel>&']}, RUN, send)
    assert '&lt;!channel&gt;&amp;' in send.call_args.args[0]
    assert '<!channel>' not in send.call_args.args[0]


def test_corrupt_state_is_not_reset(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text('{bad')
    with pytest.raises(json.JSONDecodeError):
        m.notify(state, {'apt': ['v1']}, RUN, Mock())
    assert state.read_text() == '{bad'


def test_workflow_uses_org_slack_settings_and_handles_partial_failure():
    workflow = yaml.safe_load((ROOT / '.github/workflows/sync-debian-pre-release-mirror.yml').read_text())
    step = workflow['jobs']['sync']['steps'][-1]
    assert step['env']['SLACK_BOT_TOKEN'] == '${{ secrets.SLACK_BOT_TOKEN }}'
    assert step['env']['SLACK_VULCAN_EVENT_CHANNEL_ID'] == '${{ vars.SLACK_VULCAN_EVENT_CHANNEL_ID }}'
    assert 'always()' in step['if'] and 'inputs.publish == true' in step['if']
    assert '${DEBIAN_MIRROR_WORK_ROOT}' in step['run']


def test_shared_slack_sender_rejects_api_failure(monkeypatch):
    import runpy
    import io
    sender = runpy.run_path(str(ROOT / 'scripts/post-debian-mirror-summary.py'))['post_message']
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: io.BytesIO(b'{"ok": false, "error": "not_in_channel"}'))
    with pytest.raises(RuntimeError, match='not_in_channel'):
        sender('test-token', 'C123', 'test')


def test_fresh_notification_state_only_announces_copied_images(tmp_path):
    send = Mock()
    versions = m.collect({}, {'result': 'Published', 'versions': ['old', 'new'], 'copied_versions': ['new']})
    m.notify(tmp_path / 'state.json', versions, RUN, send)
    assert 'Device images: new\n' in send.call_args.args[0]
    assert 'old' not in send.call_args.args[0]
    assert m.collect({}, {'result': 'Published', 'versions': ['old']})['images'] == []


def test_each_daily_image_links_to_its_jenkins_build(tmp_path):
    send = Mock()
    m.notify(tmp_path / 'state.json', {'images': ['3.0.0_daily_develop_B1295', '3.0.0_daily_develop_B1296']}, RUN, send)
    message = send.call_args.args[0]
    for number in (1295, 1296):
        assert f'<https://jenkins.eng.sima.ai/job/soc-jobs/job/elxr-builder/{number}/console|3.0.0_daily_develop_B{number}>' in message
    assert f'<{RUN}|GitHub workflow run>' in message


@pytest.mark.parametrize('version', ['unknown', '3.0.0_daily_release_B1295', '3.0.0_daily_develop_B1295/evil', '3.0.0_daily_develop_B1295\n', '<!channel>'])
def test_unrecognized_images_do_not_generate_jenkins_links(version):
    assert 'https://jenkins' not in m.format_version('images', version)
    assert '<!channel>' not in m.format_version('images', version)


def test_apt_versions_are_not_linked_to_jenkins():
    assert m.format_version('apt', '3.0.0_daily_develop_B1295') == '3.0.0_daily_develop_B1295'


def test_only_changed_versions_in_package_notification(tmp_path):
    report = {'result': 'Published', 'platform': {'versions': ['old', 'new']},
              'changes': {'baseline_available': True, 'version_changes': [
                  {'package': 'example', 'architecture': 'arm64', 'previous_versions': ['retained', 'old'], 'current_versions': ['retained', 'new']}]}}
    versions = m.collect(report, {})
    assert versions['packages'] == ['example (arm64): added new; removed old']
    send = Mock()
    m.notify(tmp_path / 'state.json', versions, RUN, send)
    assert 'APT package changes: 1' in send.call_args.args[0]
    assert 'retained' not in send.call_args.args[0]
    report['changes']['baseline_available'] = False
    assert m.collect(report, {}) == {'apt': [], 'images': []}


def test_package_preview_is_bounded(tmp_path):
    send = Mock()
    m.notify(tmp_path / 'state.json', {'packages': [f'pkg{i}: added v2' for i in range(16)]}, RUN, send)
    message = send.call_args.args[0]
    assert 'APT package changes: 16' in message
    assert message.count('• ') == 5
    assert '11 more' in message


@pytest.mark.parametrize('retry', [False, True])
def test_package_preview_prioritizes_additions_over_removals(tmp_path, retry):
    state = tmp_path / 'state.json'
    events = [f'a-removed-{i} (arm64): removed 1.0' for i in range(5)] + [
        'z-new (arm64): added 2.0',
        'y-updated (arm64): added 2.0; removed 1.0',
    ]
    if retry:
        state.write_text(json.dumps({
            'schema_version': 1, 'seen': {},
            'pending': [{'kind': 'packages', 'version': value, 'run_url': RUN}
                        for value in events],
        }))
    send = Mock()
    m.notify(state, {} if retry else {'packages': events}, NEXT_RUN if retry else RUN, send)
    message = send.call_args.args[0]
    bullets = [line for line in message.splitlines() if line.startswith('• ')]
    assert bullets[:2] == [
        '• y-updated (arm64): added 2.0; removed 1.0',
        '• z-new (arm64): added 2.0',
    ]
    assert len(bullets) == 5
    assert 'APT package changes: 7' in message
    assert '…and 2 more' in message
    assert f'<{RUN}|GitHub workflow run>' in message


def test_table_shows_all_sixteen_changes_with_full_versions(tmp_path):
    version = '2.2.0~git202609112047.177c0f3-1350'
    send = Mock()
    events = [f'pkg{i:02} (arm64): added {version}; removed 1.0' for i in range(16)]
    m.notify(tmp_path / 'state.json', {'packages': events}, RUN, send)
    blocks = send.call_args.kwargs['blocks']
    table = next(block for block in blocks if block['type'] == 'table')
    assert len(table['rows']) == 17
    assert [cell['text'] for cell in table['rows'][1]] == ['pkg00', 'arm64', '1.0', version]
    assert all(column['is_wrapped'] for column in table['column_settings'])
    assert RUN in blocks[-1]['text']['text']


def test_table_bounds_and_preserves_add_remove_and_multiple_versions(tmp_path):
    events = ['a (arm64): added 2.0, 3.0; removed 1.0', 'b (all): added 1.0']
    events += [f'z{i:03} (arm64): removed 1.0' for i in range(100)]
    send = Mock()
    m.notify(tmp_path / 'state.json', {'packages': events}, RUN, send)
    blocks = send.call_args.kwargs['blocks']
    table = next(block for block in blocks if block['type'] == 'table')
    assert len(table['rows']) == 100
    assert [cell['text'] for cell in table['rows'][1]] == ['a', 'arm64', '1.0', '2.0, 3.0']
    assert [cell['text'] for cell in table['rows'][2]] == ['b', 'all', '—', '1.0']
    assert [cell['text'] for cell in table['rows'][3]] == ['z000', 'arm64', '1.0', '—']
    assert any('3 more changes' in block.get('elements', [{}])[0].get('text', '') for block in blocks)


def test_package_table_retry_preserves_original_run_and_literal_cells(tmp_path):
    state = tmp_path / 'state.json'
    events = ['example (arm64): added <!channel>&; removed 1.0', 'legacy event']
    with pytest.raises(RuntimeError):
        m.notify(state, {'packages': events}, RUN, Mock(side_effect=RuntimeError()))
    send = Mock()
    m.notify(state, {}, NEXT_RUN, send)
    blocks = send.call_args.kwargs['blocks']
    table = next(block for block in blocks if block['type'] == 'table')
    assert table['rows'][1][3] == {'type': 'raw_text', 'text': '<!channel>&'}
    assert table['rows'][2][0]['text'] == 'legacy event'
    assert RUN in blocks[-1]['text']['text']
    assert NEXT_RUN not in json.dumps(blocks)
    assert not json.loads(state.read_text())['pending']


def test_shared_sender_includes_blocks_and_keeps_plain_text_compatible(monkeypatch):
    import io
    import runpy
    sender = runpy.run_path(str(ROOT / 'scripts/post-debian-mirror-summary.py'))['post_message']
    requests = []

    def respond(request, **kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr('urllib.request.urlopen', respond)
    blocks = m.message_blocks([], RUN)
    sender('test-token', 'C123', 'fallback', blocks=blocks)
    assert requests[-1]['blocks'] == blocks
    assert requests[-1]['text'] == 'fallback'
    sender('test-token', 'C123', 'daily digest')
    assert 'blocks' not in requests[-1]


@pytest.mark.parametrize('length', [1999, 2000, 2001, 5000])
def test_table_cell_limits_cover_versions_and_legacy_events(tmp_path, length):
    value = 'v' * length
    events = [f'package (arm64): added {value}; removed {value}', value]
    state = tmp_path / 'state.json'
    # A failed send retains the complete event for the next run.
    with pytest.raises(RuntimeError):
        m.notify(state, {'packages': events}, RUN, Mock(side_effect=RuntimeError()))
    assert {item['version'] for item in json.loads(state.read_text())['pending']} == set(events)
    send = Mock()
    m.notify(state, {}, NEXT_RUN, send)
    blocks = send.call_args.kwargs['blocks']
    table = next(block for block in blocks if block['type'] == 'table')
    expected = value if length <= 2000 else value[:2000 - len(m.TABLE_CELL_OVERFLOW)] + m.TABLE_CELL_OVERFLOW
    assert table['rows'][1][2]['text'] == expected
    assert table['rows'][1][3]['text'] == expected
    assert table['rows'][2][0]['text'] == expected
    assert all(len(cell['text']) <= 2000 for row in table['rows'] for cell in row)
    assert RUN in blocks[-1]['text']['text']
    assert not json.loads(state.read_text())['pending']
