"""Connection API compatibility without an installed Hermes."""
import io
import json
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from teamflow import kanban_child


@pytest.fixture(params=['legacy', 'split', 'both'])
def fake_hermes(request, monkeypatch):
    package = ModuleType('hermes_cli')
    package.__path__ = []
    db = ModuleType('hermes_cli.kanban_db')
    split = ModuleType('hermes_cli.kanban_db_connect')
    legacy_connect = Mock(name='legacy_connect')
    split.connect = Mock(name='split_connect')
    db.list_tasks = Mock(return_value=[])
    if request.param != 'split':
        db.connect = legacy_connect
    package.kanban_db = db
    monkeypatch.setitem(sys.modules, 'hermes_cli', package)
    monkeypatch.setitem(sys.modules, 'hermes_cli.kanban_db', db)
    monkeypatch.setitem(sys.modules, 'hermes_cli.kanban_db_connect',
                        None if request.param == 'legacy' else split)
    # execute() prepends the selected repo; restore the path after each test.
    monkeypatch.setattr(sys, 'path', sys.path[:])
    selected = split.connect if request.param == 'split' else legacy_connect
    unused = legacy_connect if request.param == 'split' else split.connect
    return db, selected, unused


def test_execute_selects_connect_and_keeps_explicit_path(fake_hermes, tmp_path):
    db, connect, unused = fake_hermes
    payload = {'repo': str(tmp_path), 'run_root': str(tmp_path / 'run'), 'operation': 'rows'}

    assert kanban_child.execute(payload) == []

    connect.assert_called_once_with((tmp_path / 'run').resolve() / 'kanban.db')
    db.list_tasks.assert_called_once_with(connect.return_value, include_archived=True)
    connect.return_value.close.assert_called_once_with()
    unused.assert_not_called()


def test_connect_errors_stay_inside_child_boundary(fake_hermes, tmp_path, monkeypatch, capsys):
    db, connect, unused = fake_hermes
    connect.side_effect = AttributeError('secret-marker')
    payload = {'repo': str(tmp_path), 'run_root': str(tmp_path / 'run'), 'operation': 'rows'}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))

    kanban_child.main()

    output = capsys.readouterr()
    assert json.loads(output.out) == {'ok': False, 'error': 'NativeOperationError'}
    assert output.err == ''
    connect.assert_called_once_with((tmp_path / 'run').resolve() / 'kanban.db')
    db.list_tasks.assert_not_called()
    unused.assert_not_called()
