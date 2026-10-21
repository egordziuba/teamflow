import json
import pytest

from teamflow import role_checks as rc
from teamflow.roles import ROLE_IDS
from teamflow.ledger import GateError, RequestLedger, canonical_hash


def answer(role, req):
    if role not in ('analyst', 'coordinator', 'implementer', 'verifier'):
        return dict(role=role, source_sha256=req['source_sha256'], contract_sha256=req['contract_sha256'], deliverable=rc.OPTIONAL[role][2], limitations=['Draft only; not externally verified.'])
    if role == 'analyst':
        return dict(source_sha256=req['source_sha256'], delimiter=';', decimal_separator=',', findings=['Source uses semicolons and decimal commas.'])
    if role == 'coordinator':
        return dict(source_sha256=req['source_sha256'], contract_sha256=req['contract_sha256'], instruction='Deduplicate by accepted id and sum exact decimals under the contract.')
    if role == 'implementer':
        return {'accepted': [{'row': 2, 'id': 'a', 'amount': '0.10'}, {'row': 4, 'id': 'b', 'amount': '0.20'}], 'excluded': [{'row': 3, 'reason': 'duplicate_id'}], 'total_eur': '0.30'}
    return dict(verdict='FIX_REQUIRED', artifact_sha256=req['artifact_sha256'], checks=req['deterministic_checks'], issues=['Total 9.99 is wrong; expected 0.30.'])


class Double:
    live = False
    calls = 0
    def call(self, role, req):
        self.calls += 1
        return answer(role, req)


@pytest.mark.parametrize('role', ROLE_IDS)
def test_all_roles_run_and_resume(tmp_path, role):
    backend = Double()
    result = rc.run_case(tmp_path, role, backend)
    assert result['status'] == 'ROLE_CHECK_PASS'
    assert result['mode'] == 'TEST_DOUBLE'
    assert result['model_calls'] == 1
    assert json.loads((tmp_path / 'artifacts/checks.json').read_text()) == result['checks']
    assert rc.run_case(tmp_path, role, backend) == result
    assert backend.calls == 1


def test_transport_never_retried_and_safe(tmp_path):
    class Broken(Double):
        def call(self, role, req):
            self.calls += 1
            raise RuntimeError('secret-provider-output')
    backend = Broken()
    assert rc.run_case(tmp_path, 'designer', backend)['status'] == 'BLOCKED'
    assert rc.run_case(tmp_path, 'designer', backend)['status'] == 'BLOCKED'
    assert backend.calls == 1
    assert 'secret-provider-output' not in (tmp_path / 'result.json').read_text()



@pytest.mark.parametrize('role', ROLE_IDS)
def test_bad_schema_and_stale_response(role):
    req = rc.case_request(role)
    good = answer(role, req)
    for bad in (None, [], {}, dict(good, extra=True)):
        assert not all(c['passed'] for c in rc.validate_role_response(role, req, bad))
    for key in ('source_sha256', 'contract_sha256', 'artifact_sha256'):
        if key in good:
            assert not all(c['passed'] for c in rc.validate_role_response(role, req, dict(good, **{key: 'stale'})))
    req['contract_sha256'] = 'bad'
    assert not all(c['passed'] for c in rc.validate_role_response(role, req, good))


@pytest.mark.parametrize('value', ['', 'x' * 1801, 'Colors: #112233 #FFFFFF\nType: sans-serif\nLayout: single column' + ' ' * 1801, 3, None])
def test_deliverable_bounds(value):
    req = rc.case_request('designer')
    out = answer('designer', req)
    out['deliverable'] = value
    assert not all(c['passed'] for c in rc.validate_role_response('designer', req, out))


def test_pending_blocks_without_call(tmp_path):
    RequestLedger(tmp_path / 'execution.sqlite3', 1).reserve('designer', rc.case_request('designer'))
    backend = Double()
    assert rc.run_case(tmp_path, 'designer', backend)['error_code'] == 'ambiguous_request'
    assert backend.calls == 0


def test_fingerprint_changes_refused(tmp_path):
    backend = Double()
    rc.run_case(tmp_path, 'designer', backend)
    backend.fingerprint = lambda: {'kind': 'changed'}
    with pytest.raises(GateError):
        rc.run_case(tmp_path, 'designer', backend)
    assert backend.calls == 1


