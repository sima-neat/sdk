import importlib.util
from pathlib import Path
import unittest
from unittest import mock
import json
import io
import os
import tempfile
import contextlib

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).resolve().parents[2] / 'scripts/publish-components.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublicationGateTests(unittest.TestCase):
    def event(self):
        return {'repository': {'full_name': 'sima-neat/sdk'}, 'workflow_run': {
            'name': 'Build SDK Docker Image', 'conclusion': 'success', 'head_branch': 'main',
            'event': 'push', 'head_repository': {'full_name': 'sima-neat/sdk'}, 'head_sha': 'a'*40}}

    def test_successful_main_build_revision(self):
        self.assertEqual(publisher.merged_revision(self.event(), 'workflow_run'), 'a'*40)

    def test_branch_tag_pr_failed_and_foreign_builds_are_rejected(self):
        for field, value in [('head_branch','develop'),('head_branch','v3.0.0'),
                             ('event','pull_request'),('conclusion','failure'),('name','Other workflow'),
                             ('head_repository',{'full_name':'other/sdk'}),('head_sha','bad')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                event=self.event();event['workflow_run'][field]=value
                publisher.merged_revision(event,'workflow_run')

    def test_manual_and_direct_push_events_cannot_bypass_gate(self):
        for name in ('workflow_dispatch','push','pull_request','schedule'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                publisher.merged_revision(self.event(),name)


    def test_conditional_write_and_main_race(self):
        root = Path(__file__).resolve().parents[2]
        catalog = json.loads((root / 'components.json').read_text())
        for advance in (False, True):
            with self.subTest(advance=advance), tempfile.TemporaryDirectory() as tmp:
                event = Path(tmp) / 'event.json'; event.write_text(json.dumps(self.event()))
                manifest = Path(tmp) / 'manifest.json'; manifest.write_text(json.dumps(catalog))
                previous = dict(catalog, publication={'manual_test': True})
                s3 = mock.MagicMock()
                s3.get_object.return_value = {'ETag': 'prior-etag', 'Body': io.BytesIO(json.dumps(previous).encode())}
                s3.put_object.return_value = {'ETag': 'new-etag', 'VersionId': 'new-version'}
                sts = mock.MagicMock(); sts.get_caller_identity.return_value = {'Account': publisher.ACCOUNT}
                cdn = mock.MagicMock(); cdn.create_invalidation.return_value = {'Invalidation': {'Id': 'test-invalidation'}}
                boto = mock.MagicMock()
                boto.Session.return_value.client.side_effect = lambda name: {'s3':s3,'sts':sts,'cloudfront':cdn}[name]
                head_reads = []
                def run(*args):
                    if args[:3] == ('gh','api','repos/sima-neat/sdk/commits/main'):
                        head_reads.append(1)
                        return 'b'*40 if advance and len(head_reads)>1 else 'a'*40
                    if args[0] == 'gh':
                        return json.dumps([{'merged_at':'2026-11-01','merge_commit_sha':'a'*40,'base':{'ref':'main'}}])
                    if args[:2] == ('git','show'): return json.dumps(catalog)
                    if args[0] == 'git': return 'a'*40
                    return ''
                env = {'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'workflow_run',
                    'SSE_KMS_KEY_ID':'arn:aws:kms:us-west-2:'+publisher.ACCOUNT+':key/test'}
                with mock.patch.dict(os.environ, env), mock.patch.dict('sys.modules', {'boto3':boto}), \
                     mock.patch.object(publisher, 'run', side_effect=run), \
                     mock.patch('sys.argv',['publish-components','--manifest',str(manifest),'--output',str(Path(tmp)/'out.json')]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    if advance:
                        with self.assertRaisesRegex(ValueError,'Main advanced'): publisher.main()
                        s3.put_object.assert_not_called()
                    else:
                        publisher.main()
                        self.assertEqual(s3.put_object.call_args.kwargs['IfMatch'],'prior-etag')
                        self.assertEqual(s3.put_object.call_args.kwargs['SSEKMSKeyId'],env['SSE_KMS_KEY_ID'])
                        self.assertIn('must-revalidate',s3.put_object.call_args.kwargs['CacheControl'])


if __name__ == '__main__':
    unittest.main()
