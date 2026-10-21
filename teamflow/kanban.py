"""Credential-free subprocess boundary to the installed native Hermes board."""
import json
import os
from pathlib import Path
import subprocess


class KanbanError(RuntimeError):
    """Only a fixed error class crosses the subprocess boundary."""


class NativeBoard:
    def __init__(self, hermes_repo: Path, runtime_home: Path, run_root: Path):
        self.hermes_repo = Path(hermes_repo).resolve()
        self.runtime_home = Path(runtime_home).resolve()
        self.run_root = Path(run_root).resolve()
        protected = [Path.home() / '.hermes', Path.home() / 'AppData/Local/hermes']
        if os.environ.get('HERMES_HOME'):
            protected.append(Path(os.environ['HERMES_HOME']).resolve())
        for target in (self.runtime_home, self.run_root):
            if any(target == path.resolve() or target.is_relative_to(path.resolve() / 'profiles')
                   for path in protected) or target.is_relative_to(self.hermes_repo):
                raise KanbanError('UnsafeRuntimePath')
        self.python = self.hermes_repo / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.runtime_home.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)

    def _environment(self):
        allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}
        env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
        env['HERMES_HOME'] = str(self.runtime_home)
        env['HOME'] = env['USERPROFILE'] = str(self.runtime_home)
        env['APPDATA'] = env['LOCALAPPDATA'] = str(self.runtime_home)
        return env

    def _call(self, operation, **arguments):
        payload = {'operation': operation, 'repo': str(self.hermes_repo),
                   'run_root': str(self.run_root), **arguments}
        try:
            process = subprocess.run(
                [str(self.python), '-I', str(Path(__file__).with_name('kanban_child.py'))],
                input=json.dumps(payload, ensure_ascii=True, allow_nan=False),
                text=True, encoding='utf-8', capture_output=True, shell=False,
                cwd=self.runtime_home, env=self._environment(), timeout=60,
            )
            envelope = json.loads(process.stdout)
            if process.returncode or not envelope.get('ok'):
                raise KanbanError('NativeOperationError')
            return envelope['result']
        except KanbanError:
            raise
        except Exception:
            raise KanbanError('NativeTransportError') from None

    def start(self, ticket_id: int, role: str, request: dict) -> dict:
        return self._call('start', ticket_id=ticket_id, role=role, request=request)

    def finish(self, handle: dict, response: dict):
        return self._call('finish', handle=handle, response=response)

    def fail(self, handle: dict, reason: str):
        return self._call('fail', handle=handle, reason=reason)

    def rows(self) -> list:
        return self._call('rows')
