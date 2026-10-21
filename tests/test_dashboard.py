import importlib.util
import json
import threading
import urllib.error
import urllib.request


def test_local_api_is_empty_readonly_and_rejects_mutations(tmp_path):
    assert importlib.util.find_spec('teamflow.dashboard'), 'Local observation server missing'
    from teamflow.dashboard import create_server
    server = create_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    try:
        with urllib.request.urlopen(base + '/api/snapshot') as response:
            value = json.load(response)
            assert value['read_only'] is True and value['runs'] == []
            assert "default-src 'self'" in response.headers['Content-Security-Policy']
            assert response.headers['Cache-Control'] == 'no-store'
        for method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            request = urllib.request.Request(base + '/api/snapshot', data=b'{}', method=method)
            try:
                urllib.request.urlopen(request)
                assert False, 'Mutation route accepted'
            except urllib.error.HTTPError as error:
                assert error.code == 405
        for route in ['/../.runtime/hermes/auth.json', '/.runtime/hermes/auth.json', '/api/run']:
            try:
                urllib.request.urlopen(base + route)
                assert False, 'Arbitrary file or command route accepted'
            except urllib.error.HTTPError as error:
                assert error.code == 404
        request = urllib.request.Request(base + '/api/snapshot', headers={'Origin': 'https://evil.example'})
        try:
            urllib.request.urlopen(request)
            assert False, 'Cross-origin request accepted'
        except urllib.error.HTTPError as error:
            assert error.code == 403
        assert list(tmp_path.iterdir()) == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