def test_board_reconciliation_no_repeat(tmp_path):
    class Board:
        broken = True
        def start(self, ticket, role, req):
            assert RequestLedger(tmp_path / 'execution.sqlite3', 1).status(ticket)['state'] in ('PENDING', 'COMPLETED')
            return ticket
        def finish(self, ticket, response):
            assert (tmp_path / 'receipt.json').exists()
            if self.broken:
                raise RuntimeError('board-secret')
        def fail(self, *args):
            pass
    backend, board = Double(), Board()
    assert rc.run_case(tmp_path, 'designer', backend, board)['status'] == 'BLOCKED'
    board.broken = False
    assert rc.run_case(tmp_path, 'designer', backend, board)['status'] == 'ROLE_CHECK_PASS'
    assert backend.calls == 1
    assert len(list((tmp_path / 'history/result').glob('*.json'))) == 2


def test_cli_preflight_before_writes(tmp_path, monkeypatch):
    from teamflow import runtime
    monkeypatch.setattr(runtime, 'PACKAGE_ROOT', tmp_path)
    monkeypatch.setattr(runtime, 'inspect_runtime', lambda *a, **k: {'auth_present': False, 'profiles_ok': False})
    assert rc.main(['--run', 'check']) == 2
    assert not list(tmp_path.iterdir())


def test_cli_visits_all_and_resumes(tmp_path, monkeypatch):
    from teamflow import runtime, adapters, kanban
    monkeypatch.setattr(runtime, 'PACKAGE_ROOT', tmp_path)
    monkeypatch.setattr(runtime, 'inspect_runtime', lambda *a, **k: {'auth_present': True, 'profiles_ok': True})
    monkeypatch.setattr(runtime, 'find_install', lambda: tmp_path)
    calls = []
    class Backend(Double):
        def __init__(self, *a, **k):
            pass
        def call(self, role, req):
            calls.append(role)
            if role == 'designer':
                raise ValueError('model_timeout_outcome_unknown')
            return answer(role, req)
    class Board:
        def __init__(self, *a): pass
        def start(self, *a): return {}
        def finish(self, *a): pass
        def fail(self, *a): pass
    monkeypatch.setattr(adapters, 'HermesBackend', Backend)
    monkeypatch.setattr(kanban, 'NativeBoard', Board)
    assert rc.main(['--run', 'all']) == 2
    assert calls == list(ROLE_IDS)
    report = json.loads((tmp_path / 'reports/all.json').read_text())
    assert len(report['results']) == 13
    assert rc.main(['--run', 'all']) == 2
    assert calls == list(ROLE_IDS)


def test_non_json_response_fails_closed():
    req = rc.case_request('implementer')
    out = answer('implementer', req)
    out['accepted'] = [float('nan')]
    assert not all(c['passed'] for c in rc.validate_role_response('implementer', req, out))


@pytest.mark.parametrize('role, field, value', [
    ('data-specialist', 'deliverable', 'kept=a,b; duplicate=a; total=0.31'),
    ('localization-editor', 'deliverable', 'Save\nCancel'),
    ('document-specialist', 'deliverable', '- [ ] name'),
    ('designer', 'limitations', [True]),
    ('implementer', 'total_eur', '9.99'),
    ('ui-tester', 'deliverable', 'PLANNED: empty tested and passed\nPLANNED: valid saved\nPLANNED: failed error'),
])
def test_wrong_case_content(role, field, value):
    req = rc.case_request(role)
    out = answer(role, req)
    out[field] = value
    assert not all(c['passed'] for c in rc.validate_role_response(role, req, out))


def test_transport_has_check_artifact(tmp_path):
    class Broken(Double):
        def call(self, *args):
            raise ValueError('model_timeout_outcome_unknown')
    result = rc.run_case(tmp_path, 'designer', Broken())
    assert json.loads((tmp_path / 'artifacts/checks.json').read_text()) == result['checks']


def test_cases_have_immutable_bound_contracts():
    from teamflow import role_checks as rc
    for role in ROLE_IDS:
        req = rc.case_request(role)
        assert req['role_under_test'] == role
        assert req['stage'] == 'role-check'
        assert req['source_sha256'] == canonical_hash(req['sources'])
        assert req['contract_sha256'] == canonical_hash(req['contract'])
        assert req['output_schema']
        assert rc.validate_role_response(role, req, {})
        assert not all(c['passed'] for c in rc.validate_role_response(role, req, {}))
