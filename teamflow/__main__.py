"""Explicit, isolated Teamflow command-line entry point."""
import argparse
import json
import re
from pathlib import Path

from .runtime import PACKAGE_ROOT, DEFAULT_MODEL


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None):
    try:
        return dispatch(argv)
    except (ValueError, OSError, RuntimeError) as exc:
        # Do not echo backend exceptions: they may contain sensitive provider output.
        emit({'error': 'operation_failed', 'error_type': type(exc).__name__})
        return 2


def dispatch(argv=None):
    parser = argparse.ArgumentParser(description='Teamflow: local CSV pilot and specialist drafts (no deployment).')
    parser.add_argument('--model', default=DEFAULT_MODEL)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'doctor', 'roles', 'pilot', 'specialists', 'status', 'auth'):
        command = commands.add_parser(name)
        if name == 'pilot':
            command.add_argument('--inject-fault', action='store_true')
        if name == 'doctor':
            command.add_argument('--engine', action='store_true')
        if name == 'roles':
            command.add_argument('--project-type')
        if name == 'specialists':
            command.add_argument('--brief', required=True)
        if name in ('pilot', 'specialists', 'status'):
            command.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    if hasattr(args, 'run'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', args.run):
            parser.error('expected safe run name: [a-z0-9][a-z0-9-]{0,63}')
        root = PACKAGE_ROOT / 'runs' / args.run
        if root.resolve() != root or not root.resolve().is_relative_to(PACKAGE_ROOT):
            parser.error('expected safe run name: redirected path')
    if args.command == 'status' and not root.is_dir():
        emit({'error': 'run_not_found', 'run': args.run, 'verified': False})
        return 2
    if args.command == 'status':
        result_path = root / 'result.json'
        recorded = json.loads(result_path.read_text(encoding='utf-8')) if result_path.is_file() else {}
        emit({'run': args.run, 'recorded_status': recorded.get('status'), 'verified': False,
              'note': 'Recorded metadata only; artifact, source and pending ledger are not verified.'})
        return 0
    if args.command in ('pilot', 'specialists'):
        from .runtime import inspect_runtime
        report = inspect_runtime(PACKAGE_ROOT, model=args.model)
        if not report['auth_present'] or not report['profiles_ok']:
            emit({'error': 'auth_required', 'profiles_ok': report['profiles_ok'],
                  'auth_present': report['auth_present'],
                  'next': 'Run prepare, then explicitly run auth in your terminal.'})
            return 2
        from .runtime import find_install
        from .adapters import HermesBackend
        from .kanban import NativeBoard
        repo = find_install()
        backend = HermesBackend(PACKAGE_ROOT, repo, model=args.model, receipts=root / 'receipts')
        board = NativeBoard(repo, PACKAGE_ROOT / '.runtime' / 'hermes', root)
        if args.command == 'pilot':
            from .workflow import run_pilot
            source = (PACKAGE_ROOT / 'examples' / 'transactions.csv').read_text(encoding='utf-8')
            result = run_pilot(root, source, backend, inject_fault=args.inject_fault, board=board)
        else:
            from .specialists import run_specialists
            brief = json.loads(Path(args.brief).read_text(encoding='utf-8'))
            result = run_specialists(root, brief, backend, board=board)
        emit(result)
        return 0
    if args.command == 'prepare':
        from .runtime import find_install, prepare_runtime
        home = prepare_runtime(PACKAGE_ROOT, find_install(), model=args.model)
        emit({'status': 'prepared', 'runtime_home': str(home), 'model': args.model})
        return 0
    if args.command == 'doctor':
        from .runtime import inspect_runtime, find_install
        report = inspect_runtime(PACKAGE_ROOT, model=args.model)
        if args.engine:
            from .adapters import HermesBackend
            report['engine'] = HermesBackend(PACKAGE_ROOT, find_install(), model=args.model).preflight()
        emit(report)
        return 0
    if args.command == 'auth':
        import subprocess
        from .runtime import find_install, runtime_python, clean_env
        repo = find_install()
        home = PACKAGE_ROOT / '.runtime' / 'hermes'
        return subprocess.run([str(runtime_python(repo)), '-m', 'hermes_cli.main',
                               'auth', 'add', 'openai-codex'],
                              cwd=repo, env=clean_env(home)).returncode
    if args.command == 'roles':
        from .roles import catalog, allowed_specialists, CORE_ROLES
        roles = catalog()
        if args.project_type:
            allowed = set(CORE_ROLES) | set(allowed_specialists(args.project_type))
            roles = {key: value for key, value in roles.items() if key in allowed}
        emit(roles)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
