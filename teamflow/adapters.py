"""Hermes subprocess and board boundaries. Never silently replace failed live calls."""
import json


def parse_object(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('Non-finite JSON constant: ' + value)

    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    if type(result) is not dict:
        raise ValueError('Expected a JSON object')
    return result


class HermesBackend:
    live = True

    def __init__(self, project, hermes_repo, model='gpt-6-astra', timeout=None, receipts=None, streaming=False):
        from pathlib import Path
        self.project = Path(project).resolve()
        self.repo = Path(hermes_repo).resolve()
        self.model = model
        self.timeout = timeout
        self.receipts = Path(receipts) if receipts else None
        if type(streaming) is not bool:
            raise ValueError('invalid_streaming_flag')
        self.streaming = streaming

    def call_timeout(self, role):
        return self.timeout if self.timeout is not None else (360 if role == 'designer' else 180)

    def _invoke(self, role, request, action):
        import subprocess
        import uuid
        from pathlib import Path
        from .runtime import clean_env, runtime_python, PACKAGE_ROOT, inspect_runtime
        from .roles import ROLE_IDS
        if role not in ROLE_IDS:
            raise ValueError('invalid_role')
        report = inspect_runtime(self.project, [role], self.model)
        if not report['profiles_ok']:
            raise ValueError('profile_preflight_failed')
        home = Path(report['runtime_home']) / 'profiles' / role
        if action == 'call' and not (report['auth_present'] or (home / 'auth.json').is_file()):
            raise ValueError('auth_required')
        payload = {'role': role, 'request': request, 'model': self.model, 'provider': 'openai-codex',
                   'profile_home': str(home), 'hermes_repo': str(self.repo), 'action': action,
                   'streaming': self.streaming, 'call_id': uuid.uuid4().hex,
                   'system': (PACKAGE_ROOT / 'roles' / (role + '.md')).read_text(encoding='utf-8')}
        env = clean_env(home)
        env['PYTHONPATH'] = str(PACKAGE_ROOT)
        try:
            proc = subprocess.run([str(runtime_python(self.repo)), '-m', 'teamflow.hermes_child'],
                                  input=json.dumps(payload, ensure_ascii=False), text=True, encoding='utf-8',
                                  capture_output=True, cwd=home, env=env, timeout=self.call_timeout(role))
        except subprocess.TimeoutExpired as exc:
            raise ValueError('model_timeout_outcome_unknown') from exc
        try:
            envelope = parse_object(proc.stdout)
        except ValueError as exc:
            raise ValueError('invalid_hermes_envelope') from exc
        if proc.returncode or envelope.get('error'):
            code = envelope.get('error', 'hermes_process_failed')
            if code not in {'auth_required', 'profile_preflight_failed', 'tools_not_empty',
                            'invalid_model_json', 'hermes_runtime_error', 'invalid_request'}:
                code = 'hermes_process_failed:' + str(envelope.get('error_type', 'unknown'))
            raise ValueError(code)
        if envelope.get('tool_count') != 0 or type(envelope.get('tool_count')) is not int:
            raise ValueError('tools_not_empty')
        if action == 'call':
            if type(envelope.get('response')) is not dict:
                raise ValueError('invalid_model_json')
            if self.receipts:
                self.receipts.mkdir(parents=True, exist_ok=True)
                (self.receipts / (role + '-' + uuid.uuid4().hex + '.json')).write_text(
                    json.dumps(envelope, ensure_ascii=False, indent=2), encoding='utf-8')
        return envelope

    def preflight(self, role='analyst'):
        return self._invoke(role, {}, 'preflight')

    def fingerprint(self):
        import hashlib
        from .runtime import PACKAGE_ROOT, secure_config
        from .roles import ROLE_IDS
        from .ledger import canonical_hash
        result = {'kind': 'live-hermes', 'model': self.model, 'provider': 'openai-codex',
                'config_sha256': canonical_hash(secure_config(self.model)),
                'role_configs': {role: canonical_hash(secure_config(self.model, role=role)) for role in ROLE_IDS},
                'prompts': {role: hashlib.sha256((PACKAGE_ROOT / 'roles' / (role + '.md')).read_bytes()).hexdigest()
                            for role in ROLE_IDS}}
        if self.streaming:
            result['transport'] = 'stream-consumer-v1'
        return result

    def call(self, role, request):
        return self._invoke(role, request, 'call')['response']
