import importlib.util
import tempfile
import unittest
from pathlib import Path


BRIEF = {'goal': 'Prepare website design and copy recommendations', 'project_type': 'website',
         'sources': [{'id': 'brief', 'text': 'B2B panel manufacturing. No invented project facts.'}],
         'acceptance': ['Clear hierarchy', 'Only sourced business claims']}


class RoutingDouble:
    live = False
    def __init__(self, requests):
        self.requests = requests
        self.calls = []
    def call(self, role, request):
        self.calls.append(role)
        if role == 'coordinator':
            if request.get('stage') == 'specialist-integration':
                return {'instruction': 'Use the supplied draft specifications in the next implementation stage.',
                        'specialist_roles': [x['role'] for x in request['specialist_reports']],
                        'open_questions': ['Human review of drafts is still required.']}
            return {'requests': self.requests, 'rationale': 'Only roles needed by the given brief.'}
        return {'role': role, 'source_sha256': request['source_sha256'],
                'contract_sha256': request['contract_sha256'],
                'deliverable': 'A test-only proposed specification, not a rendered result.',
                'limitations': ['TEST DOUBLE: no real model call.']}


class SpecialistTests(unittest.TestCase):
    def test_registered_specialist_uses_same_durable_budget(self):
        import tempfile
        from pathlib import Path
        from teamflow.ledger import RequestLedger, GateError
        with tempfile.TemporaryDirectory() as td:
            ledger = RequestLedger(Path(td) / 'roles.db', max_calls=1)
            ticket = ledger.reserve('designer', {'task': 'Prepare design specification'})
            self.assertEqual(ticket['state'], 'PENDING')
            with self.assertRaises(GateError):
                ledger.reserve('invented-role', {})
            with self.assertRaises(GateError):
                ledger.reserve('copywriter', {'task': 'Copy'})

    def test_only_requested_specialists_run_and_resume_is_cached(self):
        self.assertIsNotNone(importlib.util.find_spec('teamflow.specialists'), 'Specialist workflow missing')
        from teamflow.specialists import run_specialists
        with tempfile.TemporaryDirectory() as td:
            backend = RoutingDouble([{'role': 'designer', 'reason': 'Layout needed', 'deliverable': 'Design specification'},
                                     {'role': 'copywriter', 'reason': 'Copy needed', 'deliverable': 'Draft text'}])
            result = run_specialists(Path(td), BRIEF, backend)
            self.assertEqual(backend.calls, ['coordinator', 'designer', 'copywriter', 'coordinator'])
            self.assertEqual(result['activated_roles'], ['designer', 'copywriter'])
            self.assertEqual(result['status'], 'DRAFTS_REQUIRE_REVIEW')
            run_specialists(Path(td), BRIEF, backend)
            self.assertEqual(len(backend.calls), 4)
            self.assertTrue((Path(td) / 'integration.json').is_file())
        with tempfile.TemporaryDirectory() as td:
            backend = RoutingDouble([])
            run_specialists(Path(td), BRIEF, backend)
            self.assertEqual(backend.calls, ['coordinator'])

    def test_unknown_role_and_stale_output_are_not_accepted(self):
        from teamflow.specialists import run_specialists
        with tempfile.TemporaryDirectory() as td:
            backend = RoutingDouble([{'role': 'admin', 'reason': 'x', 'deliverable': 'x'}])
            with self.assertRaises(ValueError):
                run_specialists(Path(td), BRIEF, backend)
            self.assertEqual(backend.calls, ['coordinator'])
        class Stale(RoutingDouble):
            def call(self, role, request):
                response = super().call(role, request)
                if role != 'coordinator':
                    response['source_sha256'] = '0' * 64
                return response
        with tempfile.TemporaryDirectory() as td:
            backend = Stale([{'role': 'designer', 'reason': 'x', 'deliverable': 'x'}])
            with self.assertRaises(ValueError):
                run_specialists(Path(td), BRIEF, backend)
            self.assertFalse((Path(td) / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
