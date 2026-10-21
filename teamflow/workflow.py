"""Bounded pilot orchestration. Models produce data only; the supervisor owns writes."""
import hashlib
import json
from pathlib import Path

from .ledger import RequestLedger, GateError, canonical_hash, validate_verdict
from .pilot import CRITERIA, check_candidate


CONTRACT = {
    'id': 'eur-csv-reconciliation-v1',
    'goal': 'Reconcile every source transaction without silently dropping rows; output exact EUR total.',
    'headers': ['id', 'amount', 'currency', 'status'],
    'rules': [
        'CSV delimiter is determined from source. Monetary source notation has decimal comma.',
        'Row numbering includes header: first transaction is row 2; preserve source row order.',
        'Exclude malformed row as malformed_row; then blank id as missing_id; then status != settled as not_settled;',
        'then currency != EUR as unsupported_currency; then amount not matching -?[0-9]{1,12},[0-9]{2} as invalid_amount;',
        'then repeated id among previously ACCEPTED rows as duplicate_id. First applicable reason wins.',
        'Accepted negative amounts are refunds, not errors. Use exact decimal arithmetic.',
        'Output exactly {accepted:[{row:int,id:str,amount:str}],excluded:[{row:int,reason:str}],total_eur:str}.',
        'Normalized amounts and total use decimal point and exactly two decimal places.'
    ],
    'criteria': CRITERIA,
    'boundaries': ['No tools', 'No code execution', 'No external writes', 'No acceptance weakening']
}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def backend_fingerprint(backend):
    if hasattr(backend, 'fingerprint'):
        return backend.fingerprint()
    return {'kind': 'TEST_DOUBLE', 'class': type(backend).__name__}


def write_snapshot(path: Path, value):
    text = json_text(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding='utf-8') != text:
            raise GateError('Snapshot conflict: ' + path.name)
    else:
        with path.open('x', encoding='utf-8') as f:
            f.write(text)


@__import__('contextlib').contextmanager
def workspace_lock(root: Path):
    import os
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.controller.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise GateError('Controller already running for this workspace') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_pilot(root: Path, source: str, backend, **options):
    with workspace_lock(root):
        return _run_pilot(root, source, backend, **options)


