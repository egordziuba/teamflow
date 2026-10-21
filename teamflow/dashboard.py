"""Local, read-only observation server. No execution or mutation endpoints."""
import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .observation import snapshot

PROJECT = Path(__file__).resolve().parents[1]
UI = Path(__file__).resolve().parent / 'ui'
SERVICE = 'hermes-project-team-observer-v1'
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.css': ('app.css', 'text/css; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/ui-model.js': ('ui-model.js', 'text/javascript; charset=utf-8')}


def identity(project):
    return hashlib.sha256(str(Path(project).resolve()).encode('utf-8')).hexdigest()


def create_server(project=PROJECT, *, port=8769):
    project = Path(project).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'TeamflowObserver/1'
        sys_version = ''

        def log_message(self, *args):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            if self.command != 'HEAD':
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_GET(self):
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in allowed:
                return self.send(403, b'{"error":"invalid_host"}')
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + host for host in allowed}:
                return self.send(403, b'{"error":"cross_origin_forbidden"}')
            path = urlsplit(self.path).path
            if path == '/api/health':
                value = {'service': SERVICE, 'project_id': identity(project), 'read_only': True}
                return self.send(200, json.dumps(value).encode('utf-8'))
            if path == '/api/snapshot':
                try:
                    value = snapshot(project)
                    return self.send(200, json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
                except Exception:
                    return self.send(503, b'{"error":"snapshot_unavailable"}')
            if path in ASSETS:
                filename, mime = ASSETS[path]
                target = UI / filename
                if target.is_file() and not target.is_symlink():
                    return self.send(200, target.read_bytes(), mime)
                return self.send(503, b'{"error":"ui_not_available"}')
            return self.send(404, b'{"error":"not_found"}')

        do_HEAD = do_GET

        def mutation_forbidden(self):
            self.send(405, b'{"error":"read_only"}')

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = mutation_forbidden

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='Панель наблюдения Teamflow: только локальное чтение журналов.')
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--open', action='store_true', help='Открыть панель в браузере')
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    url = f'http://127.0.0.1:{args.port}/'
    try:
        server = create_server(port=args.port)
    except OSError:
        import urllib.request
        try:
            with urllib.request.urlopen(url + 'api/health', timeout=2) as response:
                health = json.load(response)
            if health.get('service') != SERVICE or health.get('project_id') != identity(PROJECT):
                raise ValueError('different service')
        except Exception:
            print('Порт занят другим сервисом. Панель не запущена.')
            return 2
        print('Панель уже работает: ' + url)
        if args.open:
            import webbrowser
            webbrowser.open(url)
        return 0
    print('Teamflow · только наблюдение · ' + url, flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
