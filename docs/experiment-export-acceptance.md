# Saved experiment-run export acceptance

Date: 2026-10-18
Scope: versioned JSON export of one saved concept preview/tune run.

## Delegated work

All implementation, browser smoke, and test execution in this cycle were delegated to GPT-6 Luna subagents:

| Agent | Responsibility | Result |
|---|---|---|
| `run_export_backend` | Export API, safe stored-field projection, package version, API/README docs | Implemented `POST /api/concepts/runs/export`; documented run export separately from profile export. |
| `run_export_frontend` | Per-run JSON download UI and isolated browser smoke | Implemented the download action; mocked-API browser smoke passed on port `18765`. |
| `run_export_qa` | Acceptance test, full suite, wheel/install validation, acceptance evidence | 31/31 suite and 0.2.0 wheel/install gates passed; real browser-to-backend download was not run. |
| `research_eval` | Official-source research on evaluation/export formats | Added [`experiment-export-research.md`](experiment-export-research.md), checked 2026-10-18. |

The coordinator reviewed the source diffs and reports and did not run tests or edit implementation/test code.

## Environment and safety boundary

- Python 3.12.3 at `./.venv/bin/python`.
- Elasticsearch 9.5.5 at `http://127.0.0.1:9200`.
- Read-only reference index: `jira-grpc-issues-9-5-5`.
- Acceptance uses a temporary SQLite database and uniquely named `concept-accept-*` / `concept-agent-nested-*` fixture indices. Tests remove only fixtures they create and fingerprint the configured source index before and after.
- Browser smoke used isolated port `18765` and mocked API responses. Existing ports `8765` and `8766` were left untouched.

## Gates

| Gate | Result | Evidence |
|---|---|---|
| Focused saved-run export | PASS | `PYTHONPATH=tests ./.venv/bin/python -m unittest test_concept_live_acceptance.LiveConceptAcceptance.test_saved_experiment_run_export_is_complete_private_and_read_only -v` — 1/1 passed in 0.281s. |
| Full suite | PASS | `./.venv/bin/python -m unittest discover -s tests -v` — 31/31 passed in 44.405s: 20 live concept/provider acceptance tests and 11 mocked robustness tests. |
| Saved profile export regression | PASS | Existing parity test passed; app-integration profile remains `es-rag-profile-v1` and Python, raw Search API, and Mustache results remain in parity. |
| Wheel build and installed CLI | PASS | `./.venv/bin/python -m pip wheel . --no-deps -w <temporary-wheel-dir>` built `es_rag_tuning_workbench-0.2.0-py3-none-any.whl`. Installed without dependencies in a temporary venv; `es-rag-workbench --help` from outside the repository exited 0. |
| Frontend export smoke | PASS, mocked API | Verified the selected `concept_id`/`run_id` POST body, `es-rag-run-run_one_x.json` download name, no row overflow at 390px, `node --check`, and `git diff --check`. |
| Real browser-to-backend download | NOT RUN | The HTTP API test and isolated mocked frontend smoke ran separately. |
| Current default-service smoke and Code-RAG regression | NOT RUN | The prior source-service process was absent during this cycle; ports 8765/8766 were not used. Prior checks remain v0.1.0 baseline evidence only. |

The export test covers tune and preview runs, exact concept/run ownership, schema version, all persisted judgments and rankings, aggregate/per-query train metrics, validation-unavailable warning, source hashes and reproducibility fingerprints, unjudged versus grade 0, complete output counts, unrelated-run exclusion, common `password=...` redaction, absence of DB paths and fetched source bodies, and unchanged fixture fingerprints. The route reads the exact saved SQLite run row and does not query Elasticsearch.

### Package evidence

- Wheel SHA-256: `8f9702eca40015e9f758876778c72814f388c39ccc83bfe7acddfa6805d8ffe9`
- Package metadata version: `0.2.0`

## Limits

The artifact records stored evidence from the time of a run; it does not rerun retrieval or prove current index state, semantic relevance, answer correctness, or downstream RAG quality. It retains query text and judgment reason/note text. Common credential patterns are redacted, but arbitrary sensitive prose cannot be reliably detected; users are asked to review the file before sharing. Document IDs and source SHA-256 values remain present for mapping and reproducibility.
