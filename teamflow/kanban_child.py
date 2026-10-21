"""One native DB operation; no agent, dispatcher or gateway entrypoint."""
import contextlib
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def require_owned_run(conn, task, run_id, owner):
    if (task is None or task.status != 'running' or task.claim_lock != owner
            or task.current_run_id != run_id):
        raise RuntimeError()
    run = conn.execute('SELECT * FROM task_runs WHERE id = ? AND task_id = ?',
                       (run_id, task.id)).fetchone()
    if (not run or run['status'] != 'running' or run['ended_at'] is not None
            or run['claim_lock'] != owner):
        raise RuntimeError()


def execute(payload):
    sys.path.insert(0, payload['repo'])
    from hermes_cli import kanban_db as db
    root = Path(payload['run_root']).resolve()
    owner = 'teamflow:' + digest(os.path.normcase(str(root)))
    conn = db.connect(root / 'kanban.db')
    try:
        operation = payload['operation']
        if operation == 'start':
            if (type(payload['ticket_id']) is not int
                    or not isinstance(payload['role'], str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', payload['role'])
                    or not isinstance(payload['request'], dict)):
                raise ValueError()
        if operation == 'finish' and not isinstance(payload['response'], dict):
            raise ValueError()
        if operation == 'fail' and not isinstance(payload['reason'], str):
            raise ValueError()
        if operation in {'finish', 'fail'}:
            handle = payload['handle']
            if (not isinstance(handle, dict) or not isinstance(handle.get('id'), str)
                    or type(handle.get('run_id')) is not int or handle['run_id'] <= 0):
                raise ValueError()
        if operation == 'rows':
            return [asdict(task) for task in db.list_tasks(conn, include_archived=True)]
        if operation == 'start':
            key = digest([os.path.normcase(str(root)), payload['ticket_id'],
                          payload['role'], digest(payload['request'])])
            existing = conn.execute('SELECT id FROM tasks WHERE idempotency_key = ?', (key,)).fetchone()
            if existing:
                task = db.get_task(conn, existing['id'])
                if task.status == 'done':
                    run = conn.execute("SELECT id FROM task_runs WHERE task_id = ? AND outcome = 'completed' ORDER BY id DESC LIMIT 1", (task.id,)).fetchone()
                    if not run:
                        raise RuntimeError()
                    return {'id': task.id, 'run_id': run['id']}
                if task.status == 'running':
                    require_owned_run(conn, task, task.current_run_id, owner)
                    return {'id': task.id, 'run_id': task.current_run_id}
                if task.status != 'ready' or task.claim_lock:
                    raise RuntimeError()
                task_id = task.id
            else:
                task_id = db.create_task(conn, title='Teamflow ticket ' + str(payload['ticket_id']),
                                         assignee=payload['role'], created_by='teamflow',
                                         idempotency_key=key,
                                         workspace_kind='dir', workspace_path=str(root))
            task = db.claim_task(conn, task_id, claimer=owner)
            if task is None:
                raise RuntimeError()
            return {'id': task.id, 'run_id': task.current_run_id}
        if operation == 'fail':
            handle = payload['handle']
            require_owned_run(conn, db.get_task(conn, handle['id']), handle['run_id'], owner)
            if not db.block_task(conn, handle['id'], expected_run_id=handle['run_id'],
                                 reason='sha256:' + digest(payload['reason'])):
                raise RuntimeError()
            return None
        if operation == 'finish':
            handle = payload['handle']
            value = digest(payload['response'])
            task = db.get_task(conn, handle['id'])
            if task and task.status == 'done':
                run = conn.execute('SELECT * FROM task_runs WHERE task_id = ? AND id = ?',
                                   (handle['id'], handle['run_id'])).fetchone()
                if (not run or run['outcome'] != 'completed'
                        or json.loads(run['metadata'] or '{}').get('response_hash') != value
                        or task.result != 'sha256:' + value):
                    raise RuntimeError()
                return None
            require_owned_run(conn, task, handle['run_id'], owner)
            if not db.complete_task(conn, handle['id'], expected_run_id=handle['run_id'],
                                    result='sha256:' + value, summary='sha256:' + value,
                                    metadata={'response_hash': value}):
                raise RuntimeError()
            return None
        raise ValueError()
    finally:
        conn.close()


def main():
    # Native helpers may print. Suppress both streams, including exception text.
    try:
        payload = json.load(sys.stdin)
        with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = execute(payload)
        envelope = {'ok': True, 'result': result}
    except Exception:
        envelope = {'ok': False, 'error': 'NativeOperationError'}
    sys.stdout.write(json.dumps(envelope, ensure_ascii=True))


if __name__ == '__main__':
    main()
