"""Browser exercises the real read-only server against a clearly test-only producer."""
import threading

import pytest

playwright = pytest.importorskip('playwright.sync_api', reason='Playwright is not installed')
sync_playwright, expect = playwright.sync_playwright, playwright.expect

from teamflow.dashboard import create_server
from teamflow.ledger import RequestLedger


def test_browser_observes_new_steps_without_running_agents(tmp_path):
    root = tmp_path / 'runs' / 'browser-fixture'
    root.mkdir(parents=True)
    ledger = RequestLedger(root / 'execution.sqlite3')
    ticket = ledger.reserve('analyst', {'stage': 'TEST_FIXTURE_NO_MODEL'})
    server = create_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except playwright.Error as error:
                if "Executable doesn't exist at" in str(error):
                    pytest.skip('Playwright Chromium browser is not installed; run playwright install chromium')
                raise
            page = browser.new_page(viewport={'width': 900, 'height': 900})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect(page.locator('.hero')).to_contain_text('Ожидает ответа')
            expect(page.locator('.step')).to_have_count(1)
            ledger.complete(ticket['id'], {'test_fixture': True})
            expect(page.locator('.hero')).to_contain_text('Итог не принят', timeout=10000)
            ledger.reserve('coordinator', {'stage': 'TEST_FIXTURE_NEXT_STEP'})
            expect(page.locator('.step')).to_have_count(2, timeout=10000)
            expect(page.locator('[data-run-id="browser-fixture"]')).to_have_attribute('aria-current', 'true')
            assert len(ledger.rows()) == 2
            assert len(ledger.events()) == 3
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
