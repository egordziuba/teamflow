import importlib.util
import tempfile
import unittest
from pathlib import Path

import pytest


class RuntimeTests(unittest.TestCase):
    def test_clean_environment_excludes_inherited_authority(self):
        self.assertIsNotNone(importlib.util.find_spec('teamflow.runtime'), 'Runtime isolation missing')
        from teamflow.runtime import clean_env
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = clean_env(root, {'PATH': 'tools', 'SYSTEMROOT': 'C:/Windows',
                                  'HERMES_KANBAN_TASK': 'foreign', 'HERMES_YOLO_MODE': '1',
                                  'OPENAI_API_KEY': 'dummy', 'PYTHONPATH': 'foreign',
                                  'CODEX_HOME': 'foreign'})
            self.assertEqual(env['HERMES_HOME'], str(root.resolve()))
            self.assertEqual(env['SYSTEMROOT'], 'C:/Windows')
            self.assertEqual(env['CODEX_HOME'], str(root.resolve() / 'isolated-codex'))
            for key in ['HERMES_KANBAN_TASK', 'HERMES_YOLO_MODE', 'OPENAI_API_KEY', 'PYTHONPATH']:
                self.assertNotIn(key, env)

    @pytest.mark.usefixtures('hermes_repo')
    def test_prepare_real_isolated_profile_idempotent_and_closed(self):
        import teamflow.runtime as rt
        self.assertTrue(hasattr(rt, 'prepare_runtime'), 'Profile bootstrap missing')
        repo = self.hermes_repo
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = rt.prepare_runtime(root, repo, role_ids=['analyst'])
            self.assertEqual(home, root / '.runtime' / 'hermes')
            report = rt.inspect_runtime(root, ['analyst'])
            self.assertTrue(report['profiles_ok'])
            self.assertFalse(report['auth_present'])
            self.assertFalse((home / 'profiles' / 'analyst' / 'auth.json').exists())
            self.assertEqual(rt.prepare_runtime(root, repo, role_ids=['analyst']), home)
            (home / 'profiles' / 'analyst' / 'config.yaml').write_text('{}', encoding='utf-8')
            self.assertFalse(rt.inspect_runtime(root, ['analyst'])['profiles_ok'])
            with self.assertRaises(ValueError):
                rt.prepare_runtime(root, repo, role_ids=['analyst'])

    @pytest.mark.usefixtures('hermes_repo')
    def test_root_configuration_and_plugins_cannot_bypass_profile_preflight(self):
        from teamflow.runtime import prepare_runtime, inspect_runtime
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = prepare_runtime(root, self.hermes_repo, role_ids=['analyst'])
            (home / 'plugins' / 'unexpected').mkdir(parents=True)
            self.assertFalse(inspect_runtime(root, ['analyst'])['profiles_ok'])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = prepare_runtime(root, self.hermes_repo, role_ids=['analyst'])
            (home / 'config.yaml').write_text('{}', encoding='utf-8')
            self.assertFalse(inspect_runtime(root, ['analyst'])['profiles_ok'])

    def test_designer_has_a_finite_larger_budget_only_for_that_profile(self):
        from teamflow.runtime import secure_config
        designer = secure_config(role='designer')
        normal = secure_config(role='copywriter')
        self.assertEqual(designer['providers']['openai-codex']['stale_timeout_seconds'], 300)
        self.assertEqual(designer['providers']['openai-codex']['request_timeout_seconds'], 300)
        self.assertNotIn('providers', normal)
        self.assertEqual(designer['platform_toolsets']['cli'], [])
        self.assertEqual(designer['approvals']['mode'], 'manual')


if __name__ == '__main__':
    unittest.main()
