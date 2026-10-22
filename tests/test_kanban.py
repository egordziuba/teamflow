"""Real subprocess tests: no model, dispatcher, or production Hermes home."""
from contextlib import closing
import importlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pytest

pytestmark = pytest.mark.usefixtures('hermes_repo')


class NativeBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='teamflow-kanban-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'isolated-home'
        self.run = self.root / 'run'

    def board(self):
        try:
            module = importlib.import_module('teamflow.kanban')
        except ModuleNotFoundError:
            self.fail('Native Kanban subprocess adapter is not implemented')
        return module.NativeBoard(self.hermes_repo, self.home, self.run)

    def sql(self, query, args=()):
        with closing(sqlite3.connect(self.run / 'kanban.db')) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, args)]

    def test_restart_replay_deduplicates_claim_and_completion(self):
        board = self.board()
        handle = board.start(7, 'developer', {'b': 2, 'a': 1})
        self.assertEqual(self.board().start(7, 'developer', {'a': 1, 'b': 2}), handle)
        board.finish(handle, {'answer': 'same'})
        history = self.sql('SELECT * FROM task_events')
        replay = self.board().start(7, 'developer', {'a': 1, 'b': 2})
        self.assertEqual(replay, handle)
        self.board().finish(replay, {'answer': 'same'})
        self.assertEqual(self.sql('SELECT * FROM task_events'), history)
        self.assertEqual(len(self.sql('SELECT * FROM task_runs')), 1)
        self.assertEqual(len(board.rows()), 1)

    def test_failure_is_native_block_with_fenced_run(self):
        board = self.board()
        handle = board.start(8, 'reviewer', {})
        self.assertTrue(hasattr(board, 'fail'), 'fail method is missing')
        from teamflow.kanban import KanbanError
        with self.assertRaises(KanbanError):
            board.fail({**handle, 'run_id': handle['run_id'] + 100}, 'secret-marker')
        board.fail(handle, 'secret-marker')
        self.assertEqual(board.rows()[0]['status'], 'blocked')
        runs = self.sql('SELECT * FROM task_runs')
        self.assertEqual(runs[0]['outcome'], 'blocked')
        self.assertNotIn('secret-marker', str(runs))
        with self.assertRaises(KanbanError):
            board.start(8, 'reviewer', {})

    def test_foreign_claim_cannot_be_replayed_or_completed(self):
        board = self.board()
        handle = board.start(7, 'developer', {})
        with closing(sqlite3.connect(self.run / 'kanban.db')) as conn:
            conn.execute("UPDATE tasks SET claim_lock = 'foreign-controller'")
            conn.commit()
        from teamflow.kanban import KanbanError
        with self.assertRaises(KanbanError):
            board.finish(handle, {'ok': True})
        with self.assertRaises(KanbanError):
            board.fail(handle, 'failure')
        with self.assertRaises(KanbanError):
            self.board().start(7, 'developer', {})
        self.assertEqual(board.rows()[0]['status'], 'running')

    def test_null_run_id_cannot_bypass_fencing(self):
        board = self.board()
        handle = board.start(7, 'developer', {})
        from teamflow.kanban import KanbanError
        with self.assertRaises(KanbanError):
            board.finish({**handle, 'run_id': None}, {})
        with self.assertRaises(KanbanError):
            board.finish({**handle, 'run_id': True}, {})
        self.assertEqual(board.rows()[0]['status'], 'running')

    def test_replay_rejects_broken_native_run_lease(self):
        board = self.board()
        board.start(7, 'developer', {})
        with closing(sqlite3.connect(self.run / 'kanban.db')) as conn:
            conn.execute("UPDATE task_runs SET claim_lock = 'foreign-controller'")
            conn.commit()
        from teamflow.kanban import KanbanError
        with self.assertRaises(KanbanError):
            self.board().start(7, 'developer', {})

    def test_refuses_inherited_profile_home(self):
        self.board()
        from teamflow.kanban import NativeBoard, KanbanError
        from unittest.mock import patch
        active = self.root / 'active-profile'
        active.mkdir()
        sentinel = active / 'config.yaml'
        sentinel.write_text('sentinel', encoding='utf-8')
        with patch.dict(os.environ, {'HERMES_HOME': str(active)}):
            with self.assertRaises(KanbanError):
                NativeBoard(self.hermes_repo, active, self.run)
            with self.assertRaises(KanbanError):
                NativeBoard(self.hermes_repo, self.home, active)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'sentinel')
        self.assertEqual(list(active.iterdir()), [sentinel])

    def test_completed_response_conflict_and_stale_handle_are_rejected(self):
        board = self.board()
        handle = board.start(7, 'developer', {})
        from teamflow.kanban import KanbanError
        with self.assertRaises(KanbanError):
            board.finish({**handle, 'run_id': handle['run_id'] + 99}, {})
        board.finish(handle, {'answer': 'accepted'})
        history = self.sql('SELECT * FROM task_events')
        with self.assertRaises(KanbanError):
            board.finish(handle, {'answer': 'different-secret-marker'})
        with self.assertRaises(KanbanError):
            board.finish({**handle, 'run_id': handle['run_id'] + 99}, {'answer': 'accepted'})
        self.assertEqual(self.sql('SELECT * FROM task_events'), history)
        self.assertEqual(len(self.sql('SELECT * FROM task_runs')), 1)

    def test_idempotency_scopes_request_role_ticket_and_root(self):
        board = self.board()
        handles = [board.start(7, 'developer', {}), board.start(7, 'developer', {'new': True}),
                   board.start(7, 'reviewer', {}), board.start(8, 'developer', {})]
        self.assertEqual(len({h['id'] for h in handles}), 4)
        from teamflow.kanban import NativeBoard
        other = NativeBoard(self.hermes_repo, self.home, self.root / 'other-run')
        other.start(7, 'developer', {})
        self.assertNotEqual(board.rows()[0]['idempotency_key'], other.rows()[0]['idempotency_key'])

    def test_real_child_environment_is_credential_free(self):
        import json
        import subprocess
        from unittest.mock import patch
        board = self.board()
        dirty = {'HERMES_KANBAN_TASK': 'inherited', 'HERMES_PROFILE': 'main',
                 'OPENAI_API_KEY': 'secret-marker', 'AWS_SECRET_ACCESS_KEY': 'secret-marker',
                 'UNRECOGNIZED_CREDENTIAL': 'secret-marker', 'PYTHONPATH': 'secret-marker'}
        with patch.dict(os.environ, dirty):
            environment = board._environment()
            result = subprocess.run([str(board.python), '-I', '-c',
                                     'import os,json; print(json.dumps(dict(os.environ)))'],
                                    env=environment, cwd=board.runtime_home,
                                    text=True, capture_output=True, shell=False, check=True)
            board.start(7, 'developer', {'text': '$(echo not-a-command); & |'})
        actual = json.loads(result.stdout)
        self.assertFalse(set(dirty) & set(actual))
        self.assertEqual(actual['HERMES_HOME'], str(board.runtime_home))
        self.assertEqual({k for k in actual if k.startswith('HERMES_')}, {'HERMES_HOME'})
        self.assertNotIn('secret-marker', str(board.rows()))

    def test_child_errors_are_structured_and_do_not_echo_secrets(self):
        import json
        import subprocess
        board = self.board()
        child = Path(importlib.import_module('teamflow.kanban').__file__).with_name('kanban_child.py')
        result = subprocess.run([str(board.python), '-I', str(child)],
                                input='{"secret-marker": invalid}', text=True,
                                capture_output=True, shell=False, cwd=board.runtime_home,
                                env=board._environment(), check=True)
        self.assertEqual(json.loads(result.stdout), {'ok': False, 'error': 'NativeOperationError'})
        self.assertEqual(result.stderr, '')

    def test_invalid_api_types_fail_closed_without_creating_tasks(self):
        board = self.board()
        from teamflow.kanban import KanbanError
        for ticket, role, request in [('secret-marker', 'developer', {}),
                                      (True, 'developer', {}),
                                      (7, 'secret-marker;command', {}),
                                      (7, 'developer', ['not-object'])]:
            with self.subTest(ticket=ticket, role=role), self.assertRaises(KanbanError):
                board.start(ticket, role, request)
        self.assertEqual(board.rows(), [])
        handle = board.start(7, 'developer', {})
        with self.assertRaises(KanbanError):
            board.finish(handle, ['not-object'])
        with self.assertRaises(KanbanError):
            board.fail(handle, {'not': 'string'})
        self.assertEqual(board.rows()[0]['status'], 'running')

    def test_real_claim_and_completion_have_native_history(self):
        board = self.board()
        handle = board.start(7, 'developer', {'task': 'local-only'})
        self.assertEqual(set(handle), {'id', 'run_id'})
        self.assertIsInstance(handle['run_id'], int)
        row = board.rows()[0]
        self.assertEqual(row['status'], 'running')
        self.assertEqual(row['current_run_id'], handle['run_id'])
        self.assertEqual(row['workspace_kind'], 'dir')
        board.finish(handle, {'ok': True})
        self.assertEqual(board.rows()[0]['status'], 'done')
        runs = self.sql('SELECT * FROM task_runs')
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['outcome'], 'completed')
        self.assertTrue(self.run.is_dir())
        self.assertNotIn('run_agent', __import__('sys').modules)


if __name__ == '__main__':
    unittest.main()
