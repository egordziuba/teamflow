import importlib.util
import unittest


class PilotTests(unittest.TestCase):
    def test_pilot_has_a_real_deterministic_validator(self):
        self.assertIsNotNone(importlib.util.find_spec('teamflow.pilot'),
                             'Missing deterministic CSV acceptance validator')
        from teamflow.pilot import expected_result
        result = expected_result('id;amount;currency;status\nA;12,50;EUR;settled\nB;-2,00;EUR;settled\n')
        self.assertEqual(result, {'accepted': [{'row': 2, 'id': 'A', 'amount': '12.50'},
                                             {'row': 3, 'id': 'B', 'amount': '-2.00'}],
                                  'excluded': [], 'total_eur': '10.50'})

    def test_rejections_and_duplicate_precedence(self):
        from teamflow.pilot import expected_result
        source = ('id;amount;currency;status\nA;12,50;EUR;settled\nA;12,50;EUR;settled\n'
                  'B;wrong;EUR;settled\nC;2,00;USD;settled\nD;2,00;EUR;pending\n'
                  'E;NaN;EUR;settled\nF;0,001;EUR;settled\n')
        result = expected_result(source)
        self.assertEqual(result['total_eur'], '12.50')
        self.assertEqual(result['excluded'], [
            {'row': 3, 'reason': 'duplicate_id'}, {'row': 4, 'reason': 'invalid_amount'},
            {'row': 5, 'reason': 'unsupported_currency'}, {'row': 6, 'reason': 'not_settled'},
            {'row': 7, 'reason': 'invalid_amount'}, {'row': 8, 'reason': 'invalid_amount'}])

    def test_acceptance_requires_exact_typed_coverage_and_total(self):
        import teamflow.pilot as pilot
        self.assertTrue(hasattr(pilot, 'check_candidate'), 'Acceptance gate missing')
        source = 'id;amount;currency;status\nA;12,50;EUR;settled\n'
        correct = pilot.expected_result(source)
        self.assertTrue(all(c['passed'] for c in pilot.check_candidate(source, correct)))
        bad = dict(correct, total_eur='0.00')
        self.assertFalse(all(c['passed'] for c in pilot.check_candidate(source, bad)))
        bad = dict(correct, accepted=[{'row': True, 'id': 'A', 'amount': '12.50'}])
        self.assertFalse(all(c['passed'] for c in pilot.check_candidate(source, bad)))
        self.assertFalse(all(c['passed'] for c in pilot.check_candidate(source, {'accepted': []})))


if __name__ == '__main__':
    unittest.main()
