"""Read-only projections of existing run evidence; never imports or starts an agent."""
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .roles import catalog

SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
STATE_LABELS = {'COMPLETED': 'Ответ получен', 'PENDING': 'Ожидает ответа — по журналу',
                'FAILED': 'Шаг остановлен'}
PHASES = {'analyst': 'Проверка контекста', 'coordinator': 'Постановка задания',
          'implementer': 'Подготовка результата', 'verifier': 'Независимая проверка'}


def _json(path):
    if not path.exists():
        return None
    if path.is_symlink() or path.resolve() != path.absolute() or path.stat().st_size > 2_000_000:
        raise ValueError('unsafe evidence path')
    from .adapters import parse_object
    return parse_object(path.read_text(encoding='utf-8'))


def _seconds(start, end):
    if not start or not end:
        return None
    return max(0, round((datetime.fromisoformat(end.replace('Z', '+00:00')) -
                         datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds(), 1))


def _read_db(path, queries):
    import tempfile
    if not path.is_file() or path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError('missing or redirected ledger')
    # Even SQLite mode=ro may create WAL/SHM beside the original database.
    # Read stable bytes twice and rebuild any WAL index ONLY in a disposable copy.
    wal = Path(str(path) + '-wal')
    def capture():
        if path.stat().st_size > 50_000_000:
            raise ValueError('ledger exceeds observation limit')
        if wal.exists() and (wal.is_symlink() or wal.resolve() != wal.absolute() or wal.stat().st_size > 50_000_000):
            raise ValueError('unsafe WAL')
        return path.read_bytes(), wal.read_bytes() if wal.exists() else None
    first = capture()
    if first != capture():
        raise ValueError('ledger changing during observation')
    with tempfile.TemporaryDirectory(prefix='teamflow-readonly-') as temp:
        copy = Path(temp) / 'ledger.sqlite3'
        copy.write_bytes(first[0])
        if first[1] is not None:
            Path(str(copy) + '-wal').write_bytes(first[1])
        with closing(sqlite3.connect(copy.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            result = [[dict(r) for r in db.execute(query)] for query in queries]
    return result


def _rows(path):
    requests, events = _read_db(path, [
        'SELECT id,role,state,request_json,response_json,reason FROM requests ORDER BY id LIMIT 1001',
        'SELECT id,ticket_id,state,created_at FROM events ORDER BY id LIMIT 3001'])
    if len(requests) > 1000 or len(events) > 3000:
        raise ValueError('observation limit exceeded')
    return requests, events


def _artifact(root, relative):
    if type(relative) is not str or not re.fullmatch(r'artifacts/[a-zA-Z0-9_-]+\.json', relative):
        raise ValueError('unsafe artifact reference')
    path = root / relative
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError('redirected artifact')
    value = _json(path)
    if value is None:
        raise ValueError('missing artifact')
    return value


def _evidence(root, result, requests, brief):
    import hashlib
    from .ledger import canonical_hash, validate_verdict
    from .pilot import check_candidate, CRITERIA
    if not requests or any(r['state'] != 'COMPLETED' for r in requests):
        raise ValueError('unfinished request history')
    if type(result.get('model_calls')) is not int or result['model_calls'] != len(requests):
        raise ValueError('request coverage mismatch')
    manifest = _json(root / 'manifest.json')
    first = json.loads(requests[0]['request_json'])
    if not manifest or canonical_hash(first['contract']) != result['contract_sha256']:
        raise ValueError('contract mismatch')
    if result['contract_sha256'] != manifest['contract_sha256'] or result['source_sha256'] != manifest['source_sha256']:
        raise ValueError('manifest mismatch')
    artifacts = []
    if result['status'] in {'ROLE_CHECK_PASS', 'ROLE_CHECK_FAIL'}:
        from .role_checks import validate_role_response
        role = result.get('role')
        if (len(requests) != 1 or role not in catalog() or requests[0]['role'] != role
                or first.get('stage') != 'role-check' or first.get('role_under_test') != role
                or canonical_hash(first['sources']) != result['source_sha256']
                or canonical_hash(first) != manifest.get('request_sha256')):
            raise ValueError('role check request mismatch')
        candidate = _artifact(root, result['artifact'])
        if (canonical_hash(candidate) != result['artifact_sha256']
                or canonical_hash(json.loads(requests[0]['response_json'])) != canonical_hash(candidate)):
            raise ValueError('role check receipt mismatch')
        checks = validate_role_response(role, first, candidate)
        passed = bool(checks) and all(c['passed'] for c in checks)
        if canonical_hash(checks) != canonical_hash(result['checks']) or passed != (result['status'] == 'ROLE_CHECK_PASS'):
            raise ValueError('role check decision mismatch')
        artifacts.append({'label': 'Ответ на контрольное задание', 'path': result['artifact'], 'state': 'verified' if passed else 'draft'})
        return ('accepted' if passed else 'blocked', 'Тест роли пройден' if passed else 'Тест роли не пройден',
                artifacts, 'Короткий контракт перепроверен по ответу в журнале. Это не полная оценка компетенции специалиста.')
    if result['status'] == 'NO_SPECIALISTS_REQUESTED':
        routing = _json(root / 'routing.json')
        response = json.loads(requests[0]['response_json'])
        if (len(requests) != 1 or requests[0]['role'] != 'coordinator'
                or first.get('stage') != 'specialist-routing'
                or brief is None or canonical_hash(brief['sources']) != result['source_sha256']
                or result.get('activated_roles') != [] or result.get('reports') != []
                or not routing or routing.get('requests') != []
                or canonical_hash(routing) != canonical_hash(response)):
            raise ValueError('empty routing receipt mismatch')
        return ('incomplete', 'Дополнительные роли не потребовались', [],
                'Решение координатора сверено с журналом. Это не приёмка всего проекта.')
    if result['status'] == 'ACCEPTED':
        source = first['source']
        if hashlib.sha256(source.encode('utf-8')).hexdigest() != result['source_sha256']:
            raise ValueError('source mismatch')
        candidate = _artifact(root, result['artifact'])
        digest = canonical_hash(candidate)
        if digest != result['artifact_sha256'] or not all(c['passed'] for c in check_candidate(source, candidate)):
            raise ValueError('artifact mismatch')
        review = result['attempts'][-1]['review']
        if validate_verdict(review, digest, CRITERIA) != 'PASS':
            raise ValueError('review not passed')
        last_response = json.loads(requests[-1]['response_json'])
        if requests[-1]['role'] != 'verifier' or canonical_hash(last_response) != canonical_hash(review):
            raise ValueError('review receipt mismatch')
        artifacts.append({'label': 'Проверенный результат CSV', 'path': result['artifact'], 'state': 'verified'})
        return 'accepted', 'Результат принят', artifacts, 'Хеш, источник, вердикт и программная сверка совпадают.'
    if result['status'] == 'DRAFTS_REQUIRE_REVIEW':
        if brief is None or canonical_hash(brief['sources']) != result['source_sha256']:
            raise ValueError('source mismatch')
        seen = []
        for report in result['reports']:
            if report['role'] not in catalog() or report['role'] in seen:
                raise ValueError('invalid report role')
            candidate = _artifact(root, report['artifact'])
            if canonical_hash(candidate) != report['sha256'] or candidate['role'] != report['role']:
                raise ValueError('artifact mismatch')
            if candidate['source_sha256'] != result['source_sha256'] or candidate['contract_sha256'] != result['contract_sha256']:
                raise ValueError('stale report')
            authors = [row for row in requests if row['role'] == report['role']]
            if len(authors) != 1 or canonical_hash(json.loads(authors[0]['response_json'])) != canonical_hash(candidate):
                raise ValueError('specialist receipt mismatch')
            seen.append(report['role'])
            artifacts.append({'label': catalog()[report['role']]['title'] + ' · черновик', 'path': report['artifact'], 'state': 'draft'})
        integration = _json(root / 'integration.json')
        if not seen or seen != result['activated_roles'] or not integration or integration['specialist_roles'] != seen:
            raise ValueError('handoff mismatch')
        if canonical_hash(json.loads(requests[-1]['response_json'])) != canonical_hash(integration):
            raise ValueError('handoff receipt mismatch')
        artifacts.append({'label': 'Инструкция следующего этапа', 'path': 'integration.json', 'state': 'draft'})
        return 'drafts', 'Черновики готовы к проверке', artifacts, 'Целостность черновиков и передача координатору подтверждены; качество требует проверки.'
    raise ValueError('unknown result contract')


def _run(root):
    registry = catalog()
    value = {'id': root.name, 'kind': 'csv', 'status': 'unknown', 'status_label': 'Неизвестно',
             'headline': 'Сверка операций CSV', 'current_role': None, 'current_stage': 'Нет подтверждённого этапа',
             'updated_at': None, 'counts': {'completed': 0, 'pending': 0, 'failed': 0, 'planned': 0},
             'steps': [], 'roles': [], 'events': [], 'artifacts': [],
             'evidence': {'checked': False, 'summary': 'Итог ещё не подтверждён'},
             'warning': None, 'next_action': 'Открыть журнал выполнения'}
    try:
        requests, events = _rows(root / 'execution.sqlite3')
        routing = _json(root / 'routing.json')
        brief = _json(root / 'brief.json')
        if routing is not None or brief is not None:
            value['kind'] = 'specialists'
            value['headline'] = 'Работа специалистов'
        roles = {role: 'idle' for role in registry}
        seen = set()
        for row in requests:
            if row['role'] not in registry or row['state'] not in STATE_LABELS:
                raise ValueError('invalid ledger state')
            role = row['role']
            data = json.loads(row['request_json'])
            response = json.loads(row['response_json']) if row['response_json'] else {}
            if type(data) is not dict or type(response) is not dict:
                raise ValueError('invalid persisted payload')
            related = [e for e in events if e['ticket_id'] == row['id']]
            start = next((e['created_at'] for e in related if e['state'] == 'PENDING'), None)
            end = next((e['created_at'] for e in reversed(related) if e['state'] in {'COMPLETED', 'FAILED'}), None)
            phase = PHASES.get(role, 'Работа специалиста')
            if data.get('stage') == 'role-check':
                value['kind'] = 'role-check'
                value['headline'] = 'Проверка · ' + registry[role]['title']
                phase = 'Короткое контрольное задание'
            if data.get('stage') == 'specialist-routing':
                phase = 'Выбор специалистов'
            elif data.get('stage') == 'specialist-integration':
                phase = 'Согласование и передача результатов'
            state = {'COMPLETED': 'completed', 'PENDING': 'pending', 'FAILED': 'failed'}[row['state']]
            label = STATE_LABELS[row['state']]
            note = ''
            if row['state'] == 'FAILED':
                code = row['reason'] if row['reason'] in {'ValueError', 'TimeoutError', 'RuntimeError', 'GateError'} else 'ошибка выполнения'
                note = 'Ответ не принят. Код журнала: ' + code + '. Повтор автоматически не запущен.'
            elif row['state'] == 'PENDING':
                note = 'Запрос сохранён; активность процесса отдельно не подтверждается.'
            elif response.get('verdict') == 'FIX_REQUIRED':
                label = 'Вернул на исправление'
                note = 'Проверка завершена, но результат отклонён.'
            elif response.get('verdict') == 'PASS':
                label = 'Проверка пройдена'
            attempt = data.get('attempt') if type(data.get('attempt')) is int else None
            value['steps'].append({'id': str(row['id']), 'role': role, 'title': registry[role]['title'],
                'phase': phase, 'attempt': attempt, 'state': state, 'state_label': label,
                'started_at': start, 'ended_at': end, 'duration_seconds': _seconds(start, end), 'note': note})
            value['counts'][state] += 1
            roles[role] = state
            seen.add(role)
        if routing:
            selected = routing.get('requests')
            if type(selected) is not list or len(selected) > len(registry) or any(type(item) is not dict for item in selected):
                raise ValueError('invalid routing records')
            for request in selected:
                role = request.get('role')
                if role not in registry:
                    raise ValueError('unknown planned role')
                if role not in seen:
                    value['steps'].append({'id': 'planned-' + role, 'role': role, 'title': registry[role]['title'],
                         'phase': 'Выбран координатором', 'attempt': None, 'state': 'planned',
                         'state_label': 'Ещё не запускался', 'started_at': None, 'ended_at': None,
                         'duration_seconds': None, 'note': 'Ждёт предыдущего этапа; запроса модели ещё нет.'})
                    value['counts']['planned'] += 1
                    roles[role] = 'planned'
        value['roles'] = [{'id': role, 'title': info['title'], 'state': roles[role]} for role, info in registry.items()]
        indexed = {r['id']: r['role'] for r in requests}
        for e in events:
            if e['ticket_id'] not in indexed or e['state'] not in STATE_LABELS:
                raise ValueError('invalid event')
            role = indexed[e['ticket_id']]
            value['events'].append({'at': e['created_at'], 'role': role,
                  'label': registry[role]['title'] + ' · ' + STATE_LABELS[e['state']],
                  'state': e['state'].lower(), 'ticket_id': e['ticket_id']})
        value['updated_at'] = events[-1]['created_at'] if events else None
        current = next((s for s in reversed(value['steps']) if s['state'] in {'failed', 'pending'}), None)
        current = current or next((s for s in reversed(value['steps']) if s['state'] != 'planned'), None)
        if current:
            value['current_role'], value['current_stage'] = current['role'], current['phase']
        if value['counts']['failed']:
            value.update(status='blocked', status_label='Заблокировано', warning=current['note'],
                         next_action='Разобрать остановку; панель не запускает повторные попытки.')
        elif value['counts']['pending']:
            value.update(status='pending', status_label='Ожидает ответа', warning='Состояние из журнала, не проверка активности процесса.',
                         next_action='Дождаться новой записи. При длительном ожидании проверить процесс отдельно.')
        elif requests:
            value.update(status='incomplete', status_label='Итог не принят', next_action='Завершить проверку и передачу результата.')
        else:
            value.update(status='empty', status_label='Нет шагов', next_action='Запросы ещё не зарегистрированы.')
        native = None
        if (root / 'kanban.db').exists():
            native = _read_db(root / 'kanban.db', ['SELECT id,assignee,status FROM tasks LIMIT 1001'])[0]
            if len(native) > 1000:
                raise ValueError('too many native tasks')
            if any(t['status'] == 'blocked' for t in native):
                value.update(status='blocked', status_label='Заблокировано',
                             warning='Kanban сохранил заблокированный шаг. ' + (value['warning'] or ''),
                             next_action='Разобрать остановку; повтор автоматически не запущен.')
        result = _json(root / 'result.json')
        if result is not None and value['status'] not in {'blocked', 'pending'}:
            try:
                if native is not None and (len(native) != len(requests) or any(t['status'] != 'done' for t in native)):
                    raise ValueError('native handoff unfinished')
                status, label, artifacts, summary = _evidence(root, result, requests, brief)
                value.update(status=status, status_label=label, artifacts=artifacts,
                             current_stage='Приёмка завершена' if status == 'accepted' else 'Ручная проверка черновиков',
                             next_action='Результат сохранён.' if status == 'accepted' else 'Проверить черновики перед реализацией.')
                value['evidence'] = {'checked': True, 'summary': summary}
                if result['status'] in {'ROLE_CHECK_PASS', 'ROLE_CHECK_FAIL'}:
                    value.update(current_stage=label,
                                 next_action='Короткая проверка завершена; сложные задания проверяются отдельно.' if status == 'accepted' else 'Разобрать замечания к ответу; автоматически не повторять.')
                if result['status'] == 'NO_SPECIALISTS_REQUESTED':
                    value.update(current_stage='Выбор специалистов завершён',
                                 next_action='Продолжить основную задачу без дополнительных ролей.')
                if result.get('mode') == 'TEST_DOUBLE':
                    value['warning'] = 'Тестовые ответы; это не живой запуск моделей.'
            except (OSError, ValueError, KeyError, TypeError, IndexError, ArithmeticError):
                value.update(status='evidence_mismatch', status_label='Итог не подтверждён',
                             warning='Сохранённая отметка результата не совпала с проверкой файлов или журнала.',
                             next_action='Проверить целостность доказательств; успех не подтверждать.')
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        value.update(status='unknown', status_label='Данные недоступны', warning='Не удалось согласованно прочитать журнал. Успех не подтверждён.',
                     next_action='Проверить доступность и целостность файлов запуска.')
    return value


def snapshot(project):
    project = Path(project).resolve()
    root = project / 'runs'
    runs = []
    if root.is_dir() and root.resolve() == root:
        for item in root.iterdir():
            if item.is_dir() and SLUG.fullmatch(item.name) and not item.is_symlink() and item.resolve() == item:
                runs.append(_run(item))
    runs.sort(key=lambda r: r['updated_at'] or '', reverse=True)
    return {'schema': 1, 'read_only': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'poll_seconds': 3, 'roles': [{'id': k, 'title': v['title']} for k, v in catalog().items()], 'runs': runs}
