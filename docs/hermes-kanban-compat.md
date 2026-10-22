# Hermes Kanban compatibility

Observed on 2026-10-22 with Teamflow based on `e66da0e` and the locally
installed Hermes commit `3ab0930318ad970b4ec102838f75f62973e188ec`.
The Hermes integration tests use `TEAMFLOW_TEST_HERMES_REPO` when set; otherwise
`teamflow.runtime.find_install()` detects the executable/source checkout.
`runtime_python()` validates the selected interpreter. Missing prerequisites skip
by default; `TEAMFLOW_REQUIRE_HERMES=1` makes the fixture fail instead.
An installed but incompatible Hermes is a test failure, not a skip or xfail.

## Confirmed API mismatch

All 12 failing tests below reach this call in `teamflow/kanban_child.py:33`:

```python
from hermes_cli import kanban_db as db
conn = db.connect(root / 'kanban.db')
```

The old contract **expected by Teamflow** is
`hermes_cli.kanban_db.connect(db_path) -> sqlite3.Connection`.
This describes Teamflow's call site; it does not assert a signature from an
unverified older Hermes revision.

In the pinned Hermes checkout, `kanban_db` does not expose `connect`.
The connection implementation lives in `hermes_cli/kanban_db_connect.py:716`:

```python
def connect(db_path: Optional[Path] = None, *, board: Optional[str] = None) -> sqlite3.Connection:
```

It opens and initializes the SQLite board at the explicit path. The change
relevant here is the module location/export, not the positional path argument.
`kanban_db.py` imports `init_db` and `write_txn` from that split module, but
does not re-export `connect`. Hermes's own `hermes_cli/kanban.py` imports
`kanban_db_connect` separately.

Calling `execute()` directly in an isolated, credential-free Hermes subprocess
with a synthetic `start` request exposes the underlying exception:

```text
AttributeError: module 'hermes_cli.kanban_db' has no attribute 'connect'
```

The normal child boundary deliberately hides exception details and returns
`{"ok": false, "error": "NativeOperationError"}`. The parent raises
`teamflow.kanban.KanbanError: NativeOperationError`. The connection call runs
before operation validation, task creation, claiming, completion, or blocking.
Consequently, these failures do not establish additional mismatches in those
later APIs.

## Failing tests

Every row has the same old/new API contract described above and the same
proposed minimal fix **A** below. Node IDs are given in full.

| Failing test | First failing operation | Changed Hermes call | Proposed fix |
| --- | --- | --- | --- |
| `tests/test_kanban.py::NativeBoardTests::test_completed_response_conflict_and_stale_handle_are_rejected` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_failure_is_native_block_with_fenced_run` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_foreign_claim_cannot_be_replayed_or_completed` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_idempotency_scopes_request_role_ticket_and_root` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_invalid_api_types_fail_closed_without_creating_tasks` | `board.rows()` after invalid-input subtests | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_null_run_id_cannot_bypass_fencing` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_real_child_environment_is_credential_free` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_real_claim_and_completion_have_native_history` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_replay_rejects_broken_native_run_lease` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_kanban.py::NativeBoardTests::test_restart_replay_deduplicates_claim_and_completion` | `board.start(...)` | `db.connect(path)` | A |
| `tests/test_native_pipeline.py::NativePipelineTests::test_native_board_roundtrip_csv_repair_and_cache` | pipeline's first `board.start(...)` | `db.connect(path)` | A |
| `tests/test_native_pipeline.py::NativePipelineTests::test_native_board_specialist_handoff_drafts_not_project_done` | specialist flow's first `board.start(...)` | `db.connect(path)` | A |

The invalid-input subtests currently accept the generic error raised by the
connection failure. They therefore do not demonstrate that the invalid inputs
reached Hermes operation validation in this run.

## Proposed minimal fix A (not applied)

Import the connection function from its current module and replace only the
connection call in `teamflow/kanban_child.py`:

```diff
 from hermes_cli import kanban_db as db
+from hermes_cli.kanban_db_connect import connect
 ...
-conn = db.connect(root / 'kanban.db')
+conn = connect(root / 'kanban.db')
```

Keep task operations on `db`, the explicit per-run database path, credential
isolation, ownership checks, and error envelope. Rerun the native tests after
that separate runtime change to find any subsequent incompatibilities. This
proposal addresses the observed missing attribute; it has not been applied or
claimed to make the entire native suite pass.

## Verification counts

The suite was run with Python 3.12.14, pytest 9.1.1 and Node 24.19.0.
The configured CI job uses Python 3.11 and Node 22 and installs no Hermes.
Local socket permission was enabled for the dashboard server tests. No models
or live authentication were used.

For the full-suite runs, Playwright was installed but its default browser cache
had no Chromium, so the browser test skipped with an installation reason.

| Command | Hermes on PATH | Passed | Skipped | Failed |
| --- | --- | ---: | ---: | ---: |
| `python -m pytest -q` | No | 119 | 18 | 0 |
| `python -m pytest -q` | Yes, pinned checkout | 124 | 1 | 12 |
| `node --test tests/*.cjs` | No | 3 | 0 | 0 |
| `node --test tests/*.cjs` | Yes, pinned checkout | 3 | 0 | 0 |

Pytest additionally reported 97 passing subtests without Hermes and 101 with
Hermes; those are not included in the test counts above. The 18 skips without
Hermes consist of 17 local Hermes integration tests and one browser test.
The fingerprint and timeout adapter unit tests still run without Hermes.

The browser test was also run with the installed Chromium cache selected via
`PLAYWRIGHT_BROWSERS_PATH=/workspace/.onboarding/browsers`: 1 passed, 0 skipped,
0 failed. Only a missing browser executable is converted to a skip; other
Playwright launch failures still fail.

To reproduce in this sandbox from the repository root (append `-ra` to see
skip reasons):

```sh
# The inherited PATH here contains no Hermes.
/workspace/.onboarding/venv/bin/python -m pytest -q
PATH="/workspace/.onboarding/hermes-agent/venv/bin:$PATH" \
  /workspace/.onboarding/venv/bin/python -m pytest -q
node --test tests/*.cjs
PATH="/workspace/.onboarding/hermes-agent/venv/bin:$PATH" node --test tests/*.cjs
```
