# Teamflow — an evidence-gated multi-agent team on Hermes Agent

A local orchestration layer that runs a small team of role-based agents ([Hermes Agent](https://hermes-agent.nousresearch.com/)) through a controlled workflow: coordinator → analyst → implementer → independent verifier. The controller, not the model, decides what counts as done.

Project documentation is in Russian ([README.ru.md](README.ru.md), [docs/](docs/)); code and CLI are in English.

## Ideas it demonstrates

- **Agents are tool-free and answer in JSON.** The controller validates every answer, computes facts deterministically and stores artifacts. Model output is never executed.
- **Independent acceptance.** A verifier checks the exact artifact version; acceptance happens only after real checks, and a deliberately broken candidate (`--inject-fault`) must be rejected and repaired.
- **Versioned context and bounded repair loops.** The working hypothesis may be corrected; the goal and acceptance rules may not.
- **Durable ledger and crash recovery.** Every step is written to an append-only ledger with backend receipts; a restarted run replays safely without duplicating claims or completions.
- **Native Kanban board** in an isolated Hermes runtime (separate profile, credentials never copied from the user's main profile; sign-in only on an explicit `auth` command).
- **13 roles in total**: the four core roles plus specialists (designer, copywriter, researcher, SEO, localisation, data, documents, UI tester, architect) that the coordinator requests only when needed. Their output is marked `DRAFTS_REQUIRE_REVIEW`, never "done".
- **Read-only observer dashboard** (`python -m teamflow.dashboard --open`, http://127.0.0.1:8769/) showing stages, hand-offs, stops and evidence without starting agents.

## Scenarios

| Command | What it does |
|---|---|
| `python -m teamflow pilot --run csv-demo` | Reconciles a messy sample CSV (`;` separator, decimal comma, duplicate, invalid row) with analysis, candidate, independent check and deterministic acceptance criteria |
| `python -m teamflow specialists --brief examples/website-brief.json --run drafts` | Text drafts for a fictional business brief, produced by the roles the coordinator asks for |
| `python -m teamflow.role_checks --run role-check-1` | Compact live checks of every role |
| `python -m teamflow status --run NAME` | Ledger status of a run |

## Requirements

Python 3.11+, a local Hermes Agent installation with its Python environment. `python -m teamflow prepare` creates the isolated runtime in `.runtime/hermes`; `python -m teamflow doctor` checks it without calling a model.

## Tests

`python -m pytest -q` (137 tests) and `node --test tests/*.cjs` for the dashboard UI model. Integration tests that talk to the native Hermes board need a local Hermes installation; the browser test needs Playwright.

All examples are fictional; `runs/`, `reports/` and `.runtime/` are git-ignored.
