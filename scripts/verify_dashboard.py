"""Real-browser read-only QA. Never invokes a model or operation endpoint."""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports' / 'dashboard-qa'


def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / 'runs').rglob('*') if p.is_file()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    errors, external, rows = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith('http://127.0.0.1:8769/') else None)
        page.goto('http://127.0.0.1:8769/', wait_until='networkidle')
        for run_id in ['website-design-recheck', 'website-design-live', 'website-live', 'first-live']:
            expect(page.locator('[data-run-id="' + run_id + '"]')).to_be_visible()
        page.locator('[data-run-id="website-design-recheck"]').click()
        expect(page.locator('.hero')).to_contain_text('Заблокировано')
        expect(page.locator('.step.failed')).to_contain_text('Дизайнер')
        expect(page.locator('.step.planned')).to_contain_text('Ещё не запускался')
        for width, height in [(1440, 1000), (900, 1000), (480, 1000), (1920, 1080)]:
            page.set_viewport_size({'width': width, 'height': height})
            overflow = page.evaluate('Math.max(0, document.documentElement.scrollWidth - innerWidth)')
            assert overflow == 0, (width, overflow)
            path = OUT / f'blocked-{width}.png'
            page.screenshot(path=str(path), full_page=True)
            rows.append({'state': 'blocked', 'width': width, 'height': height, 'horizontal_overflow': overflow, 'screenshot': str(path)})
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('[data-run-id="first-live"]').click()
        expect(page.locator('.hero')).to_contain_text('Результат принят')
        expect(page.locator('.step')).to_have_count(7)
        expect(page.locator('.flow')).to_contain_text('Вернул на исправление')
        page.locator('[data-focus-key="evidence"]').click()
        expect(page.locator('.evidence-summary')).to_contain_text('Проверка выполнена')
        page.locator('#refresh').click()
        expect(page.locator('[data-run-id="first-live"]')).to_have_attribute('aria-current', 'true')
        expect(page.locator('details[open]')).to_have_count(1)
        page.screenshot(path=str(OUT / 'accepted-1440.png'), full_page=True)
        page.locator('[data-run-id="website-live"]').click()
        expect(page.locator('.hero')).to_contain_text('Черновики готовы к проверке')
        expect(page.locator('.step')).to_have_count(3)
        page.screenshot(path=str(OUT / 'drafts-1440.png'), full_page=True)
        # A failed refresh retains prior data and displays a disconnected warning.
        page.route('**/api/snapshot', lambda route: route.abort())
        page.locator('#refresh').click()
        expect(page.locator('#connection-state')).to_contain_text('Нет связи')
        expect(page.locator('.hero')).to_contain_text('Черновики готовы к проверке')
        expect(page.locator('#notice')).to_be_visible()
        page.screenshot(path=str(OUT / 'disconnected-1440.png'), full_page=True)
        page.unroute('**/api/snapshot')
        page.locator('#refresh').click()
        expect(page.locator('#connection-state')).to_contain_text('Связь с журналом установлена')
        browser.close()
    assert not errors, errors
    assert not external, external
    assert before == source_hashes(), 'UI changed source run files'
    result = {'status': 'PASS', 'browser': 'Playwright Chromium', 'views': rows,
              'page_errors': errors, 'external_requests': external,
              'run_files_unchanged': len(before), 'selection_refresh_preserved': True,
              'disconnect_retains_snapshot': True,
              'ui_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'teamflow' / 'ui').glob('*') if p.is_file()}}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
