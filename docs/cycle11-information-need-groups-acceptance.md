# Cycle 11 information-need groups acceptance

Date: 2026-10-18

Requested model override: `gpt-6-luna`; runtime identity is not exposed in a verifiable way here, so application of the override cannot be confirmed.

Scope: optional user-authored information-need labels on exact query records. Query identity, judgments, ranking inputs, and per-query metrics remain authoritative.

## Subagent record

| Role | Responsibility | Requested override | Runtime identity |
| --- | --- | --- | --- |
| Research | Compare candidate-pool and information-need-group directions; document primary-source findings, project fit, and bounded acceptance criteria. | `gpt-6-luna` | Unverified; runtime identity is not exposed. |
| Implementation | Implement optional group normalization, split integrity, freshness handling, readiness counts, persistence/export compatibility, and UI support. | `gpt-6-luna` | Unverified; runtime identity is not exposed. |
| QA | Add and run bounded acceptance/regression checks; inspect browser behavior and package smoke; record evidence and skips. | `gpt-6-luna` | Unverified; runtime identity is not exposed. |

## Acceptance criteria

| Gate | Required evidence | Status |
| --- | --- | --- |
| Legacy compatibility | Load a legacy concept without `information_need`; exact query IDs, stored JSON, judgments, and both current/stale judgment states remain unchanged. Compare SQLite schema and records before/after the read. | PASS |
| Group normalization | Same-split variants with differently spaced/cased labels normalize to one group; another label is independent; blank/missing labels remain singleton queries. | PASS |
| Split integrity | Attempt to save a label shared across train and validation; receive a clear validation error and prove saved concept plus version history are unchanged. | PASS |
| Judgment freshness | Changing only a group label preserves query fingerprint and judgment freshness. Editing query text or split still marks the judgment stale. | PASS |
| Readiness | Per-split group/query totals and graded/positive coverage match the fixture. Tune eligibility still depends on a positive train query judgment. No group-average score or metric is added. | PASS |
| Snapshot/export | Profile and run snapshots/exports retain labels, exact query IDs, text, split, and membership. | PASS |
| Retrieval invariance | With the same synthetic Elasticsearch response, group-only edits send identical retrieval request bodies and preserve candidate/baseline identities and order. | PASS |
| Browser/UI | Add/edit/save/reload labels and display per-split group coverage. Render hostile label text as literal text, with no executable markup. Record browser/runtime and console evidence. | PASS |
| Bounded offline regression | Focused Cycle 11 suite, readiness regression, full offline suite, syntax checks, package build/install, and installed CLI/service smoke. The full suite completed with two skips; those skipped checks are not passes. | PASS |
| Standalone live Elasticsearch acceptance | Independently exercise against Elasticsearch and a live corpus. | NOT RUN |
| Opt-in checks | Live Elasticsearch class was skipped against the refused loopback endpoint; tokenizer parity was skipped because its isolated asset fixture was not supplied. Neither check passed or ran to completion. | NOT RUN |

## Test boundary

`tests/test_information_need_groups_acceptance.py` uses a temporary SQLite database, synthetic concept/query/document identifiers, a dynamically allocated loopback port, and mocked Elasticsearch calls for profile/export and preview invariance checks. It does not use a customer database, corpus, or credentials. UI acceptance is a separate real-browser check; API evidence alone does not pass that gate. No group-average metrics are expected or accepted in this cycle.

## Execution evidence

Statuses below come from the commands run for this acceptance. Separate source-tree tests, live Elasticsearch tests, browser results, and installed-wheel results.

