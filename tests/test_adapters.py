import importlib.util
import unittest


class AdapterTests(unittest.TestCase):
    def test_only_one_strict_json_object_is_accepted(self):
        self.assertIsNotNone(importlib.util.find_spec('teamflow.adapters'), 'Adapter missing')
        from teamflow.adapters import parse_object
        self.assertEqual(parse_object('{"a":true}'), {'a': True})
        for invalid in ['{"a":1,"a":2}', '{"x":NaN}', '[]', 'prefix {"a":1}', '{} {}']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_object(invalid)

    def test_real_hermes_preflight_has_no_tools_and_missing_auth_blocks_call(self):
        import tempfile
        from pathlib import Path
        import teamflow.adapters as ad
        self.assertTrue(hasattr(ad, 'HermesBackend'), 'Hermes subprocess adapter missing')
        from teamflow.runtime import prepare_runtime, find_install
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = find_install()
            prepare_runtime(root, repo, role_ids=['analyst'])
            backend = ad.HermesBackend(root, repo)
            report = backend.preflight('analyst')
            self.assertEqual(report['tool_count'], 0)
            self.assertFalse(report['auth_present'])
            with self.assertRaisesRegex(ValueError, 'auth_required'):
                backend.call('analyst', {'output_schema': {'ok': 'boolean'}})
            self.assertFalse((root / 'live-receipts').exists())

    def test_streaming_is_explicit_and_changes_fingerprint(self):
        from teamflow.adapters import HermesBackend
        from teamflow.runtime import PACKAGE_ROOT, find_install
        legacy = HermesBackend(PACKAGE_ROOT, find_install())
        streamed = HermesBackend(PACKAGE_ROOT, find_install(), streaming=True)
        self.assertNotIn('transport', legacy.fingerprint())
        self.assertEqual(streamed.fingerprint()['transport'], 'stream-consumer-v1')

    def test_outer_designer_budget_exceeds_provider_wait_and_override_is_honored(self):
        from teamflow.adapters import HermesBackend
        from teamflow.runtime import PACKAGE_ROOT, find_install
        backend = HermesBackend(PACKAGE_ROOT, find_install())
        self.assertEqual(backend.call_timeout('designer'), 360)
        self.assertEqual(backend.call_timeout('copywriter'), 180)
        explicit = HermesBackend(PACKAGE_ROOT, find_install(), timeout=30)
        self.assertEqual(explicit.call_timeout('designer'), 30)


if __name__ == '__main__':
    unittest.main()