def _run_pilot(root: Path, source: str, backend, *, inject_fault=False, max_attempts=3, max_calls=12, board=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
    contract_hash = canonical_hash(CONTRACT)
    manifest = {'source_sha256': source_hash, 'contract_sha256': contract_hash,
                'inject_fault': inject_fault, 'max_attempts': max_attempts, 'max_calls': max_calls,
                'backend': backend_fingerprint(backend)}
    write_snapshot(root / 'manifest.json', manifest)
    write_snapshot(root / 'contract.json', CONTRACT)
    ledger = RequestLedger(root / 'execution.sqlite3', max_calls=max_calls)

    def ask(role, payload):
        request = {'source': source, 'source_sha256': source_hash,
                   'contract': CONTRACT, 'contract_sha256': contract_hash, **payload}
        ticket = ledger.reserve(role, request)
        if ticket['state'] == 'COMPLETED':
            if board is not None:
                card = board.start(ticket['id'], role, request)
                board.finish(card, ticket['response'])
            return ticket['response']
        card = None
        try:
            if board is not None:
                card = board.start(ticket['id'], role, request)
            response = backend.call(role, request)
            ledger.complete(ticket['id'], response)
        except Exception as exc:
            ledger.fail(ticket['id'], type(exc).__name__)
            if board is not None and card is not None:
                board.fail(card, type(exc).__name__)
            raise
        if board is not None and card is not None:
            board.finish(card, response)
        return response

    old_context = {'revision': 1, 'delimiter': ',', 'decimal_separator': '.',
                   'status': 'UNVERIFIED_TEST_HYPOTHESIS'}
    write_snapshot(root / 'revisions' / 'context-1.json', old_context)
    analysis = ask('analyst', {'previous_context': old_context,
                             'output_schema': {'source_sha256': 'copy exact input', 'delimiter': 'character',
                                               'decimal_separator': 'character', 'findings': ['evidence']}})
    if (set(analysis) != {'source_sha256', 'delimiter', 'decimal_separator', 'findings'}
            or analysis['source_sha256'] != source_hash or analysis['delimiter'] != ';'
            or analysis['decimal_separator'] != ',' or not analysis['findings']):
        raise GateError('Analyst context not supported by the source')
    context = {'revision': 2, **analysis}
    write_snapshot(root / 'revisions' / 'context-2.json', context)
    attempts = []
    defects = []
    for attempt in range(1, max_attempts + 1):
        plan = ask('coordinator', {'context': context, 'attempt': attempt, 'defects': defects,
                  'output_schema': {'source_sha256': 'copy exact input', 'contract_sha256': 'copy exact input',
                                    'instruction': 'concrete implementation instruction without changing the contract'}})
        if (set(plan) != {'source_sha256', 'contract_sha256', 'instruction'}
                or plan['source_sha256'] != source_hash or plan['contract_sha256'] != contract_hash
                or type(plan['instruction']) is not str or not plan['instruction'].strip()):
            raise GateError('Coordinator attempted an invalid contract/source revision')
        write_snapshot(root / 'revisions' / f'task-{attempt}.json', plan)
        raw = ask('implementer', {'context': context, 'attempt': attempt, 'plan': plan, 'defects': defects,
                                 'output_schema': 'Return ONLY the exact result object required by contract.rules'})
        write_snapshot(root / 'artifacts' / f'raw-{attempt}.json', raw)
        candidate = dict(raw)
        if inject_fault and attempt == 1:
            candidate['total_eur'] = '0.00'
            write_snapshot(root / 'evidence' / 'fault-injection.json', {
                'kind': 'CONTROLLED_TEST_INJECTION', 'field': 'total_eur',
                'raw_sha256': canonical_hash(raw), 'injected_value': '0.00',
                'note': 'Harness altered candidate, NOT an alleged model mistake.'})
        artifact_hash = canonical_hash(candidate)
        write_snapshot(root / 'artifacts' / f'candidate-{attempt}.json', candidate)
        checks = check_candidate(source, candidate)
        verdict = ask('verifier', {'attempt': attempt, 'candidate': candidate,
                     'artifact_sha256': artifact_hash, 'deterministic_checks': checks,
                     'output_schema': {'verdict': 'PASS|FIX_REQUIRED|CONTEXT_INVALID|NEEDS_DECISION',
                        'artifact_sha256': 'copy exact input',
                        'checks': [{'id': 'one entry per contract.criteria', 'passed': 'JSON boolean',
                                    'evidence': 'nonempty evidence from source and artifact'}],
                        'issues': ['concrete defects; empty only if none']}})
        status = validate_verdict(verdict, artifact_hash, CRITERIA)
        accepted = status == 'PASS' and all(c['passed'] for c in checks)
        evidence = {'attempt': attempt, 'artifact_sha256': artifact_hash,
                    'deterministic_checks': checks, 'review': verdict, 'accepted': accepted}
        write_snapshot(root / 'evidence' / f'attempt-{attempt}.json', evidence)
        attempts.append(evidence)
        if accepted:
            result = {'status': 'ACCEPTED', 'mode': 'live' if getattr(backend, 'live', False) else 'TEST_DOUBLE',
                      'context_revision': 2, 'source_sha256': source_hash, 'contract_sha256': contract_hash,
                      'artifact_sha256': artifact_hash, 'artifact': f'artifacts/candidate-{attempt}.json',
                      'attempts': attempts, 'model_calls': len(ledger.rows()), 'fault_injected': inject_fault}
            write_snapshot(root / 'result.json', result)
            return result
        if status in {'CONTEXT_INVALID', 'NEEDS_DECISION'}:
            raise GateError('Reviewer requires context/human decision: ' + status)
        if len(attempts) > 1 and attempts[-2]['artifact_sha256'] == artifact_hash:
            raise GateError('No progress: identical rejected artifact repeated')
        defects = verdict['issues'] + [c['id'] + ': ' + c['evidence'] for c in checks if not c['passed']]
    raise GateError('Attempt budget exhausted; no accepted result')
