# Role checks

Compact contract/transport smoke checks, **not broad qualification of role competence**.
All inputs are tiny fictional fixtures. No browsing, rendering, UI execution, deployment,
or model tools. Optional prose checks verify shape and selected anchors, not complete
semantic truth; a pass does not replace human review.

API: `case_request(role) -> dict`, `validate_role_response(role, request, response)
-> list[{id, passed, evidence}]`, `run_case(root: Path, role, backend, board=None) -> dict`.

Core roles use natural CSV schemas: analyst detects separators, coordinator preserves
hashes and issues instructions, implementer deduplicates decimal amounts, verifier
rejects a deliberately wrong total using independently computed checks. The other nine
cases cover two-color text design, factual copy, conflicting provided sources, decimal
deduplication, three components, three **planned** UI scenarios, title/description draft,
fixed Russian→German UI labels, and a fictional document's missing date/signature.

```bash
python -m pytest tests/test_role_checks.py -q
python -m teamflow.role_checks --run smoke-001
python -m teamflow.role_checks --run smoke-designer-001 --roles designer
```

The latter commands are LIVE and require isolated runtime auth and profiles already
prepared. The runner does not set up profiles or read/copy main-profile credentials.
A 180-second model transport timeout is the default; `--timeout` accepts 1–600 seconds.
One request reservation per role, no retry, including after ambiguous timeout. Every
role is visited sequentially even if another fails; progress is flushed immediately.

Runs live under `runs/SLUG-role`. Inputs and backend fingerprint are immutable.
SQLite records PENDING before board start/call, then COMPLETED receipt or FAILED.
PENDING/FAILED reservations cannot be replayed. COMPLETED responses may reconcile
the board without a model call and are revalidated independently on resume.
`artifacts/response.json` stores the exact response; `artifacts/checks.json` stores
independent checks. `receipt.json` binds request and response hashes. Result snapshots
are retained under `history/`; `result.json` is an atomic latest view. Artifact hashes
use canonical JSON SHA-256, not hashes of pretty-printed bytes. `model_calls` is the
durable number of reserved calls (conservative if board start failed before dispatch).

Statuses: ROLE_CHECK_PASS, ROLE_CHECK_FAIL, BLOCKED (transport/durability/board error).
Errors are whitelist codes, never raw exceptions. An aggregate `reports/SLUG.json`
is atomically updated after each role, retaining its earlier snapshots in a sibling
history directory. Exit 0 only when all selected roles pass; otherwise 2. Reusing a
slug with different role selection/model/settings is refused. Pick a new slug to
explicitly authorize a fresh test after failure; historical runs remain untouched.