| Gate | Status | Command/environment/result/boundary |
| --- | --- | --- |
| Focused Cycle 11 | PASS | `./.venv/bin/python -m unittest discover -s tests -p 'test_information_need_groups_acceptance.py' -v`; repository venv Python 3.12; 7 tests in 0.181s, `OK`. Temporary SQLite and synthetic values only. Checks legacy/current+stale evidence preservation, normalized/shared and singleton groups, split-rejection atomicity/version history, group-only freshness versus query/split staleness, per-split readiness counts and tune eligibility, profile/run export snapshots, and identical mocked retrieval requests/results after group-only edits. |
| Readiness regression | PASS | `./.venv/bin/python -m unittest discover -s tests -p 'test_concept_tune_readiness.py' -v`; Python 3.12; 12 tests in 0.636s, `OK`. Existing ungrouped fixtures now assert that each legacy query is one implicit group, while retaining all prior exact count and eligibility assertions. |
| Live concept acceptance | NOT RUN | The live Elasticsearch acceptance was not run by itself to avoid accessing a configured corpus. In the full suite, the class skipped against an explicitly refused loopback URL; no live Elasticsearch endpoint or customer corpus was contacted. |
| Full offline suite | PASS, with skips | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:9 ES_RAG_ACCEPTANCE_SOURCE_INDEX=cycle11-synthetic-unused ./.venv/bin/python -m unittest discover -s tests -v`; 72 tests in 4.970s, `OK (skipped=2)`. This reports the suite command completed successfully, not that every test passed: the live Elasticsearch class skipped because the deliberately refused loopback endpoint was unavailable, and tokenizer parity skipped because its isolated four-asset fixture was not supplied. All other tests used synthetic/mocked services and temporary stores. |
| Browser/UI | PASS | Playwright CLI via `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`, repository fixture `tests/run_tune_readiness_fixture.py`, loopback URL `http://127.0.0.1:56357`, temporary SQLite, headless Chrome 154.0.0.0, Linux, 1280×720. Saved two train variants with hostile shared label `Recovery <img src=x onerror=alert(1)>` and one separate validation label, reloaded the concept, verified exact label roundtrip, zero injected `<img>` elements, and readiness coverage `1/1` train group and `1/1` validation group. Captured resources contained only loopback API URLs, including readiness calls, and no Elasticsearch URL. Console had one unrelated `GET /favicon.ico` 404; no feature-script error. |
| Syntax/whitespace | PASS | `node --check es_rag_tuner/web/app.js`; `./.venv/bin/python -m py_compile tests/test_information_need_groups_acceptance.py tests/test_concept_tune_readiness.py`; `git diff --check` — all exit 0. |
| Wheel/install/CLI | PASS | `./.venv/bin/python -m pip wheel . --no-deps --wheel-dir /tmp/es-rag-cycle11.Ts66hh/wheel`; built `es_rag_tuning_workbench-0.12.0-py3-none-any.whl`, SHA-256 `d389478bf6772c75553dc554222858ba89a5f4ae17569d770ed5152fae7b36ab`. Installed with `--no-deps --no-index` into isolated `/tmp/es-rag-cycle11.Ts66hh/venv`; installed `es-rag-workbench --help` exited 0. Started the installed service on an allocated loopback port with temporary SQLite; `/api/health` returned version `0.12.0`, synthetic concept save/list preserved `information_need`, and readiness reported one train group. No Elasticsearch was called. |

### Iteration notes

The first focused Cycle 11 run failed two tests because the fixture called POST-only `/api/concepts/list` through a GET helper (HTTP 404). The test fixture was corrected to use POST; the focused suite then passed 7/7.

The first readiness regression run used this exact command and failed 9/12 tests: `./.venv/bin/python -m unittest discover -s tests -p 'test_concept_tune_readiness.py' -v`. The failing assertions were `test_aggregate_only_and_request_does_not_mutate_database`, `test_counts_match_split_and_exclude_stale_rows`, `test_grade_zero_only_and_pin_only_do_not_qualify`, `test_initialized_empty_judgments_table_is_confirmed_zero_not_unavailable`, `test_legacy_schema_without_query_fingerprint_is_read_only_stale`, `test_query_coverage_counts_are_distinct_and_include_unlabeled_queries`, `test_stale_train_positive_is_excluded_and_counted`, `test_train_positive_outside_current_preview_is_eligible`, and `test_validation_only_positive_is_ineligible`. In every case the actual payload had the six intended additive group-count keys and the previous expected-count fixture did not; all prior document/query counts, eligibility, stale behavior, and response privacy assertions were otherwise unchanged. Updated the existing test helper to assert singleton-group counts for legacy ungrouped fixtures, then reran the exact command successfully at 12/12.

## Final disposition

PASS for the bounded synthetic/offline, browser, and package gates above. Standalone live Elasticsearch acceptance remains NOT RUN. The two opt-in suite checks were skipped and do not count as passed. These synthetic and mocked results do not establish customer-corpus behavior or production retrieval quality.
