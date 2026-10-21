"""CLI contracts exercised in subprocesses, never with live authentication/models."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    target = tmp_path / 'project'
    shutil.copytree(ROOT / 'teamflow', target / 'teamflow', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('roles', 'examples'):
        shutil.copytree(ROOT / name, target / name)
    return target


def cli(project, *args):
    env = dict(os.environ, PYTHONPATH=str(project), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return subprocess.run([sys.executable, '-m', 'teamflow', *args], cwd=project.parent,
                          env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)


def test_help_lists_user_commands(project):
    result = cli(project, '--help')
    assert result.returncode == 0, result.stderr
    for command in ('prepare', 'doctor', 'roles', 'pilot', 'specialists', 'status', 'auth'):
        assert command in result.stdout
    assert not (project / '.runtime').exists()


@pytest.mark.parametrize('name', ['../escape', 'a/b', 'UPPER', '.', 'a' * 65, 'bad_name'])
def test_invalid_slug_rejected_before_writes(project, name):
    result = cli(project, 'pilot', '--run', name)
    assert result.returncode == 2
    assert 'safe run name' in result.stderr
    assert not (project / 'runs').exists()
    assert not (project / '.runtime').exists()


def test_status_missing_is_read_only(project):
    result = cli(project, 'status', '--run', 'missing')
    assert result.returncode == 2
    assert json.loads(result.stdout)['error'] == 'run_not_found'
    assert not (project / 'runs').exists()
    assert not (project / '.runtime').exists()


@pytest.mark.parametrize('command,extra', [('pilot', []), ('specialists', ['--brief', 'absent.json'])])
def test_model_commands_require_isolated_auth_before_any_writes(project, command, extra):
    result = cli(project, command, '--run', 'no-auth', *extra)
    assert result.returncode == 2
    assert json.loads(result.stdout)['error'] == 'auth_required'
    assert not (project / 'runs').exists()
    assert not (project / '.runtime').exists()


def test_status_never_promotes_unverified_recorded_acceptance(project):
    root = project / 'runs' / 'recorded'
    root.mkdir(parents=True)
    (root / 'result.json').write_text('{"status":"ACCEPTED"}', encoding='utf-8')
    before = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
    result = cli(project, 'status', '--run', 'recorded')
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['recorded_status'] == 'ACCEPTED'
    assert value['verified'] is False
    assert value.get('status') != 'ACCEPTED'
    assert before == sorted(str(p.relative_to(root)) for p in root.rglob('*'))


def isolated_dispatch(project, args, setup):
    script = (
        'import sys, runpy, json\nfrom pathlib import Path\n'
        'import teamflow.runtime as runtime\n' + setup + '\n'
        + 'sys.argv = ["teamflow"] + ' + repr(args) + '\n'
        + 'runpy.run_module("teamflow", run_name="__main__")\n'
    )
    return subprocess.run([sys.executable, '-c', script], cwd=project,
                          capture_output=True, text=True, encoding='utf-8', timeout=30)


@pytest.mark.parametrize('engine', [False, True])
def test_doctor_read_only_and_engine_uses_preflight(project, engine):
    setup = '''
runtime.inspect_runtime = lambda project, **kw: dict(profiles_ok=True, auth_present=False, checked_model=kw['model'])
runtime.find_install = lambda: Path('hermes-test')
import teamflow.adapters as adapters
class Backend:
    def __init__(self, project, repo, **kw): pass
    def preflight(self): return dict(tool_count=0, auth_present=False, model_called=False)
    def call(self, *a): raise AssertionError('model forbidden')
adapters.HermesBackend = Backend
'''
    result = isolated_dispatch(project, ['--model', 'test-model', 'doctor'] + (['--engine'] if engine else []), setup)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['checked_model'] == 'test-model'
    if engine:
        assert report['engine']['model_called'] is False
    assert not (project / '.runtime').exists()


def test_prepare_delegates_without_authentication(project):
    setup = '''
runtime.find_install = lambda: Path('hermes-test')
def prepare(project, repo, **kw):
    assert project == runtime.PACKAGE_ROOT
    assert kw['model'] == 'test-model'
    return project / '.runtime' / 'hermes'
runtime.prepare_runtime = prepare
'''
    result = isolated_dispatch(project, ['--model', 'test-model', 'prepare'], setup)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'prepared'


def test_auth_only_explicit_command_launches_native_isolated_cli(project):
    setup = '''
runtime.find_install = lambda: Path('hermes-test')
runtime.runtime_python = lambda repo: Path('native-python')
import subprocess
def launch(command, **kw):
    assert command == ['native-python', '-m', 'hermes_cli.main', 'auth', 'add', 'openai-codex']
    assert kw['env']['HERMES_HOME'] == str(runtime.PACKAGE_ROOT / '.runtime' / 'hermes')
    assert kw['cwd'] == Path('hermes-test')
    print('NATIVE_AUTH_EXPLICIT')
    return subprocess.CompletedProcess(command, 0)
subprocess.run = launch
'''
    result = isolated_dispatch(project, ['auth'], setup)
    assert result.returncode == 0, result.stderr
    assert 'NATIVE_AUTH_EXPLICIT' in result.stdout


@pytest.mark.parametrize('command', ['pilot', 'specialists'])
def test_authenticated_dispatch_uses_native_board_and_receipts(project, command):
    setup = '''
runtime.inspect_runtime = lambda project, **kw: dict(profiles_ok=True, auth_present=True)
runtime.find_install = lambda: Path('hermes-test')
import teamflow.adapters as adapters
import teamflow.kanban as kanban
import teamflow.workflow as workflow
import types
specialists = types.ModuleType('teamflow.specialists')
sys.modules['teamflow.specialists'] = specialists
class Backend:
    def __init__(self, project, repo, **kw):
        assert project == runtime.PACKAGE_ROOT
        assert kw['receipts'] == project / 'runs' / 'demo' / 'receipts'
        assert kw['model'] == 'gpt-6-astra'
adapters.HermesBackend = Backend
class Board:
    def __init__(self, repo, home, root):
        assert home == runtime.PACKAGE_ROOT / '.runtime' / 'hermes'
        assert root == runtime.PACKAGE_ROOT / 'runs' / 'demo'
kanban.NativeBoard = Board
def pilot(root, source, backend, **kw):
    assert isinstance(source, str) and 'EUR' in source
    assert kw['inject_fault'] is True
    assert isinstance(kw['board'], Board)
    return {'status': 'TEST_ONLY'}
def specialist(root, brief, backend, **kw):
    assert brief['project_type'] == 'website'
    assert isinstance(kw['board'], Board)
    return {'status': 'DRAFTS_REQUIRE_REVIEW'}
workflow.run_pilot = pilot
specialists.run_specialists = specialist
'''
    brief = project / 'brief.json'
    brief.write_text('{"project_type":"website"}', encoding='utf-8')
    extra = ['--inject-fault'] if command == 'pilot' else ['--brief', str(brief)]
    result = isolated_dispatch(project, [command, '--run', 'demo', *extra], setup)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == ('TEST_ONLY' if command == 'pilot' else 'DRAFTS_REQUIRE_REVIEW')


def test_invalid_roles_returns_json_error(project):
    result = cli(project, 'roles', '--project-type', 'unknown')
    assert result.returncode == 2
    assert json.loads(result.stdout)['error'] == 'operation_failed'
    assert 'Traceback' not in result.stderr


def test_launchers_are_explicit_and_website_example_is_fictional():
    launch = (ROOT / 'Launch.cmd').read_text(encoding='utf-8').lower()
    auth = (ROOT / 'Authenticate.cmd').read_text(encoding='utf-8').lower()
    assert 'cd /d "%~dp0"' in launch and 'cd /d "%~dp0"' in auth
    assert '-m teamflow --help' in launch and 'pause' in launch
    assert '-m teamflow auth' in auth and 'pause' in auth
    assert '-m teamflow auth' not in launch
    brief = json.loads((ROOT / 'examples' / 'website-brief.json').read_text(encoding='utf-8'))
    assert brief['project_type'] == 'website'
    assert brief['sources'] and brief['acceptance'] and brief['goal']
    assert 'http' not in json.dumps(brief)


def test_roles_filter_is_metadata_not_activation(project):
    result = cli(project, 'roles', '--project-type', 'website')
    assert result.returncode == 0, result.stderr
    roles = json.loads(result.stdout)
    assert 'designer' in roles and 'coordinator' in roles
    assert 'data-specialist' not in roles
    assert not (project / '.runtime').exists()
