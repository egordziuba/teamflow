def test_role_check_is_shown_as_a_test_not_project_acceptance(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.role_checks import run_case
    class Backend:
        def call(self, role, request):
            return {'role': role, 'source_sha256': request['source_sha256'],
                    'contract_sha256': request['contract_sha256'],
                    'deliverable': 'Colors: #112233 #FFFFFF\nType: sans-serif\nLayout: single column',
                    'limitations': ['No rendering or tests performed.']}
    root = tmp_path / 'runs' / 'role-smoke-designer'
    result = run_case(root, 'designer', Backend())
    assert result['status'] == 'ROLE_CHECK_PASS'
    value = snapshot(tmp_path)['runs'][0]
    assert value['kind'] == 'role-check'
    assert value['status_label'] == 'Тест роли пройден'
    assert value['evidence']['checked'] is True
    assert 'коротк' in value['evidence']['summary'].lower()
