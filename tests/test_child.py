import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ChildTests(unittest.TestCase):
    def test_child_refuses_unknown_role_before_hermes_import(self):
        self.assertIsNotNone(importlib.util.find_spec('teamflow.hermes_child'), 'Hermes child missing')
        proc = subprocess.run([sys.executable, '-m', 'teamflow.hermes_child'],
                              input=json.dumps({'role': 'admin'}), text=True, capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('invalid_request', proc.stdout)
        self.assertNotIn('Traceback', proc.stdout)

    def test_no_tools_is_enforced_and_no_fallback_response(self):
        import teamflow.hermes_child as child
        self.assertTrue(hasattr(child, 'run_agent_call'), 'Model boundary missing')
        class Agent:
            tools = []
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.session_id = 'test-session'
            def run_conversation(self, **kwargs):
                return {'final_response': '{"ok":true}', 'messages': []}
        data = {'request': {'x': 1}, 'system': 'role', 'model': 'test', 'provider': 'test'}
        result = child.run_agent_call(Agent, {'provider': 'test', 'api_key': 'not-a-real-credential'}, data)
        self.assertEqual(result['response'], {'ok': True})
        self.assertEqual(result['tool_count'], 0)
        class Unsafe(Agent):
            tools = [{'function': {'name': 'terminal'}}]
            def run_conversation(self, **kwargs):
                raise AssertionError('Unsafe model call occurred')
        with self.assertRaisesRegex(ValueError, 'tools_not_empty'):
            child.run_agent_call(Unsafe, {}, data)

    def test_registry_specialist_allowed_and_bad_profile_rejected(self):
        from teamflow.hermes_child import validate_request
        good = {'role': 'designer', 'request': {}, 'model': 'test', 'provider': 'openai-codex',
                'profile_home': 'x', 'hermes_repo': 'x', 'system': 'x'}
        validate_request(good)
        for key in ['profile_home', 'model', 'system']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_request(dict(good, **{key: ''}))

    def test_stream_consumer_records_counts_without_recording_text(self):
        from teamflow.hermes_child import run_agent_call
        progress = []
        class Agent:
            tools = []
            session_id = 'stream-test'
            def __init__(self, **kwargs):
                pass
            def run_conversation(self, **kwargs):
                callback = kwargs.get('stream_callback')
                self_test.assertTrue(callable(callback), 'Streaming consumer missing')
                callback('SENSITIVE_STREAM_TEXT')
                callback(None)
                return {'final_response': '{"ok":true}', 'messages': []}
        self_test = self
        data = {'request': {}, 'system': 'test', 'model': 'test', 'provider': 'test', 'streaming': True}
        result = run_agent_call(Agent, {}, data, progress_sink=progress.append)
        self.assertEqual(result['response'], {'ok': True})
        self.assertGreater(result['telemetry']['stream_chunks'], 0)
        self.assertEqual(progress[-1]['phase'], 'completed')
        self.assertNotIn('SENSITIVE_STREAM_TEXT', json.dumps(result['telemetry']))
        self.assertNotIn('SENSITIVE_STREAM_TEXT', json.dumps(progress))

    def test_stream_diagnostic_identifiers_are_strict(self):
        from teamflow.hermes_child import validate_request
        good = {'role': 'designer', 'request': {}, 'model': 'test', 'provider': 'openai-codex',
                'profile_home': 'x', 'hermes_repo': 'x', 'system': 'x',
                'streaming': True, 'call_id': 'a' * 32}
        validate_request(good)
        for change in [{'streaming': 'true'}, {'call_id': '../escape'}, {'call_id': ''}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_request(dict(good, **change))

    def test_numeric_progress_is_persisted_without_raw_content(self):
        import teamflow.hermes_child as child
        self.assertTrue(hasattr(child, 'progress_sink'), 'Persistent progress sink missing')
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            sink = child.progress_sink(home, 'a' * 32)
            value = {'streaming': True, 'phase': 'waiting', 'stream_chunks': 0, 'stream_chars': 0,
                     'first_delta_seconds': None, 'last_delta_seconds': None, 'elapsed_seconds': 0.2}
            sink(value)
            saved = json.loads((home / 'telemetry' / ('a' * 32 + '.json')).read_text())
            self.assertEqual(saved, value)
            with self.assertRaises(ValueError):
                sink(dict(value, raw_text='DO_NOT_STORE'))
            self.assertEqual(json.loads((home / 'telemetry' / ('a' * 32 + '.json')).read_text()), value)


if __name__ == '__main__':
    unittest.main()
