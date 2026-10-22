# Native Kanban subprocess adapter

`teamflow.kanban.NativeBoard(hermes_repo: Path, runtime_home: Path, run_root: Path)`
uses the **installed Hermes interpreter** (`venv/Scripts/python.exe` on Windows,
`venv/bin/python` on POSIX), not the supervisor interpreter. No package installation
is performed. Every operation starts `kanban_child.py` with Python `-I`, JSON stdin,
`shell=False`, a 60-second timeout, and `cwd=runtime_home`. The child imports only
the native `hermes_cli.kanban_db` API and its dependencies, never an agent loop,
gateway or dispatcher. There are no model calls or external tool invocations.

## API and state

- `start(ticket_id: int, role: str, request: dict) -> {"id": str, "run_id": int}`
  creates a native card and **claims it before returning**, so the supervisor must
  call this before spawning its model process. Roles are 1–64 ASCII letters,
  digits, underscores or hyphens. Request and response must be JSON objects.
- `finish(handle, response: dict)` completes the native run using
  `expected_run_id`. Stores only a canonical SHA-256 response digest in task result,
  run summary, and run metadata (`response_hash`), not raw response text.
- `fail(handle, reason: str)` blocks the current native run using
  `expected_run_id`. Only a SHA-256 reason digest is persisted; raw errors may
  contain credentials. Blocked cards are not silently retried or unblocked.
- `rows() -> list[dict]` returns native task dataclasses as dictionaries.

The database is **`run_root/kanban.db`**, with native `tasks`, `task_runs` and
`task_events` history. All state mutations use native APIs; SQL is only used to
read idempotency/run metadata. Workspaces explicitly use `workspace_kind="dir"`
and `workspace_path=run_root`; completion cannot delete the supervisor artifacts
as scratch workspaces. No default-profile board is used.

## Replay, fencing, and controller ownership

The idempotency key hashes normalized absolute run-root identity, ticket ID,
exact role, and canonical request hash (sorted keys, compact JSON, UTF-8).
Changing any component creates another card. JSON object key ordering does not.

A restart in the **same exclusively locked workspace** reuses a running handle
only if task `claim_lock`, `current_run_id`, and the native active run agree with
the deterministic root-specific controller owner. There is no process-PID owner:
each API call is itself a new child process. A ready card left between create and
claim can be claimed on restart; pending/todo, blocked, archived and foreign
claims fail closed. Native run IDs fence completion and failure. Null, boolean,
non-positive and stale run IDs cannot bypass the fence.

A completed `start` returns the original completed run handle. Replaying `finish`
with the same response verifies both run metadata hash and task result hash and
performs **no native completion call and no new events/runs**. A different response
is rejected. `current_run_id` is cleared by native completion, so completed replay
resolves the completed run from native `task_runs` rather than fabricating a lease.

**Supervisor responsibilities:** own an exclusive workspace lock across the whole
operation, including restarts; do not run a dispatcher against this private DB;
load and validate the response cache before deciding to call a model. The adapter
never calls a model and cannot prevent a caller from doing so again. The native
claim TTL is informational here: no dispatcher automatically reclaims it. An
unchanged root owner with a still-current active native run is resumable even if
wall-clock TTL has elapsed. Do not reuse or transfer this board to another
controller while a model worker is alive.

## Isolation and errors

The child environment starts from an OS allowlist: SYSTEMROOT, WINDIR, COMSPEC,
PATH, PATHEXT, TEMP, TMP, LANG, LC_ALL (case-insensitive). All inherited `HERMES_*`,
provider credentials, unknown variables and Python injection variables are
removed. Only fresh `HERMES_HOME=runtime_home` is added; HOME, USERPROFILE, APPDATA
and LOCALAPPDATA also point to that isolated home. The installed repository is
added explicitly to `sys.path` after Python isolated startup.

Use a dedicated trusted runtime directory, never a real profile. The adapter
rejects known default home roots, inherited active home, profile directories and
paths within the installed repository before making directories. Do not place
plugins/hooks/credentials in the dedicated runtime. This is environment/cwd
isolation, **not an OS sandbox for a malicious installed Hermes package**.

Child exceptions become `{"ok": false, "error": "NativeOperationError"}` only.
Native stdout/stderr are suppressed; the parent does not relay subprocess stderr
or exception messages. Parent failures raise `KanbanError` with fixed class labels
(`NativeOperationError`, `NativeTransportError`, `UnsafeRuntimePath`).

## Real integration tests

From the project directory:

```sh
python -m pytest tests/test_kanban.py -v
```

Tests use temporary isolated homes and real installed-interpreter subprocesses,
then inspect actual SQLite rows/history. No LLM, network authentication or mocked
board implementation is used. `TEAMFLOW_TEST_HERMES_REPO` optionally selects an
installed repo for the tests; absent that, `teamflow.runtime.find_install()`
detects Hermes on PATH. The shared fixture validates the selected repo with
`runtime_python()`, and integration tests use that same resolved repo.
Missing or unusable installations skip by default with a clear reason. Set
`TEAMFLOW_REQUIRE_HERMES=1` to make missing integration prerequisites fail via
`pytest.fail()` instead (reported by pytest as fixture setup errors). A present
but API-incompatible Hermes still fails its integration tests in either mode.

Covered: claim/completion, restart dedup, matching/mismatching completed replay,
fenced block, stale/null/boolean handles, foreign task/run leases, per-root/request/
role/ticket idempotency, strict input types, real child environment scrubbing,
structured secret-free errors, and protected-home rejection. SQLite connections
in tests must be explicitly closed (`contextlib.closing`); the connection context
manager alone only commits/rolls back and leaves Windows database handles open.
