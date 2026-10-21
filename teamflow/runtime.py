"""Explicit process isolation; never clone or import the main profile's credentials."""
import os
from pathlib import Path

OS_ENV = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'PATHEXT',
          'SYSTEMDRIVE', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA',
          'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}


def clean_env(home: Path, source=None):
    home = Path(home).resolve()
    source = os.environ if source is None else source
    env = {key: value for key, value in source.items() if key.upper() in OS_ENV}
    env.update({'HERMES_HOME': str(home), 'CODEX_HOME': str(home / 'isolated-codex'),
                'HOME': str(home), 'USERPROFILE': str(home),
                'LOCALAPPDATA': str(home / 'appdata'), 'APPDATA': str(home / 'appdata'),
                'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONNOUSERSITE': '1'})
    return env


DEFAULT_MODEL = 'gpt-6-astra'
PROVIDER = 'openai-codex'
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def find_install():
    import shutil
    executable = shutil.which('hermes')
    if not executable:
        raise ValueError('Hermes executable not found')
    repo = Path(executable).resolve().parents[2]
    if not (repo / 'run_agent.py').is_file():
        raise ValueError('Installed Hermes source root not found')
    return repo


def runtime_python(repo):
    candidates = [Path(repo) / 'venv' / 'Scripts' / 'python.exe', Path(repo) / 'venv' / 'bin' / 'python',
                  Path(repo) / '.venv' / 'bin' / 'python']
    for path in candidates:
        if path.is_file():
            return path
    raise ValueError('Hermes interpreter not found')


def secure_config(model=DEFAULT_MODEL, role=None):
    config = {'model': {'default': model, 'provider': PROVIDER},
            'platform_toolsets': {'cli': []}, 'mcp_servers': {}, 'plugins': {'enabled': []},
            'hooks': {}, 'approvals': {'mode': 'manual'},
            'memory': {'memory_enabled': False, 'user_profile_enabled': False},
            'compression': {'enabled': False}, 'curator': {'enabled': False},
            'kanban': {'dispatch_in_gateway': False}, 'auth': {'adopt_external_logins': False},
            'agent': {'max_turns': 2, 'tool_use_enforcement': False},
            'security': {'redact_secrets': True}}
    if role == 'designer':
        config['providers'] = {PROVIDER: {'stale_timeout_seconds': 300, 'request_timeout_seconds': 300}}
    return config


def _write_owned(path, value, new=False):
    import json
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    if path.exists() and not new:
        if path.read_text(encoding='utf-8') != text:
            raise ValueError('Managed configuration changed: ' + path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _home(project):
    project = Path(project).resolve()
    home = project / '.runtime' / 'hermes'
    if home.resolve() != home or not home.resolve().is_relative_to(project):
        raise ValueError('Runtime path is redirected')
    return home


def prepare_runtime(project, repo, *, role_ids=None, model=DEFAULT_MODEL):
    import subprocess
    from .roles import ROLE_IDS, catalog
    selected = list(ROLE_IDS if role_ids is None else role_ids)
    if any(role not in ROLE_IDS for role in selected) or len(set(selected)) != len(selected):
        raise ValueError('Invalid bootstrap role selection')
    home = _home(project)
    marker = home / 'teamflow.runtime.json'
    if home.exists() and not marker.exists():
        raise ValueError('Refusing to overwrite an unmanaged Hermes home')
    home.mkdir(parents=True, exist_ok=True)
    _write_owned(marker, {'owner': 'hermes-project-team', 'version': 1})
    _write_owned(home / 'config.yaml', secure_config(model))
    cli = Path(repo) / 'venv' / 'Scripts' / 'hermes.exe'
    if not cli.exists():
        cli = Path(repo) / 'venv' / 'bin' / 'hermes'
    for role in selected:
        profile = home / 'profiles' / role
        is_new = not profile.exists()
        if not is_new and not (profile / 'teamflow.profile.json').exists():
            raise ValueError('Refusing unmanaged profile: ' + role)
        if is_new:
            proc = subprocess.run([str(cli), 'profile', 'create', role, '--no-alias', '--no-skills',
                                   '--description', catalog()[role]['description']],
                                  env=clean_env(home), cwd=home, capture_output=True, timeout=60)
            if proc.returncode:
                raise ValueError('Profile creation failed for ' + role)
        if profile.resolve() != profile:
            raise ValueError('Profile path redirected')
        _write_owned(profile / 'config.yaml', secure_config(model, role=role), new=is_new)
        prompt = (PACKAGE_ROOT / 'roles' / (role + '.md')).read_text(encoding='utf-8')
        if not is_new and (profile / 'SOUL.md').read_text(encoding='utf-8') != prompt:
            raise ValueError('Role instructions changed: ' + role)
        if is_new:
            (profile / 'SOUL.md').write_text(prompt, encoding='utf-8')
        _write_owned(profile / 'teamflow.profile.json', {'owner': 'hermes-project-team', 'role': role})
    return home


def inspect_runtime(project, role_ids=None, model=DEFAULT_MODEL):
    import json
    from .roles import ROLE_IDS
    home = _home(project)
    selected = list(ROLE_IDS if role_ids is None else role_ids)
    report = {'runtime_home': str(home), 'profiles_ok': True, 'roles': {},
              'auth_present': (home / 'auth.json').is_file()}
    try:
        root_ok = (json.loads((home / 'config.yaml').read_text(encoding='utf-8')) == secure_config(model)
                   and json.loads((home / 'teamflow.runtime.json').read_text(encoding='utf-8')) == {'owner': 'hermes-project-team', 'version': 1}
                   and not any((home / 'plugins').glob('*')))
        if (home / '.env').exists():
            root_ok = root_ok and not any(x.strip() and not x.lstrip().startswith('#')
                                          for x in (home / '.env').read_text(encoding='utf-8').splitlines())
    except (OSError, ValueError):
        root_ok = False
    report['profiles_ok'] = bool(root_ok)
    for role in selected:
        okay = role in ROLE_IDS
        profile = home / 'profiles' / role
        try:
            okay = okay and profile.resolve() == profile
            okay = okay and json.loads((profile / 'config.yaml').read_text(encoding='utf-8')) == secure_config(model, role=role)
            okay = okay and json.loads((profile / 'teamflow.profile.json').read_text(encoding='utf-8')) == {
                'owner': 'hermes-project-team', 'role': role}
            okay = okay and (profile / 'SOUL.md').read_text(encoding='utf-8') == (PACKAGE_ROOT / 'roles' / (role + '.md')).read_text(encoding='utf-8')
            env_lines = (profile / '.env').read_text(encoding='utf-8').splitlines()
            okay = okay and not any((profile / 'plugins').glob('*'))
            okay = okay and not any(line.strip() and not line.lstrip().startswith('#') for line in env_lines)
        except (OSError, ValueError):
            okay = False
        report['roles'][role] = bool(okay)
        report['profiles_ok'] = report['profiles_ok'] and bool(okay)
    return report
