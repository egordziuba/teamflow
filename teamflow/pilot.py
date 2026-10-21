"""Deterministic acceptance oracle for the bounded CSV pilot (no model code execution)."""
import csv
import io
import re
from decimal import Decimal


def expected_result(source: str) -> dict:
    accepted, excluded, seen = [], [], set()
    total = Decimal('0')
    reader = csv.DictReader(io.StringIO(source), delimiter=';')
    if reader.fieldnames != ['id', 'amount', 'currency', 'status']:
        raise ValueError('Source headers do not match the approved pilot contract')
    for line, row in enumerate(reader, 2):
        reason = None
        if None in row or any(v is None for v in row.values()):
            reason = 'malformed_row'
        elif not row['id'].strip():
            reason = 'missing_id'
        elif row['status'] != 'settled':
            reason = 'not_settled'
        elif row['currency'] != 'EUR':
            reason = 'unsupported_currency'
        elif not re.fullmatch(r'-?\d{1,12},\d{2}', row['amount']):
            reason = 'invalid_amount'
        elif row['id'] in seen:
            reason = 'duplicate_id'
        if reason:
            excluded.append({'row': line, 'reason': reason})
        else:
            amount = Decimal(row['amount'].replace(',', '.'))
            seen.add(row['id'])
            accepted.append({'row': line, 'id': row['id'], 'amount': format(amount, '.2f')})
            total += amount
    return {'accepted': accepted, 'excluded': excluded, 'total_eur': format(total, '.2f')}


CRITERIA = ['schema', 'accepted_rows', 'excluded_rows', 'total_eur']


def check_candidate(source: str, candidate: dict) -> list[dict]:
    import json
    expected = expected_result(source)
    schema = (type(candidate) is dict and set(candidate) == {'accepted', 'excluded', 'total_eur'}
              and type(candidate.get('accepted')) is list and type(candidate.get('excluded')) is list
              and type(candidate.get('total_eur')) is str)
    if schema:
        schema = all(type(x) is dict and set(x) == {'row', 'id', 'amount'}
                     and type(x['row']) is int and type(x['id']) is str and type(x['amount']) is str
                     for x in candidate['accepted'])
        schema = schema and all(type(x) is dict and set(x) == {'row', 'reason'}
                                and type(x['row']) is int and type(x['reason']) is str
                                for x in candidate['excluded'])
    checks = [{'id': 'schema', 'passed': bool(schema), 'evidence': 'Exact JSON fields and strict scalar types checked'}]
    for cid, key in [('accepted_rows', 'accepted'), ('excluded_rows', 'excluded'), ('total_eur', 'total_eur')]:
        actual = candidate.get(key) if type(candidate) is dict else None
        same = json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected[key], sort_keys=True)
        checks.append({'id': cid, 'passed': bool(schema and same),
                       'evidence': ('Matches deterministic source reconciliation' if same else
                                    'Mismatch against deterministic source reconciliation')})
    return checks
