"""Fail-closed durable execution journal and strict evidence validation."""
import hashlib
import json
import math
import sqlite3
import time
from contextlib import contextmanager


class GateError(ValueError):
    """Input or state is unsafe to proceed."""


class BudgetExceeded(GateError):
    """The durable call budget is exhausted."""


class AmbiguousRequest(GateError):
    """A request may already have been dispatched; never retry it."""


class RequestLedger:
    """One on-disk journal per project. Summaries omit all free-form payloads.

    The database retains raw request/response evidence: protect the file as
    sensitive data. status() intentionally returns completed response evidence.
    Each operation uses its own connection, permitting independent threads.
    """

    def __init__(self, path, max_calls=12):
        if type(max_calls) is not int or max_calls < 0:
            raise GateError('max_calls must be a nonnegative integer')
        self.path = str(path)
        self.max_calls = max_calls
        with self._connection() as db:
            # Concurrent first-open WAL conversion can ignore SQLite's busy
            # handler. Retry only this idempotent local PRAGMA, never a call.
            deadline = time.monotonic() + 30
            while True:
                try:
                    db.execute('PRAGMA journal_mode=WAL').fetchone()
                    break
                except sqlite3.OperationalError as exc:
                    code = getattr(exc, 'sqlite_errorcode', 0)
                    if code & 255 not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS limits (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    max_calls INTEGER NOT NULL CHECK(max_calls>=0)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY,
                    identity TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('PENDING','COMPLETED','FAILED')),
                    response_json TEXT,
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    ticket_id INTEGER NOT NULL REFERENCES requests(id),
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'Event history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'Event history is append-only'); END;
            ''')
            # Opening a journal may tighten, but never silently replenish, its budget.
            db.execute('INSERT INTO limits(id,max_calls) VALUES (1,?) '
                       'ON CONFLICT(id) DO UPDATE SET max_calls=MIN(max_calls,excluded.max_calls)',
                       (max_calls,))

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA busy_timeout=30000')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA foreign_keys=ON')
            yield db
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    @staticmethod
    def _ticket(row):
        ticket = {'id': row['id'], 'state': row['state']}
        if row['state'] == 'COMPLETED':
            ticket['response'] = json.loads(row['response_json'])
        return ticket

    def reserve(self, role, request: dict):
        from .roles import ROLE_IDS
        if type(role) is not str or role not in ROLE_IDS:
            raise GateError('Invalid role')
        if type(request) is not dict:
            raise GateError('Request must be a JSON object')
        payload = _canonical(request)
        identity = canonical_hash({'role': role, 'request': json.loads(payload)})
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM requests WHERE identity=?', (identity,)).fetchone()
            if row is not None:
                if row['state'] != 'COMPLETED':
                    raise AmbiguousRequest('Existing request is not safely replayable')
                return self._ticket(row)
            limit = db.execute('SELECT max_calls FROM limits WHERE id=1').fetchone()[0]
            if db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] >= limit:
                raise BudgetExceeded('Call budget exhausted')
            ticket_id = db.execute(
                "INSERT INTO requests(identity,role,request_json,state) VALUES (?,?,?,'PENDING')",
                (identity, role, payload)).lastrowid
            db.execute("INSERT INTO events(ticket_id,state) VALUES (?,'PENDING')", (ticket_id,))
            row = db.execute('SELECT * FROM requests WHERE id=?', (ticket_id,)).fetchone()
            db.commit()
            return self._ticket(row)

    def complete(self, ticket_id, response: dict):
        if type(response) is not dict:
            raise GateError('Response must be a JSON object')
        payload = _canonical(response)
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            updated = db.execute(
                "UPDATE requests SET state='COMPLETED',response_json=? WHERE id=? AND state='PENDING'",
                (payload, ticket_id)).rowcount
            if updated != 1:
                raise GateError('Only a pending ticket can complete once')
            db.execute("INSERT INTO events(ticket_id,state) VALUES (?,'COMPLETED')", (ticket_id,))
            row = db.execute('SELECT * FROM requests WHERE id=?', (ticket_id,)).fetchone()
            db.commit()
            return self._ticket(row)

    def fail(self, ticket_id, reason):
        if type(reason) is not str or not reason.strip():
            raise GateError('Failure reason must be nonempty text')
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            updated = db.execute(
                "UPDATE requests SET state='FAILED',reason=? WHERE id=? AND state='PENDING'",
                (reason, ticket_id)).rowcount
            if updated != 1:
                raise GateError('Only a pending ticket can fail once')
            db.execute("INSERT INTO events(ticket_id,state) VALUES (?,'FAILED')", (ticket_id,))
            row = db.execute('SELECT * FROM requests WHERE id=?', (ticket_id,)).fetchone()
            db.commit()
            return self._ticket(row)

    def status(self, ticket_id):
        with self._connection() as db:
            row = db.execute('SELECT * FROM requests WHERE id=?', (ticket_id,)).fetchone()
            if row is None:
                raise GateError('Unknown ticket')
            return self._ticket(row)

    def rows(self):
        with self._connection() as db:
            return [dict(row) for row in db.execute('SELECT id,identity,role,state FROM requests ORDER BY id')]

    def events(self):
        with self._connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM events ORDER BY id')]


def _canonical(value):
    def check(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child)
            return
        raise GateError('Expected strict JSON values and string keys')
    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    except (RecursionError, TypeError, ValueError) as exc:
        raise GateError('Invalid strict JSON') from exc


def validate_verdict(verdict: dict, expected_hash: str, expected_criteria: list[str]) -> str:
    if (type(expected_hash) is not str or len(expected_hash) != 64
            or any(c not in '0123456789abcdef' for c in expected_hash)):
        raise GateError('Invalid expected artifact hash')
    if (type(expected_criteria) is not list
            or any(type(c) is not str or not c.strip() for c in expected_criteria)
            or len(set(expected_criteria)) != len(expected_criteria)):
        raise GateError('Invalid expected criteria')
    if type(verdict) is not dict or set(verdict) != {'verdict', 'artifact_sha256', 'checks', 'issues'}:
        raise GateError('Invalid verdict fields')
    state = verdict['verdict']
    if type(state) is not str or state not in ('PASS', 'FIX_REQUIRED', 'CONTEXT_INVALID', 'NEEDS_DECISION'):
        raise GateError('Invalid verdict state')
    if verdict['artifact_sha256'] != expected_hash:
        raise GateError('Stale artifact hash')
    checks, issues = verdict['checks'], verdict['issues']
    if type(checks) is not list or type(issues) is not list or any(type(i) is not str for i in issues):
        raise GateError('Invalid checks or issues')
    seen = set()
    for check in checks:
        if type(check) is not dict or set(check) != {'id', 'passed', 'evidence'}:
            raise GateError('Invalid check fields')
        key = check['id']
        if type(key) is not str or key not in expected_criteria or key in seen:
            raise GateError('Unknown or duplicate criterion')
        seen.add(key)
        if type(check['passed']) is not bool or type(check['evidence']) is not str or not check['evidence'].strip():
            raise GateError('Check requires strict boolean and evidence')
    if seen != set(expected_criteria):
        raise GateError('Missing criteria')
    if state == 'PASS' and (issues or not all(c['passed'] for c in checks)):
        raise GateError('Unsupported PASS')
    return state


def canonical_hash(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()
