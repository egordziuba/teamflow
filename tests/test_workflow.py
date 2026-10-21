import importlib.util
import tempfile
import unittest
from pathlib import Path


SOURCE = 'id;amount;currency;status\nA;12,50;EUR;settled\nB;-2,00;EUR;settled\n'


class FakeBackend:
    """Explicit unit-test double. Never used by the live CLI."""
    def __init__(self):
        self.calls = []

    def call(self, role, request):
        from teamflow.pilot import expected_result, check_candidate
        self.calls.append(role)
        if role == 'analyst':
            return {'source_sha256': request['source_sha256'], 'delimiter': ';',
                    'decimal_separator': ',', 'findings': ['Source delimiter is semicolon, not comma.']}
        if role == 'coordinator':
            return {'source_sha256': request['source_sha256'],
                    'contract_sha256': request['contract_sha256'],
                    'instruction': 'Reconcile every source row against the fixed acceptance contract.'}
        if role == 'implementer':
            return expected_result(request['source'])
        checks = check_candidate(request['source'], request['candidate'])
        good = all(c['passed'] for c in checks)
        return {'verdict': 'PASS' if good else 'FIX_REQUIRED',
                'artifact_sha256': request['artifact_sha256'], 'checks': checks,
                'issues': [] if good else ['Incorrect total. Recalculate from accepted source rows.']}


class WorkflowTests(unittest.TestCase):
    def test_defective_candidate_rejected_then_repaired_and_resume_cached(self):
        self.assertIsNotNone(importlib.util.find_spec('teamflow.workflow'), 'Workflow missing')
        from teamflow.workflow import run_pilot
        with tempfile.TemporaryDirectory() as td:
            backend = FakeBackend()
            result = run_pilot(Path(td), SOURCE, backend, inject_fault=True)
            self.assertEqual(result['status'], 'ACCEPTED')
            self.assertEqual([a['accepted'] for a in result['attempts']], [False, True])
            self.assertEqual(result['context_revision'], 2)
            self.assertIn('analyst', backend.calls)
            self.assertIn('coordinator', backend.calls)
            self.assertIn('implementer', backend.calls)
            self.assertIn('verifier', backend.calls)
            before = len(backend.calls)
            again = run_pilot(Path(td), SOURCE, backend, inject_fault=True)
            self.assertEqual(again['status'], 'ACCEPTED')
            self.assertEqual(before, len(backend.calls))

    def test_source_or_artifact_changes_invalidate_resume(self):
        from teamflow.workflow import run_pilot
        from teamflow.ledger import GateError
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = FakeBackend()
            result = run_pilot(root, SOURCE, backend)
            before = len(backend.calls)
            with self.assertRaises(GateError):
                run_pilot(root, SOURCE + 'X;1,00;EUR;settled\n', backend)
            (root / result['artifact']).write_text('{}', encoding='utf-8')
            with self.assertRaises(GateError):
                run_pilot(root, SOURCE, backend)
            self.assertEqual(before, len(backend.calls))

    def test_stagnating_repair_stops_before_attempt_budget(self):
        from teamflow.workflow import run_pilot
        from teamflow.ledger import GateError
        class Broken(FakeBackend):
            def call(self, role, request):
                response = super().call(role, request)
                if role == 'implementer':
                    response['total_eur'] = '0.00'
                return response
        with tempfile.TemporaryDirectory() as td:
            backend = Broken()
            with self.assertRaisesRegex(GateError, 'No progress'):
                run_pilot(Path(td), SOURCE, backend)
            self.assertEqual(backend.calls.count('implementer'), 2)

    def test_workspace_lock_prevents_second_controller(self):
        import teamflow.workflow as workflow
        self.assertTrue(hasattr(workflow, 'workspace_lock'), 'Workspace lock missing')
        from teamflow.ledger import GateError
        with tempfile.TemporaryDirectory() as td:
            backend = FakeBackend()
            with workflow.workspace_lock(Path(td)):
                with self.assertRaisesRegex(GateError, 'already running'):
                    workflow.run_pilot(Path(td), SOURCE, backend)
            self.assertEqual(backend.calls, [])

    def test_cached_response_repairs_board_after_handoff_failure(self):
        from teamflow.workflow import run_pilot
        class Board:
            def __init__(self):
                self.broken = True
                self.completed = set()
            def start(self, ticket, role, request):
                return ticket
            def finish(self, card, response):
                if self.broken:
                    self.broken = False
                    raise RuntimeError('test handoff interruption')
                self.completed.add(card)
            def fail(self, card, reason):
                pass
        with tempfile.TemporaryDirectory() as td:
            root, backend, board = Path(td), FakeBackend(), Board()
            with self.assertRaises(RuntimeError):
                run_pilot(root, SOURCE, backend, board=board)
            result = run_pilot(root, SOURCE, backend, board=board)
            self.assertEqual(result['status'], 'ACCEPTED')
            self.assertIn(1, board.completed)
            self.assertEqual(backend.calls.count('analyst'), 1)

    def test_changed_model_configuration_cannot_reuse_run(self):
        from teamflow.workflow import run_pilot
        from teamflow.ledger import GateError
        class Identified(FakeBackend):
            model = 'first'
            def fingerprint(self):
                return {'model': self.model}
        with tempfile.TemporaryDirectory() as td:
            backend = Identified()
            run_pilot(Path(td), SOURCE, backend)
            before = len(backend.calls)
            backend.model = 'other'
            with self.assertRaises(GateError):
                run_pilot(Path(td), SOURCE, backend)
            self.assertEqual(len(backend.calls), before)


if __name__ == '__main__':
    unittest.main()
