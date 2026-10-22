# Hermes Kanban compatibility

## Fix A — implemented

Verified on 2026-10-22 against pinned Hermes commit
`3ab0930318ad970b4ec102838f75f62973e188ec`.

Teamflow's legacy connection API is `hermes_cli.kanban_db.connect`.
The pinned checkout instead defines it in `hermes_cli.kanban_db_connect`:

```python
def connect(db_path: Optional[Path] = None, *, board: Optional[str] = None) -> sqlite3.Connection:
```

`teamflow/kanban_child.py` now selects the available export:

```python
from hermes_cli import kanban_db as db
try:
    connect = db.connect
except AttributeError:
    from hermes_cli.kanban_db_connect import connect
# ...
conn = connect(root / 'kanban.db')
```

The legacy export takes precedence when both are present. Only a missing export
triggers the fallback; exceptions from calling `connect` still reach the existing
child error boundary. The explicit per-run database path, task operations on
`db`, credential isolation, ownership checks, and fixed error envelope
`{"ok": false, "error": "NativeOperationError"}` are unchanged. Prompts, roles,
acceptance rules, and the ledger format are unchanged.

`tests/test_kanban_compat.py` uses small fake modules without Hermes to cover the
legacy-only, split-only, and both-present shapes. It checks the selected function,
explicit path, native task listing, connection closure, and sanitized connection
errors for each shape. These six cases run in CI without Hermes.

## History

Before fix A, the pinned checkout lacked `kanban_db.connect`, causing 12 failures
across `tests/test_kanban.py` and `tests/test_native_pipeline.py` before task
operations ran. The original full-suite result was 124 passed, 1 skipped,
12 failed with Hermes; without Hermes it was 119 passed, 18 skipped, 0 failed.

## Verification

The integration fixtures use `TEAMFLOW_TEST_HERMES_REPO` when set; otherwise
`teamflow.runtime.find_install()` detects Hermes on PATH. `runtime_python()`
validates the interpreter. Missing prerequisites skip by default;
`TEAMFLOW_REQUIRE_HERMES=1` makes them fail. An installed but incompatible Hermes
remains a failure.

All 12 previously failing tests now pass. The focused Kanban, native pipeline,
and compatibility run passed all 20 tests (plus 4 subtests), with no skips or
failures. No further API differences required changes.

The full suite uses Python 3.12.14, pytest 9.1.1, and Node 24.19.0; CI uses
Python 3.11 and Node 22 without Hermes. Local socket access was enabled for the
dashboard tests. No models or live authentication were used. Full-suite runs
used the default Playwright cache, so the missing Chromium executable caused
one browser skip; the other 17 skips without Hermes are integration tests.

| Command | Hermes on PATH | Passed | Skipped | Failed |
| --- | --- | ---: | ---: | ---: |
| `python -m pytest -q -ra` | No | 125 | 18 | 0 |
| `python -m pytest -q -ra` | Yes, pinned checkout | 142 | 1 | 0 |
| `node --test tests/*.cjs` | No | 3 | 0 | 0 |
| `node --test tests/*.cjs` | Yes, pinned checkout | 3 | 0 | 0 |

Pytest additionally reported 97 passing subtests without Hermes and 101 with
Hermes; these are excluded from the counts above.

Reproduce from the repository root in this environment:

```sh
# The inherited PATH contains no Hermes.
/workspace/.onboarding/venv/bin/python -m pytest -q -ra
PATH="/workspace/.onboarding/hermes-agent/venv/bin:$PATH" \
  TEAMFLOW_REQUIRE_HERMES=1 /workspace/.onboarding/venv/bin/python -m pytest -q -ra
node --test tests/*.cjs
PATH="/workspace/.onboarding/hermes-agent/venv/bin:$PATH" node --test tests/*.cjs
```
