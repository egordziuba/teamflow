"""On-demand advisory specialists. Outputs are drafts, never automatic project acceptance."""
from pathlib import Path

from .ledger import RequestLedger, GateError, canonical_hash
from .roles import allowed_specialists, catalog, validate_requests
from .workflow import workspace_lock, write_snapshot, backend_fingerprint


def run_specialists(root, brief, backend, *, board=None, max_specialists=3, max_calls=5):
    if (type(brief) is not dict or set(brief) != {'goal', 'project_type', 'sources', 'acceptance'}
            or type(brief['goal']) is not str or not brief['goal'].strip()
            or type(brief['sources']) is not list or not brief['sources']
            or type(brief['acceptance']) is not list or not brief['acceptance']
            or any(type(x) is not str or not x.strip() for x in brief['acceptance'])
            or any(type(s) is not dict or set(s) != {'id', 'text'}
                   or any(type(s[k]) is not str or not s[k].strip() for k in ('id', 'text'))
                   for s in brief['sources'])):
        raise GateError('Invalid project brief')
    available = allowed_specialists(brief['project_type'])
    validate_requests(brief['project_type'], [], max_specialists)
    source_hash = canonical_hash(brief['sources'])
    contract = {'goal': brief['goal'], 'acceptance': brief['acceptance'],
                'boundaries': ['DRAFT ONLY', 'No tools', 'No external effects', 'No invented source facts']}
    contract_hash = canonical_hash(contract)
    root = Path(root)
    with workspace_lock(root):
        write_snapshot(root / 'brief.json', brief)
        write_snapshot(root / 'manifest.json', {'source_sha256': source_hash, 'contract_sha256': contract_hash,
                       'max_specialists': max_specialists, 'max_calls': max_calls, 'project_type': brief['project_type'],
                       'backend': backend_fingerprint(backend)})
        ledger = RequestLedger(root / 'execution.sqlite3', max_calls=max_calls)

        def ask(role, payload):
            request = {'sources': brief['sources'], 'source_sha256': source_hash,
                       'contract': contract, 'contract_sha256': contract_hash, **payload}
            ticket = ledger.reserve(role, request)
            card = board.start(ticket['id'], role, request) if board else None
            if ticket['state'] == 'COMPLETED':
                if board:
                    board.finish(card, ticket['response'])
                return ticket['response']
            try:
                response = backend.call(role, request)
                ledger.complete(ticket['id'], response)
            except Exception as exc:
                ledger.fail(ticket['id'], type(exc).__name__)
                if board:
                    board.fail(card, type(exc).__name__)
                raise
            if board:
                board.finish(card, response)
            return response

        route = ask('coordinator', {'stage': 'specialist-routing', 'project_type': brief['project_type'],
                    'available_specialists': {r: catalog()[r] for r in available},
                    'max_specialists': max_specialists,
                    'instruction': 'Choose only specialists necessary for this brief. Zero is valid. Do not launch all roles.',
                    'output_schema': {'requests': [{'role': 'allowed role id', 'reason': 'why needed',
                                                   'deliverable': 'specific bounded output'}],
                                      'rationale': 'selection rationale'}})
        if type(route) is not dict or set(route) != {'requests', 'rationale'} or type(route['rationale']) is not str or not route['rationale'].strip():
            raise GateError('Invalid routing response')
        selected = validate_requests(brief['project_type'], route['requests'], max_specialists)
        if len(selected) + (2 if selected else 1) > max_calls:
            raise GateError('Specialist selection exceeds call budget')
        write_snapshot(root / 'routing.json', route)
        reports = []
        report_bodies = []
        for task in selected:
            role = task['role']
            response = ask(role, {'task': task, 'output_schema': {
                'role': role, 'source_sha256': 'copy exact input', 'contract_sha256': 'copy exact input',
                'deliverable': 'nonempty text containing the requested draft or specification',
                'limitations': ['nonempty strings for any unverified facts or unavailable capabilities']}})
            if (type(response) is not dict or set(response) != {'role', 'source_sha256', 'contract_sha256', 'deliverable', 'limitations'}
                    or response['role'] != role or response['source_sha256'] != source_hash
                    or response['contract_sha256'] != contract_hash
                    or type(response['deliverable']) is not str or not response['deliverable'].strip()
                    or type(response['limitations']) is not list
                    or any(type(x) is not str or not x.strip() for x in response['limitations'])):
                raise GateError('Invalid or stale specialist output: ' + role)
            write_snapshot(root / 'artifacts' / (role + '.json'), response)
            report_bodies.append(response)
            reports.append({'role': role, 'artifact': 'artifacts/' + role + '.json',
                            'sha256': canonical_hash(response), 'review_required': True})
        if selected:
            integration = ask('coordinator', {'stage': 'specialist-integration', 'specialist_reports': report_bodies,
                'instruction': 'Integrate these specialist drafts into concrete next-stage instructions. Preserve limitations and unresolved disagreements. Do not claim implementation or final acceptance.',
                'output_schema': {'instruction': 'nonempty next-stage instruction',
                                  'specialist_roles': [x['role'] for x in selected],
                                  'open_questions': ['unresolved questions or limitations']}})
            if (type(integration) is not dict or set(integration) != {'instruction', 'specialist_roles', 'open_questions'}
                    or type(integration['instruction']) is not str or not integration['instruction'].strip()
                    or integration['specialist_roles'] != [x['role'] for x in selected]
                    or type(integration['open_questions']) is not list
                    or any(type(x) is not str or not x.strip() for x in integration['open_questions'])):
                raise GateError('Invalid specialist handoff integration')
            write_snapshot(root / 'integration.json', integration)
        result = {'status': 'DRAFTS_REQUIRE_REVIEW' if selected else 'NO_SPECIALISTS_REQUESTED',
                  'mode': 'live' if getattr(backend, 'live', False) else 'TEST_DOUBLE',
                  'activated_roles': [x['role'] for x in selected], 'reports': reports,
                  'model_calls': len(ledger.rows()), 'source_sha256': source_hash, 'contract_sha256': contract_hash}
        write_snapshot(root / 'result.json', result)
        return result
