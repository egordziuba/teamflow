"""Capture the real observer UI using fictional CSV data, without model credentials.

From the repository root (Python 3.11+):
    python -m pip install playwright
    python -m playwright install chromium
    python scripts/make_screenshots.py

Uses tests/test_workflow.py's FakeBackend with the normal pilot/ledger helpers,
including a controlled bad total followed by repair. The result is TEST_DOUBLE,
never a claim of a live Hermes run. An unchanged copy of teamflow is served with
python -m teamflow.dashboard on 127.0.0.1:8769 in a disposable project under
work/ so existing runs and credentials cannot enter the screenshots.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright
from teamflow.workflow import run_pilot

BASE = 'http://127.0.0.1:8769/'
RUN_ID = 'csv-demo-fictional'


def hashes(root):
    return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def capture(project):
    # Bind only our isolated module copy; never inspect the user's actual runs.
    env = dict(os.environ, PYTHONPATH=str(project), PYTHONDONTWRITEBYTECODE='1')
    with subprocess.Popen([sys.executable, '-m', 'teamflow.dashboard'],
                          cwd=project, env=env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL) as server:
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Dashboard exited; port 8769 may already be in use')
                try:
                    with urllib.request.urlopen(BASE + 'api/health', timeout=1) as response:
                        health = json.load(response)
                    expected_id = hashlib.sha256(str(project).encode()).hexdigest()
                    if health.get('project_id') != expected_id:
                        raise RuntimeError('Port 8769 belongs to another project')
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError('Dashboard did not start')
            errors, external = [], []
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 800},
                                        device_scale_factor=1, timezone_id='UTC')
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: external.append(request.url)
                        if not request.url.startswith(BASE) else None)
                page.goto(BASE, wait_until='networkidle')
                expect(page.locator('.run-button')).to_have_count(1)
                expect(page.locator('.hero')).to_contain_text('Тестовые ответы')
                expect(page.locator('.hero')).to_contain_text('Результат принят')
                expect(page.locator('.step')).to_have_count(7)
                expect(page.locator('.flow')).to_contain_text('Вернул на исправление')
                out = ROOT / 'docs' / 'img'
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / 'dashboard-overview.png'), full_page=True)
                page.locator('[data-focus-key="evidence"]').click()
                expect(page.locator('.evidence-summary')).to_contain_text('Проверка выполнена')
                page.locator('.artifact').scroll_into_view_if_needed()
                page.screenshot(path=str(out / 'dashboard-evidence.png'))
                browser.close()
            if errors or external:
                raise RuntimeError('Capture had browser errors or external requests')
            for name in ('dashboard-overview.png', 'dashboard-evidence.png'):
                size = (out / name).stat().st_size
                if size > 300_000:
                    raise RuntimeError(f'{name} exceeds 300 kB')
                print(f'docs/img/{name}: {size:,} bytes')
        finally:
            server.terminate()
            server.wait(timeout=10)


def main():
    work = ROOT / 'work'
    work.mkdir(exist_ok=True)
    fixture = runpy.run_path(str(ROOT / 'tests' / 'test_workflow.py'))
    with tempfile.TemporaryDirectory(prefix='screenshots-', dir=work) as directory:
        project = Path(directory).resolve()
        shutil.copytree(ROOT / 'teamflow', project / 'teamflow',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        run_root = project / 'runs' / RUN_ID
        source = (ROOT / 'examples' / 'transactions.csv').read_text(encoding='utf-8')
        result = run_pilot(run_root, source, fixture['FakeBackend'](), inject_fault=True)
        assert result['mode'] == 'TEST_DOUBLE'
        assert [attempt['accepted'] for attempt in result['attempts']] == [False, True]
        before = hashes(run_root)
        capture(project)
        assert before == hashes(run_root), 'Observer changed fictional run files'
    print('Fictional fixture only; no Hermes/model calls. Viewport: 1280x800.')


if __name__ == '__main__':
    main()
