"""Model-only Hermes child. Its stdout is a single JSON envelope, never raw provider logs."""
import json
import sys
from .adapters import parse_object

from .roles import ROLE_IDS
ROLES = set(ROLE_IDS)


def validate_request(data):
    fields = {'role', 'request', 'model', 'provider', 'profile_home', 'hermes_repo', 'system'}
    import re
    if (not fields.issubset(data) or set(data) - fields - {'action', 'streaming', 'call_id'}
            or data.get('role') not in ROLES or type(data.get('request')) is not dict
            or any(type(data.get(key)) is not str or not data[key].strip() for key in fields - {'request'})
            or type(data.get('streaming', False)) is not bool
            or ('call_id' in data and (type(data['call_id']) is not str or not re.fullmatch(r'[a-f0-9]{32}', data['call_id'])))
            or data.get('action', 'call') not in {'call', 'preflight'}):
        raise ValueError('invalid_request')


def run_agent_call(factory, runtime, data, progress_sink=None):
    import time
    started = time.monotonic()
    metrics = {'streaming': bool(data.get('streaming', False)), 'phase': 'starting',
               'stream_chunks': 0, 'stream_chars': 0, 'first_delta_seconds': None,
               'last_delta_seconds': None, 'elapsed_seconds': 0.0}
    last_saved = -1.0
    def publish(phase, force=False):
        nonlocal last_saved
        elapsed = round(time.monotonic() - started, 3)
        metrics.update(phase=phase, elapsed_seconds=elapsed)
        if progress_sink is not None and (force or elapsed - last_saved >= 0.5):
            progress_sink(dict(metrics))
            last_saved = elapsed
    def on_delta(delta):
        if type(delta) is not str or not delta:
            return
        elapsed = round(time.monotonic() - started, 3)
        metrics['stream_chunks'] += 1
        metrics['stream_chars'] += len(delta)
        metrics['last_delta_seconds'] = elapsed
        if metrics['first_delta_seconds'] is None:
            metrics['first_delta_seconds'] = elapsed
        publish('streaming')
    params = {key: runtime[key] for key in ['provider', 'base_url', 'api_key', 'api_mode'] if key in runtime}
    agent = factory(**params, model=data['model'], max_iterations=2, enabled_toolsets=[],
                    skip_context_files=True, skip_memory=True, load_soul_identity=False,
                    quiet_mode=True, save_trajectories=False, max_tokens=5000,
                    reasoning_config={'effort': 'medium'},
                    ephemeral_system_prompt=data['system'])
    if agent.tools:
        raise ValueError('tools_not_empty')
    publish('waiting', force=True)
    kwargs = {'stream_callback': on_delta} if data.get('streaming', False) else {}
    try:
        result = agent.run_conversation(user_message=json.dumps(data['request'], ensure_ascii=False),
                                        system_message=data['system'], **kwargs)
        if result.get('error'):
            raise ValueError('hermes_runtime_error')
        response = parse_object(result.get('final_response', ''))
        if any(m.get('tool_calls') for m in result.get('messages', []) if isinstance(m, dict)):
            raise ValueError('unexpected_tool_call')
    except Exception:
        publish('error', force=True)
        raise
    publish('completed', force=True)
    return {'response': response, 'tool_count': 0, 'telemetry': dict(metrics),
            'session_id': str(getattr(agent, 'session_id', '')),
            'model': data['model'], 'provider': data['provider']}


def progress_sink(home, call_id):
    import os
    import re
    import tempfile
    from pathlib import Path
    if type(call_id) is not str or not re.fullmatch(r'[a-f0-9]{32}', call_id):
        raise ValueError('invalid_call_id')
    directory = Path(home) / 'telemetry'
    if directory.resolve() != directory.absolute():
        raise ValueError('redirected_telemetry')
    directory.mkdir(exist_ok=True)
    target = directory / (call_id + '.json')
    fields = {'streaming', 'phase', 'stream_chunks', 'stream_chars', 'first_delta_seconds', 'last_delta_seconds', 'elapsed_seconds'}
    def persist(value):
        if type(value) is not dict or set(value) != fields:
            raise ValueError('invalid_telemetry_fields')
        encoded = json.dumps(value, allow_nan=False)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix=call_id, suffix='.tmp', delete=False) as f:
            f.write(encoded)
            temp = f.name
        try:
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return persist


def main():
    try:
        data = parse_object(sys.stdin.read())
        validate_request(data)
    except Exception:
        print(json.dumps({'error': 'invalid_request'}))
        return 2
    import contextlib
    import os
    from pathlib import Path
    try:
        home = Path(data['profile_home']).resolve()
        if home.parent.name != 'profiles' or home.name != data['role']:
            raise ValueError('profile_preflight_failed')
        project = home.parents[3]
        from .runtime import inspect_runtime, PACKAGE_ROOT
        report = inspect_runtime(project, [data['role']], data['model'])
        if (not report['profiles_ok'] or str(home) != os.environ.get('HERMES_HOME')
                or 'HERMES_KANBAN_TASK' in os.environ or data['provider'] != 'openai-codex'
                or home.parent.parent != Path(report['runtime_home'])
                or data['system'] != (PACKAGE_ROOT / 'roles' / (data['role'] + '.md')).read_text(encoding='utf-8')):
            raise ValueError('profile_preflight_failed')
        sys.path.insert(0, data['hermes_repo'])
        with open(os.devnull, 'w', encoding='utf-8') as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            from model_tools import get_tool_definitions
            tools = get_tool_definitions(enabled_toolsets=[], quiet_mode=True)
            if tools:
                raise ValueError('tools_not_empty')
            auth_present = report['auth_present'] or (home / 'auth.json').is_file()
            if data.get('action') == 'preflight':
                envelope = {'tool_count': 0, 'auth_present': auth_present,
                            'role': data['role'], 'profile_home': str(home), 'model_called': False}
            else:
                if not auth_present:
                    raise ValueError('auth_required')
                from hermes_cli.runtime_provider import resolve_runtime_provider
                from run_agent import AIAgent
                runtime = resolve_runtime_provider(requested=data['provider'], target_model=data['model'])
                import uuid
                call_id = data.get('call_id', uuid.uuid4().hex)
                envelope = run_agent_call(AIAgent, runtime, data, progress_sink=progress_sink(home, call_id))
                envelope['call_id'] = call_id
        print(json.dumps(envelope, ensure_ascii=False))
        return 0
    except Exception as exc:
        code = str(exc) if str(exc) in {'auth_required', 'profile_preflight_failed', 'tools_not_empty',
                                       'invalid_model_json', 'hermes_runtime_error'} else 'hermes_process_failed'
        print(json.dumps({'error': code, 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
