"""Exercise the actual embedded writer and CLI failure handling without Docker."""
import ast
import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[2] / 'tools/neat-session-time.py'
WRITER = next(ast.literal_eval(n.value) for n in ast.parse(HELPER.read_text()).body
              if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'writer' for t in n.targets))


class SessionHelperTests(unittest.TestCase):
    def test_missing_cleared_and_invalid_state_are_actionable(self):
        for initial in (None, '{"expiresAt":null}', '{bad', '[]'):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'session.json'
                if initial is not None:
                    target.write_text(initial)
                result = subprocess.run([sys.executable, '-c', WRITER.replace("'/run/sima-neat'", repr(folder)), '{"display":"warning","blink":true}'], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('--minutes', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(target.read_text() if target.exists() else None, initial)

    def test_display_update_preserves_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'session.json'
            target.write_text('{"expiresAt":"2026-10-21T18:00:00Z","display":"quiet"}')
            subprocess.run([sys.executable, '-c', WRITER.replace("'/run/sima-neat'", repr(folder)), '{"display":"warning","blink":true}'], check=True)
            self.assertEqual(json.loads(target.read_text()), dict(expiresAt='2026-10-21T18:00:00Z', display='warning', blink=True))

    def test_color_only_update_payload(self):
        with patch.object(sys, 'argv', [str(HELPER), 'test-container', '--blink-color', 'amber']), patch('subprocess.run') as run, contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(HELPER), run_name='__main__')
            self.assertEqual(json.loads(run.call_args.args[0][-1]), {'blinkColor': 'amber'})

    def test_rejects_unsupported_timezone_offsets_before_docker(self):
        for timestamp in ('2026-10-21T18:00:00+01:02:03',
                          '2026-10-21T18:00:00-01:02:03',
                          '2026-10-21T18:00:00+01:02:03.5',
                          '2026-10-21T18:00:00+01:02.5',
                          '2026-10-21T18:00:00',
                          '2026-10-21T18:00:00+0102'):
            with self.subTest(timestamp=timestamp), patch.object(sys, 'argv', [str(HELPER), 'test-container', '--expires-at', timestamp]), patch('subprocess.run') as run, contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as error:
                    runpy.run_path(str(HELPER), run_name='__main__')
                self.assertEqual(error.exception.code, 2)
                self.assertIn('Invalid --expires-at', stderr.getvalue())
                self.assertIn('HH:MM', stderr.getvalue())
                run.assert_not_called()

    def test_supported_timestamps_emit_extension_parseable_deadlines(self):
        for timestamp in ('2026-10-21T18:00:00Z',
                          '2026-10-21T18:00:00+01:02',
                          '2026-10-21T18:00:00-07:00',
                          '2026-10-21T18:00:00.123456Z',
                          '2026-10-21T18:00+01:02'):
            with self.subTest(timestamp=timestamp), patch.object(sys, 'argv', [str(HELPER), 'test-container', '--expires-at', timestamp]), patch('subprocess.run') as run, contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(HELPER), run_name='__main__')
                payload = run.call_args.args[0][-1]
            result = subprocess.run(['node', '-e',
                                     "const {parseDeadline}=require(process.argv[1]); console.log(parseDeadline(process.argv[2]));",
                                     str(HELPER.parents[1] / 'vscode-extension/src/session-time.js'), payload],
                                    capture_output=True, text=True, check=True)
            self.assertGreater(int(result.stdout), 0)

    def test_docker_failure_exits_without_traceback(self):
        with patch.object(sys, 'argv', [str(HELPER), 'test-container', '--display', 'warning']), patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'docker')), contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as error:
                runpy.run_path(str(HELPER), run_name='__main__')
            self.assertEqual(error.exception.code, 1)
            self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
