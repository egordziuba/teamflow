import importlib.util
import json
import sqlite3
from pathlib import Path


def seed(tmp_path, state='FAILED'):
    from teamflow.ledger import RequestLedger
    run = tmp_path / 'runs' / 'design-run'
    run.mkdir(parents=True)
    ledger = RequestLedger(run / 'execution.sqlite3')
    t = ledger.reserve('coordinator', {'stage': 'specialist-routing'})
    ledger.complete(t['id'], {'requests': []})
    t = ledger.reserve('designer', {'task': {'deliverable': 'PRIVATE_PROMPT_SENTINEL'}})
    if state == 'FAILED':
        ledger.fail(t['id'], 'ValueError')
    (run / 'routing.json').write_text(json.dumps({'requests': [
        {'role': 'designer', 'reason': 'visual', 'deliverable': 'spec'},
        {'role': 'copywriter', 'reason': 'copy', 'deliverable': 'text'}]}), encoding='utf-8')
    return run


def test_missing_source_stays_empty_and_readonly(tmp_path):
    assert importlib.util.find_spec('teamflow.observation'), 'Read-only projection missing'
    from teamflow.observation import snapshot
    before = list(tmp_path.iterdir())
    value = snapshot(tmp_path)
    assert value['read_only'] is True and value['runs'] == []
    assert list(tmp_path.iterdir()) == before


def test_failed_step_and_unstarted_specialist_are_distinct(tmp_path):
    assert importlib.util.find_spec('teamflow.observation'), 'Read-only projection missing'
    from teamflow.observation import snapshot
    run = seed(tmp_path)
    before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    value = snapshot(tmp_path)
    result = value['runs'][0]
    assert result['status'] == 'blocked'
    assert result['current_role'] == 'designer'
    assert [x['state'] for x in result['steps']] == ['completed', 'failed', 'planned']
    assert result['counts'] == {'completed': 1, 'pending': 0, 'failed': 1, 'planned': 1}
    assert result['roles'][0]['id'] == 'coordinator'
    assert 'PRIVATE_PROMPT_SENTINEL' not in json.dumps(value)
    assert {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()} == before


def test_accepted_requires_actual_artifact_and_verdict_readback(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.workflow import run_pilot
    from test_workflow import FakeBackend, SOURCE
    root = tmp_path / 'runs' / 'csv-run'
    result = run_pilot(root, SOURCE, FakeBackend(), inject_fault=True)
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'accepted'
    assert value['evidence']['checked'] is True
    assert len(value['steps']) == 7
    assert any('исправление' in step['state_label'] for step in value['steps'])
    (root / result['artifact']).write_text('{}', encoding='utf-8')
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'evidence_mismatch'
    assert value['evidence']['checked'] is False


def test_drafts_are_not_accepted_projects(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.specialists import run_specialists
    from test_specialists import RoutingDouble, BRIEF
    root = tmp_path / 'runs' / 'copy-run'
    run_specialists(root, BRIEF, RoutingDouble([{'role':'copywriter','reason':'Text needed','deliverable':'Draft'}]))
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'drafts'
    assert value['evidence']['checked'] is True
    assert value['steps'][-1]['phase'] == 'Согласование и передача результатов'
    assert len(value['artifacts']) == 2


def test_native_block_overrides_completed_responses(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.ledger import RequestLedger
    root = tmp_path / 'runs' / 'native-block'
    root.mkdir(parents=True)
    ledger = RequestLedger(root / 'execution.sqlite3')
    ticket = ledger.reserve('analyst', {})
    ledger.complete(ticket['id'], {})
    with sqlite3.connect(root / 'kanban.db') as db:
        db.execute('create table tasks (id text, assignee text, status text)')
        db.execute('insert into tasks values (?,?,?)', ('t1','analyst','blocked'))
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'blocked'
    assert 'Kanban' in value['warning']


def test_pending_is_not_claimed_as_process_liveness(tmp_path):
    from teamflow.observation import snapshot
    seed(tmp_path, state='PENDING')
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'pending'
    assert 'не проверка активности' in value['warning']
    assert value['current_role'] == 'designer'


def test_corrupt_payload_is_unknown_not_whole_snapshot_failure(tmp_path):
    from teamflow.observation import snapshot
    root = seed(tmp_path)
    with sqlite3.connect(root / 'execution.sqlite3') as db:
        db.execute('update requests set request_json=? where id=2', ('[]',))
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'unknown'
    assert value['evidence']['checked'] is False


def test_artifact_reference_cannot_escape_run(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.workflow import run_pilot
    from test_workflow import FakeBackend, SOURCE
    root = tmp_path / 'runs' / 'csv-run'
    run_pilot(root, SOURCE, FakeBackend())
    result = json.loads((root / 'result.json').read_text(encoding='utf-8'))
    result['artifact'] = '../../private.json'
    (tmp_path / 'private.json').write_text('{"secret":"DO_NOT_EXPOSE"}', encoding='utf-8')
    (root / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    value = snapshot(tmp_path)
    assert value['runs'][0]['status'] == 'evidence_mismatch'
    assert 'DO_NOT_EXPOSE' not in json.dumps(value)


def test_corrupt_routing_does_not_hide_other_runs(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.workflow import run_pilot
    from test_workflow import FakeBackend, SOURCE
    bad = seed(tmp_path)
    (bad / 'routing.json').write_text('{"requests":[null]}', encoding='utf-8')
    run_pilot(tmp_path / 'runs' / 'good-run', SOURCE, FakeBackend())
    states = {r['id']: r['status'] for r in snapshot(tmp_path)['runs']}
    assert states == {'design-run': 'unknown', 'good-run': 'accepted'}


def test_zero_specialists_is_verified_decision_not_evidence_error(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.specialists import run_specialists
    from test_specialists import RoutingDouble, BRIEF
    root = tmp_path / 'runs' / 'no-extra-roles'
    run_specialists(root, BRIEF, RoutingDouble([]))
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'incomplete'
    assert value['status_label'] == 'Дополнительные роли не потребовались'
    assert value['evidence']['checked'] is True
    assert value['current_stage'] == 'Выбор специалистов завершён'
    assert value['artifacts'] == []
    assert len(value['steps']) == 1


def test_draft_and_result_cannot_be_resigned_without_author_receipt(tmp_path):
    from teamflow.observation import snapshot
    from teamflow.specialists import run_specialists
    from teamflow.ledger import canonical_hash
    from test_specialists import RoutingDouble, BRIEF
    root = tmp_path / 'runs' / 'copy-run'
    run_specialists(root, BRIEF, RoutingDouble([{'role':'copywriter','reason':'Text needed','deliverable':'Draft'}]))
    result_path = root / 'result.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    report = result['reports'][0]
    artifact_path = root / report['artifact']
    candidate = json.loads(artifact_path.read_text(encoding='utf-8'))
    candidate['deliverable'] = 'MODIFIED_AFTER_THE_REAL_RESPONSE'
    artifact_path.write_text(json.dumps(candidate), encoding='utf-8')
    report['sha256'] = canonical_hash(candidate)
    result_path.write_text(json.dumps(result), encoding='utf-8')
    value = snapshot(tmp_path)['runs'][0]
    assert value['status'] == 'evidence_mismatch'
    assert value['evidence']['checked'] is False
