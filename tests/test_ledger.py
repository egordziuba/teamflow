import importlib.util
import unittest


class CanonicalTests(unittest.TestCase):
    def test_canonical_strict_json(self):
        try:
            spec = importlib.util.find_spec('teamflow.ledger')
        except ModuleNotFoundError:
            spec = None
        self.assertIsNotNone(spec, 'ledger module is required')
        from teamflow.ledger import canonical_hash, GateError
        self.assertEqual(canonical_hash({'b': 2, 'a': 1}), canonical_hash({'a': 1, 'b': 2}))
        self.assertEqual(len(canonical_hash({})), 64)
        for value in [float('nan'), float('inf'), {1: 'x'}, (1, 2), {'a': object()}]:
            with self.subTest(value=repr(value)), self.assertRaises(GateError):
                canonical_hash(value)


class VerdictTests(unittest.TestCase):
    def test_verdict_contract(self):
        import teamflow.ledger as module
        self.assertTrue(hasattr(module, 'validate_verdict'))
        valid = {'verdict': 'PASS', 'artifact_sha256': 'a' * 64,
                 'checks': [{'id': 'c1', 'passed': True, 'evidence': 'test log'}], 'issues': []}
        self.assertEqual(module.validate_verdict(valid, 'a' * 64, ['c1']), 'PASS')
        import copy
        mutations = [
            lambda v: v.update(extra=1),
            lambda v: v.update(verdict='UNKNOWN'),
            lambda v: v.update(artifact_sha256='b' * 64),
            lambda v: v.update(checks=[]),
            lambda v: v['checks'].append(v['checks'][0].copy()),
            lambda v: v['checks'][0].update(passed=1),
            lambda v: v['checks'][0].update(passed='true'),
            lambda v: v['checks'][0].pop('evidence'),
            lambda v: v['checks'][0].update(evidence='  '),
            lambda v: v['checks'][0].update(passed=False),
            lambda v: v.update(issues=['broken']),
            lambda v: v.update(issues=[1]),
        ]
        for index, mutate in enumerate(mutations):
            value = copy.deepcopy(valid)
            mutate(value)
            with self.subTest(index=index), self.assertRaises(module.GateError):
                module.validate_verdict(value, 'a' * 64, ['c1'])
        for state in ['FIX_REQUIRED', 'CONTEXT_INVALID', 'NEEDS_DECISION']:
            value = copy.deepcopy(valid)
            value.update(verdict=state, issues=['needs work'])
            value['checks'][0]['passed'] = False
            self.assertEqual(module.validate_verdict(value, 'a' * 64, ['c1']), state)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'journal.sqlite'

    def test_concurrent_reservations_atomic_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from teamflow.ledger import RequestLedger, BudgetExceeded
        barrier = Barrier(8)
        def reserve(index):
            ledger = RequestLedger(self.path, max_calls=3)
            barrier.wait(timeout=15)
            try:
                return ledger.reserve('analyst', {'i': index})['state']
            except BudgetExceeded:
                return 'BUDGET'
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(8)))
        self.assertEqual(results.count('PENDING'), 3)
        self.assertEqual(results.count('BUDGET'), 5)
        ledger = RequestLedger(self.path, max_calls=3)
        self.assertEqual(len(ledger.rows()), 3)
        self.assertEqual(len(ledger.events()), 3)

    def test_concurrent_same_identity_single_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from teamflow.ledger import RequestLedger, AmbiguousRequest
        barrier = Barrier(6)
        def reserve(_):
            ledger = RequestLedger(self.path)
            barrier.wait(timeout=15)
            try:
                return ledger.reserve('analyst', {})['state']
            except AmbiguousRequest:
                return 'AMBIGUOUS'
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(reserve, range(6)))
        self.assertEqual(results.count('PENDING'), 1)
        self.assertEqual(results.count('AMBIGUOUS'), 5)
        self.assertEqual(len(RequestLedger(self.path).events()), 1)

    def test_restart_cannot_expand_durable_budget(self):
        from teamflow.ledger import RequestLedger, BudgetExceeded
        ledger = RequestLedger(self.path, max_calls=1)
        ledger.reserve('analyst', {})
        with self.assertRaises(BudgetExceeded):
            RequestLedger(self.path, max_calls=12).reserve('analyst', {'different': True})

    def test_events_append_only_and_atomic_rollback(self):
        import sqlite3
        from contextlib import closing
        from teamflow.ledger import RequestLedger
        ledger = RequestLedger(self.path)
        ticket = ledger.reserve('analyst', {})
        with closing(sqlite3.connect(self.path, isolation_level=None)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM events')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE events SET state='FAILED'")
            db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END")
        for operation in [lambda: ledger.reserve('analyst', {'new': True}),
                          lambda: ledger.complete(ticket['id'], {}),
                          lambda: ledger.fail(ticket['id'], 'error')]:
            with self.assertRaises(sqlite3.IntegrityError):
                operation()
            self.assertEqual(len(ledger.rows()), 1)
            self.assertEqual(ledger.status(ticket['id'])['state'], 'PENDING')
            self.assertEqual(len(ledger.events()), 1)

    def test_failed_ticket_never_retried(self):
        import teamflow.ledger as m
        ledger = m.RequestLedger(self.path)
        self.assertTrue(hasattr(ledger, 'fail'))
        ticket = ledger.reserve('coordinator', {})
        self.assertEqual(ledger.fail(ticket['id'], 'private-error')['state'], 'FAILED')
        restarted = m.RequestLedger(self.path)
        with self.assertRaises(m.AmbiguousRequest):
            restarted.reserve('coordinator', {})
        with self.assertRaises(m.GateError):
            restarted.complete(ticket['id'], {})
        with self.assertRaises(m.GateError):
            restarted.fail(ticket['id'], 'again')
        self.assertEqual([e['state'] for e in restarted.events()], ['PENDING', 'FAILED'])
        self.assertNotIn('private-error', str(restarted.rows()) + str(restarted.events()))

    def test_complete_once_cached_receipt(self):
        import teamflow.ledger as m
        ledger = m.RequestLedger(self.path, max_calls=1)
        self.assertTrue(hasattr(ledger, 'complete'))
        ticket = ledger.reserve('implementer', {'task': 'x'})
        for invalid in [[], None, {'n': float('nan')}]:
            with self.subTest(invalid=invalid), self.assertRaises(m.GateError):
                ledger.complete(ticket['id'], invalid)
        self.assertEqual(ledger.status(ticket['id'])['state'], 'PENDING')
        receipt = ledger.complete(ticket['id'], {'result': 'ok'})
        self.assertEqual(receipt, {'id': ticket['id'], 'state': 'COMPLETED', 'response': {'result': 'ok'}})
        restarted = m.RequestLedger(self.path, max_calls=1)
        self.assertEqual(restarted.reserve('implementer', {'task': 'x'}), receipt)
        with self.assertRaises(m.GateError):
            restarted.complete(ticket['id'], {'result': 'other'})
        with self.assertRaises(m.GateError):
            restarted.complete(999, {})
        self.assertEqual(restarted.status(ticket['id']), receipt)
        self.assertEqual([e['state'] for e in ledger.events()], ['PENDING', 'COMPLETED'])
        self.assertEqual(len(ledger.rows()), 1)

    def test_durable_pending_budget_and_role_identity(self):
        import teamflow.ledger as m
        self.assertTrue(hasattr(m, 'RequestLedger'))
        ledger = m.RequestLedger(self.path, max_calls=2)
        ticket = ledger.reserve('analyst', {'secret': 'not-for-summary', 'a': 1})
        self.assertEqual(ticket['state'], 'PENDING')
        restarted = m.RequestLedger(self.path, max_calls=2)
        with self.assertRaises(m.AmbiguousRequest):
            restarted.reserve('analyst', {'a': 1, 'secret': 'not-for-summary'})
        other = restarted.reserve('verifier', {'secret': 'not-for-summary', 'a': 1})
        self.assertNotEqual(ticket['id'], other['id'])
        with self.assertRaises(m.BudgetExceeded):
            m.RequestLedger(self.path, max_calls=2).reserve('analyst', {'a': 2})
        self.assertEqual(restarted.status(ticket['id'])['state'], 'PENDING')
        self.assertEqual(len(restarted.rows()), 2)
        self.assertNotIn('not-for-summary', str(restarted.rows()))
        self.assertEqual([e['state'] for e in restarted.events()], ['PENDING', 'PENDING'])
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertIn('not-for-summary', db.execute('SELECT request_json FROM requests WHERE id=?', (ticket['id'],)).fetchone()[0])
        for role, request in [('bad', {}), ('analyst', []), ('analyst', {'bad': float('nan')})]:
            with self.subTest(role=role, request=request), self.assertRaises(m.GateError):
                restarted.reserve(role, request)


if __name__ == '__main__':
    unittest.main()
