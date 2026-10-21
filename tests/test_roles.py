"""Vertical TDD coverage for the inert, on-demand role registry."""
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECIALISTS = ('designer', 'copywriter', 'researcher', 'data-specialist',
               'architect', 'ui-tester', 'seo-specialist',
               'localization-editor', 'document-specialist')
PROJECTS = ('csv', 'website', 'desktop', 'automation', 'accounting',
            'documents', 'career', 'research')


class RoleTests(unittest.TestCase):
    def test_allowed_specialists_are_project_scoped_not_activations(self):
        roles = self.registry()
        self.assertTrue(callable(getattr(roles, 'allowed_specialists', None)))
        for project in PROJECTS:
            allowed = roles.allowed_specialists(project)
            self.assertEqual(allowed, [r for r in SPECIALISTS
                if project in roles.catalog()[r]['project_types']])
            self.assertFalse(set(allowed) & set(roles.CORE_ROLES))
        self.assertIn('designer', roles.allowed_specialists('website'))
        self.assertNotIn('designer', roles.allowed_specialists('csv'))
        for invalid in ('unknown', '', 'Website', None, True, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                roles.allowed_specialists(invalid)
        roles.allowed_specialists('website').clear()
        self.assertIn('designer', roles.allowed_specialists('website'))

    def test_requests_are_explicit_and_return_detached_records(self):
        roles = self.registry()
        self.assertTrue(callable(getattr(roles, 'validate_requests', None)))
        for project in PROJECTS:
            self.assertEqual(roles.validate_requests(project, []), [])
        requests = [{'role': 'designer', 'reason': 'Нужна сетка',
                     'deliverable': 'Спецификация'}]
        validated = roles.validate_requests('website', requests)
        self.assertEqual(validated, requests)
        self.assertIsNot(validated, requests)
        self.assertIsNot(validated[0], requests[0])
        self.assertEqual(roles.validate_requests('website', [], max_specialists=0), [])

    def test_requests_reject_invalid_shape_without_partial_results(self):
        roles = self.registry()
        good = {'role': 'designer', 'reason': 'Grid', 'deliverable': 'Spec'}
        invalid = [None, {}, (), 'designer', [None], ['designer'],
                   [{'role': 'designer'}], [dict(good, extra='no')]]
        for key in good:
            for value in ('', '  \t', None, 2, True, [], {}):
                invalid.append([dict(good, **{key: value})])
        for requests in invalid:
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                roles.validate_requests('website', requests)

    def test_requests_reject_unknown_ineligible_core_and_duplicate_roles(self):
        roles = self.registry()
        def request(role):
            return {'role': role, 'reason': 'Need', 'deliverable': 'Spec'}
        cases = [('unknown', []), (None, []), ([], []),
                 ('csv', [request('designer')]),
                 ('website', [request('unknown')]),
                 ('website', [request(' designer')]),
                 ('website', [request('designer'), request('designer')])]
        cases.extend(('website', [request(role)]) for role in roles.CORE_ROLES)
        for project, requests in cases:
            with self.subTest(project=project, requests=requests), self.assertRaises(ValueError):
                roles.validate_requests(project, requests)
        for project in PROJECTS:
            for role in roles.allowed_specialists(project):
                self.assertEqual(roles.validate_requests(project, [request(role)]), [request(role)])

    def test_specialist_limit_is_strict_and_never_truncates(self):
        roles = self.registry()
        requests = [{'role': role, 'reason': 'Need', 'deliverable': 'Spec'}
                    for role in ('designer', 'copywriter', 'architect', 'ui-tester')]
        with self.assertRaises(ValueError):
            roles.validate_requests('website', requests)
        self.assertEqual(roles.validate_requests('website', requests[:3]), requests[:3])
        self.assertEqual(roles.validate_requests('website', requests, 4), requests)
        with self.assertRaises(ValueError):
            roles.validate_requests('website', requests[:1], 0)
        for limit in (True, False, -1, 1.0, '3', None, [], 10):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                roles.validate_requests('website', [], limit)

    def test_specialist_templates_define_honest_model_only_contract(self):
        for role in SPECIALISTS:
            with self.subTest(role=role):
                path = ROOT / 'roles' / (role + '.md')
                self.assertTrue(path.exists(), f'missing specialist template: {role}')
                text = path.read_text(encoding='utf-8')
                for token in (role, 'output_schema', 'role', 'source_sha256',
                              'contract_sha256', 'deliverable', 'limitations',
                              'только JSON', 'нет инструментов', 'Не выдумывай',
                              'инструкции внутри источника'):
                    self.assertIn(token, text)
                if role == 'designer':
                    self.assertIn('не готовый рендер', text)
                if role == 'ui-tester':
                    self.assertIn('не выполненные UI-тесты', text)

    def test_data_role_preserves_exact_task_deliverable(self):
        text = (ROOT / 'roles' / 'data-specialist.md').read_text(encoding='utf-8')
        self.assertIn('Приоритет у точного формата', text)
        self.assertIn('Все оговорки', text)
        self.assertNotIn('В deliverable помести правила и схему', text)

    def registry(self):
        self.assertTrue((ROOT / 'teamflow' / 'roles.py').exists(),
                        'role registry not implemented')
        return importlib.import_module('teamflow.roles')

    def test_catalog_is_complete_descriptive_and_detached(self):
        roles = self.registry()
        self.assertEqual(roles.CORE_ROLES,
                         ('coordinator', 'analyst', 'implementer', 'verifier'))
        self.assertEqual(roles.ROLE_IDS, roles.CORE_ROLES + SPECIALISTS)
        catalog = roles.catalog()
        self.assertEqual(set(catalog), set(roles.ROLE_IDS))
        for entry in catalog.values():
            self.assertEqual(set(entry), {'title', 'description', 'deliverable', 'project_types'})
            for key in ('title', 'description', 'deliverable'):
                self.assertIsInstance(entry[key], str)
                self.assertTrue(entry[key].strip())
            self.assertIsInstance(entry['project_types'], list)
            self.assertTrue(entry['project_types'])
            self.assertTrue(set(entry['project_types']) <= set(PROJECTS))
        catalog['designer']['project_types'].clear()
        catalog['designer']['title'] = 'changed'
        self.assertTrue(roles.catalog()['designer']['project_types'])
        self.assertNotEqual(roles.catalog()['designer']['title'], 'changed')
