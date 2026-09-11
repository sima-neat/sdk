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
        'New mirror versions detected\nAPT: 3.0.0-1168\n'
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
                     {'result': 'Published', 'versions': ['old', 'image1'], 'copied_versions': ['image1']}) == {'apt': ['v1'], 'images': ['image1']}
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


@pytest.mark.parametrize('version', ['unknown', '3.0.0_daily_develop_B1295/evil', '3.0.0_daily_develop_B1295\n', '<!channel>'])
def test_unrecognized_images_do_not_generate_jenkins_links(version):
    assert 'https://jenkins' not in m.format_version('images', version)
    assert '<!channel>' not in m.format_version('images', version)


def test_apt_versions_are_not_linked_to_jenkins():
    assert m.format_version('apt', '3.0.0_daily_develop_B1295') == '3.0.0_daily_develop_B1295'
