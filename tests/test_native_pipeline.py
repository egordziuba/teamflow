"""Real installed Hermes Kanban plus explicit test-only model doubles. No LLM calls."""
import tempfile
import unittest
from pathlib import Path

import pytest

from test_workflow import FakeBackend, SOURCE
from test_specialists import RoutingDouble, BRIEF

pytestmark = pytest.mark.usefixtures('hermes_repo')


class NativePipelineTests(unittest.TestCase):
    def test_native_board_roundtrip_csv_repair_and_cache(self):
        from teamflow.kanban import NativeBoard
        from teamflow.workflow import run_pilot
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / 'run'
            backend = FakeBackend()
            board = NativeBoard(self.hermes_repo, base / 'home', root)
            result = run_pilot(root, SOURCE, backend, inject_fault=True, board=board)
            self.assertEqual(result['status'], 'ACCEPTED')
            self.assertEqual(result['mode'], 'TEST_DOUBLE')
            before = len(backend.calls)
            rows_before = board.rows()
            self.assertEqual(len(rows_before), before)
            self.assertTrue(all(row['status'] == 'done' for row in rows_before))
            run_pilot(root, SOURCE, backend, inject_fault=True, board=board)
            self.assertEqual(len(backend.calls), before)
            self.assertEqual(board.rows(), rows_before)

    def test_native_board_specialist_handoff_drafts_not_project_done(self):
        from teamflow.kanban import NativeBoard
        from teamflow.specialists import run_specialists
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / 'run'
            board = NativeBoard(self.hermes_repo, base / 'home', root)
            backend = RoutingDouble([{'role': 'designer', 'reason': 'Layout needed', 'deliverable': 'Design spec'},
                                     {'role': 'copywriter', 'reason': 'Text needed', 'deliverable': 'Copy draft'}])
            result = run_specialists(root, BRIEF, backend, board=board)
            self.assertEqual(result['status'], 'DRAFTS_REQUIRE_REVIEW')
            self.assertEqual(backend.calls, ['coordinator', 'designer', 'copywriter', 'coordinator'])
            self.assertEqual(len(board.rows()), 4)


if __name__ == '__main__':
    unittest.main()
