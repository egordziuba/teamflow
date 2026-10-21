"""Compact contract/transport smoke checks, NOT broad role competence qualification."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import time

from .ledger import GateError, RequestLedger, AmbiguousRequest, canonical_hash, validate_verdict
from .roles import ROLE_IDS, CORE_ROLES
from .workflow import CONTRACT, backend_fingerprint, workspace_lock, write_snapshot
from .pilot import check_candidate, CRITERIA

SCOPE = 'Compact contract/transport check; NOT broad qualification of role competence.'
CSV = 'id;amount;currency;status\na;0,10;EUR;settled\na;0,10;EUR;settled\nb;0,20;EUR;settled\n'
OPTIONAL = {
    'designer': ('Fictional notes app, quiet readable interface.', 'Exactly two #RRGGBB colors, a Type: recommendation and a Layout: recommendation; use these English labels; text only, no rendering.', 'Colors: #112233 #FFFFFF\nType: sans-serif\nLayout: single column'),
    'copywriter': ('Fictional Luma library opens Tuesday at 10:00. Entry is free.', 'One short factual sentence in English including Luma, Tuesday, 10:00 and free. No extra facts.', 'Luma opens Tuesday at 10:00; entry is free.'),
    'researcher': ('S1 says fictional launch is May 3. S2 says fictional launch is May 5.', 'Compare S1 and S2 in English, quote both dates, label the conflict unresolved. No web access or verification claims.', 'S1: May 3; S2: May 5. Conflict unresolved.'),
    'data-specialist': ('id,amount\na,0.10\na,0.10\nb,0.20', 'Deduplicate by id keeping first, sum with decimal arithmetic. Exact deliverable format: kept=a,b; duplicate=a; total=0.30', 'kept=a,b; duplicate=a; total=0.30'),
    'architect': ('Fictional local notes app; no network needed.', 'Exactly three lines, with component names UI, Store, Validator; each line describes its responsibility. Proposal only.', 'UI: display notes\nStore: persist notes locally\nValidator: reject empty notes'),
    'ui-tester': ('Fictional Save button: empty note rejected; valid note saved; failed save shows error.', 'Exactly three lines starting PLANNED: covering empty, valid, and failed save, with expected results. Not performed tests.', 'PLANNED: empty note rejected\nPLANNED: valid note saved\nPLANNED: failed save shows error'),
    'seo-specialist': ('Fictional Luma library. Free entry Tuesday.', 'Exactly two English lines: Title: (<=60 characters value) and Description: (<=160 characters value). Include Luma and only source facts. Draft only; no ranking claims.', 'Title: Luma library\nDescription: Free entry Tuesday at Luma library.'),
    'localization-editor': ('Сохранить\nОтмена', 'Translate fixed UI labels Russian to German. Exact two-line deliverable: Speichern then Abbrechen.', 'Speichern\nAbbrechen'),
    'document-specialist': ('Fictional application: name=Alex; date=; signature=. Required fields: name, date, signature.', 'List only missing fields as exactly two checklist lines: - [ ] date and - [ ] signature. No invented data.', '- [ ] date\n- [ ] signature'),
}


def case_request(role):
    if role not in ROLE_IDS:
        raise GateError('Invalid role')
    if role in CORE_ROLES:
        sources = [{'id': 'CSV', 'text': CSV}]
        contract = json.loads(json.dumps(CONTRACT))
        schema = {
            'analyst': {'source_sha256': 'copy exact input', 'delimiter': ';', 'decimal_separator': ',', 'findings': ['nonempty source evidence']},
            'coordinator': {'source_sha256': 'copy exact input', 'contract_sha256': 'copy exact input', 'instruction': 'concise implementation instruction preserving contract'},
            'implementer': {'accepted': [{'row': 'integer', 'id': 'string', 'amount': 'two-decimal string'}], 'excluded': [{'row': 'integer', 'reason': 'string'}], 'total_eur': 'two-decimal string'},
            'verifier': {'verdict': 'FIX_REQUIRED', 'artifact_sha256': 'copy exact input', 'checks': [{'id': 'each contract criterion', 'passed': 'boolean', 'evidence': 'source-based evidence'}], 'issues': ['concrete defects']},
        }[role]
        extra = {'source': CSV, 'instruction': 'Apply the provided CSV contract; concise JSON only.'}
        if role == 'verifier':
            candidate = {'accepted': [{'row': 2, 'id': 'a', 'amount': '0.10'}, {'row': 4, 'id': 'b', 'amount': '0.20'}], 'excluded': [{'row': 3, 'reason': 'duplicate_id'}], 'total_eur': '9.99'}
            extra.update(candidate=candidate, artifact_sha256=canonical_hash(candidate), deterministic_checks=check_candidate(CSV, candidate))
    else:
        source, task, _ = OPTIONAL[role]
        sources = ([{'id': 'S1', 'text': 'Fictional launch is May 3.'}, {'id': 'S2', 'text': 'Fictional launch is May 5.'}]
                   if role == 'researcher' else [{'id': 'S1', 'text': source}])
        contract = {'id': 'role-check-v1-' + role, 'task': task, 'boundaries': ['No tools', 'No external effects', 'No invented facts', 'Draft only'], 'deliverable_max_chars': 1800}
        schema = {'role': role, 'source_sha256': 'copy exact input', 'contract_sha256': 'copy exact input', 'deliverable': 'concise text <=1800 characters', 'limitations': ['unverified scope; nonempty strings, <=300 characters each']}
        extra = {'task': task, 'instruction': 'Return exactly output_schema fields. Keep concise. State limitations honestly; no tools.'}
    return {'stage': 'role-check', 'role_under_test': role, 'sources': sources, 'source_sha256': canonical_hash(sources), 'contract': contract, 'contract_sha256': canonical_hash(contract), 'output_schema': schema, **extra}


def validate_role_response(role, request, response):
    checks = []
    def add(key, passed):
        checks.append({'id': key, 'passed': bool(passed), 'evidence': ('Satisfied: ' if passed else 'Not satisfied: ') + key})
    try:
        expected = case_request(role)
        add('immutable_request', request == expected)
        add('response_schema', type(response) is dict and set(response) == set(expected['output_schema']))
    except (ValueError, TypeError):
        add('valid_role_request', False)
        return checks
    if not all(c['passed'] for c in checks):
        return checks
    try:
        canonical_hash(response)  # Reject non-finite/non-JSON values before role validators.
        add('response_bound', len(json.dumps(response, ensure_ascii=True)) <= 16000)
    except (ValueError, TypeError, RecursionError):
        add('strict_json', False)
        return checks
    if not checks[-1]['passed']:
        return checks
    for field in ('source_sha256', 'contract_sha256'):
        if field in response:
            add(field, response[field] == expected[field])
    if role not in CORE_ROLES:
        text, limits = response['deliverable'], response['limitations']
        add('role', response['role'] == role)
        add('deliverable_bound', type(text) is str and bool(text.strip()) and len(text) <= 1800)
        add('limitations', type(limits) is list and len(limits) <= 8 and all(type(x) is str and 0 < len(x.strip()) <= 300 for x in limits))
        if type(text) is str:
            lines = text.strip().splitlines()
            low = text.lower()
            predicates = {
                'designer': lambda: len(re.findall(r'#[0-9a-fA-F]{6}\b', text)) == 2 and 'type:' in low and 'layout:' in low,
                'copywriter': lambda: all(x in low for x in ('luma', 'tuesday', '10:00', 'free')),
                'researcher': lambda: all(x in low for x in ('s1', 's2', 'may 3', 'may 5', 'unresolved')),
                'data-specialist': lambda: text.strip() == 'kept=a,b; duplicate=a; total=' + format(Decimal('0.10') + Decimal('0.20'), '.2f'),
                'architect': lambda: len(lines) == 3 and all(line.startswith(name + ':') and line[len(name)+1:].strip() for line, name in zip(lines, ('UI', 'Store', 'Validator'))),
                'ui-tester': lambda: len(lines) == 3 and all(line.startswith('PLANNED:') for line in lines) and all(x in low for x in ('empty', 'valid', 'failed')) and not re.search(r'\b(tested|performed|executed|passed)\b', low),
                'seo-specialist': lambda: len(lines) == 2 and lines[0].startswith('Title:') and lines[1].startswith('Description:') and 0 < len(lines[0][6:].strip()) <= 60 and 0 < len(lines[1][12:].strip()) <= 160 and 'luma' in low,
                'localization-editor': lambda: text.strip() == 'Speichern\nAbbrechen',
                'document-specialist': lambda: text.strip() == '- [ ] date\n- [ ] signature',
            }
            add('role_case', predicates[role]())
    elif role == 'analyst':
        add('csv_dialect', response['delimiter'] == ';' and response['decimal_separator'] == ',')
        add('findings', type(response['findings']) is list and 0 < len(response['findings']) <= 8 and all(type(x) is str and 0 < len(x.strip()) <= 500 for x in response['findings']))
    elif role == 'coordinator':
        add('instruction', type(response['instruction']) is str and 0 < len(response['instruction'].strip()) <= 1800)
    elif role == 'implementer':
        checks.extend(check_candidate(CSV, response))
    else:
        try:
            state = validate_verdict(response, expected['artifact_sha256'], CRITERIA)
            add('verdict', state == 'FIX_REQUIRED' and bool(response['issues']))
            actual = {c['id']: c['passed'] for c in response['checks']}
            add('independent_verdict', actual == {c['id']: c['passed'] for c in expected['deterministic_checks']})
        except GateError:
            add('verdict', False)
    return checks


SAFE_ERRORS = frozenset({'auth_required', 'profile_preflight_failed', 'tools_not_empty',
    'invalid_model_json', 'hermes_runtime_error', 'invalid_request', 'invalid_hermes_envelope',
    'model_timeout_outcome_unknown', 'hermes_process_failed', 'transport_failed',
    'ambiguous_request', 'board_failed', 'durability_failed'})


def _safe_error(exc):
    return str(exc) if str(exc) in SAFE_ERRORS else 'transport_failed'


def _publish(path, value):
    """Atomic latest view with immutable content-addressed historical snapshots."""
    import os
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    history = path.parent / 'history' / path.stem
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        write_snapshot(history / (canonical_hash(old) + '.json'), old)
    write_snapshot(history / (canonical_hash(value) + '.json'), value)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=True, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run_case(root: Path, role: str, backend, board=None):
    """One durable reservation; never retry uncertain calls. Doubles are explicit."""
    started = time.monotonic()
    request = case_request(role)
    root = Path(root)
    with workspace_lock(root):
        manifest = {'version': 1, 'role': role, 'request_sha256': canonical_hash(request),
                    'source_sha256': request['source_sha256'], 'contract_sha256': request['contract_sha256'],
                    'backend': backend_fingerprint(backend), 'max_calls': 1,
                    'mode': 'live' if getattr(backend, 'live', False) else 'TEST_DOUBLE'}
        write_snapshot(root / 'manifest.json', manifest)
        write_snapshot(root / 'request.json', request)
        ledger = RequestLedger(root / 'execution.sqlite3', max_calls=1)
        result = {'role': role, 'status': 'BLOCKED', 'model_calls': len(ledger.rows()),
                  'source_sha256': request['source_sha256'], 'contract_sha256': request['contract_sha256'],
                  'artifact': None, 'artifact_sha256': None, 'checks': [], 'mode': manifest['mode'],
                  'scope': SCOPE}
        card = None
        ticket = None
        phase = 'reserve'
        try:
            ticket = ledger.reserve(role, request)
            phase = 'board'
            if board is not None:
                card = board.start(ticket['id'], role, request)
            if ticket['state'] == 'COMPLETED':
                response = ticket['response']
            else:
                phase = 'transport'
                response = backend.call(role, request)
                phase = 'durability'
                ledger.complete(ticket['id'], response)
            phase = 'durability'
            write_snapshot(root / 'receipt.json', {'ticket_id': ticket['id'], 'request_sha256': canonical_hash(request), 'response_sha256': canonical_hash(response), 'mode': manifest['mode']})
            write_snapshot(root / 'artifacts' / 'response.json', response)
            phase = 'board'
            if board is not None:
                board.finish(card, response)
            phase = 'durability'
            checks = validate_role_response(role, request, response)
            result.update(status='ROLE_CHECK_PASS' if checks and all(c['passed'] for c in checks) else 'ROLE_CHECK_FAIL',
                          checks=checks, artifact='artifacts/response.json', artifact_sha256=canonical_hash(response))
        except Exception as exc:
            code = ('ambiguous_request' if isinstance(exc, AmbiguousRequest) else
                    'board_failed' if phase == 'board' else
                    'durability_failed' if phase == 'durability' else _safe_error(exc))
            if ticket is not None and ledger.status(ticket['id'])['state'] == 'PENDING':
                ledger.fail(ticket['id'], code)
                if board is not None and card is not None:
                    try:
                        board.fail(card, code)
                    except Exception:
                        pass
            result.update(error_code=code, checks=[{'id': 'execution', 'passed': False, 'evidence': code}])
        _publish(root / 'artifacts' / 'checks.json', result['checks'])
        result['model_calls'] = len(ledger.rows())
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        path = root / 'result.json'
        if path.exists():
            old = json.loads(path.read_text(encoding='utf-8'))
            if {k: v for k, v in old.items() if k != 'elapsed_seconds'} == {k: v for k, v in result.items() if k != 'elapsed_seconds'}:
                return old
        _publish(path, result)
        return result


def main(argv=None):
    from .runtime import PACKAGE_ROOT, DEFAULT_MODEL, inspect_runtime, find_install
    from .adapters import HermesBackend
    from .kanban import NativeBoard
    parser = argparse.ArgumentParser(description=SCOPE)
    parser.add_argument('--run', required=True)
    parser.add_argument('--roles', default=','.join(ROLE_IDS))
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args(argv)
    roles = args.roles.split(',')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', args.run):
        parser.error('Invalid run slug')
    if not roles or len(set(roles)) != len(roles) or any(r not in ROLE_IDS for r in roles):
        parser.error('Invalid or duplicate role selection')
    if not 1 <= args.timeout <= 600:
        parser.error('Timeout must be 1..600 seconds')
    try:
        project = Path(PACKAGE_ROOT)
        paths = [project / 'runs' / (args.run + '-' + r) for r in roles]
        report_path = project / 'reports' / (args.run + '.json')
        for path in paths + [report_path, project / 'reports' / (args.run + '-suite')]:
            if path.resolve() != path or not path.resolve().is_relative_to(project):
                raise GateError('Redirected path')
        preflight = inspect_runtime(project, roles, model=args.model)
        if not preflight['auth_present'] or not preflight['profiles_ok']:
            print(json.dumps({'status': 'BLOCKED', 'error_code': 'auth_required' if not preflight['auth_present'] else 'profile_preflight_failed'}), flush=True)
            return 2
        repo = find_install()
        suite_root = project / 'reports' / (args.run + '-suite')
        with workspace_lock(suite_root):
            write_snapshot(suite_root / 'manifest.json', {'roles': roles, 'model': args.model, 'timeout': args.timeout})
            results = []
            for role, root in zip(roles, paths):
                print(json.dumps({'role': role, 'progress': 'START'}), flush=True)
                try:
                    backend = HermesBackend(project, repo, model=args.model, timeout=args.timeout, receipts=root / 'receipts')
                    board = NativeBoard(repo, project / '.runtime' / 'hermes', root)
                    result = run_case(root, role, backend, board)
                except Exception:
                    req = case_request(role)
                    result = {'role': role, 'status': 'BLOCKED', 'error_code': 'durability_failed',
                              'model_calls': 0, 'source_sha256': req['source_sha256'], 'contract_sha256': req['contract_sha256'],
                              'artifact': None, 'artifact_sha256': None, 'checks': [{'id': 'execution', 'passed': False, 'evidence': 'durability_failed'}],
                              'mode': 'live', 'elapsed_seconds': 0}
                results.append(result)
                aggregate = {'run': args.run, 'roles': roles, 'scope': SCOPE, 'results': results,
                             'complete': len(results) == len(roles),
                             'status': 'ROLE_CHECK_PASS' if len(results) == len(roles) and all(r['status'] == 'ROLE_CHECK_PASS' for r in results) else 'ROLE_CHECK_FAIL'}
                _publish(report_path, aggregate)
                print(json.dumps({'role': role, 'progress': result['status'], 'elapsed_seconds': result['elapsed_seconds'], 'error_code': result.get('error_code')}), flush=True)
            return 0 if all(r['status'] == 'ROLE_CHECK_PASS' for r in results) else 2
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'error_code': 'durability_failed'}), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
