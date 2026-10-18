# Run-history detail acceptance

Date: 2026-10-18
Baseline: commit `851b140`, tag `v0.2.0`; the committed baseline records 31 tests (20 live concept/provider + 11 mocked robustness).

## PASS / FAIL criteria

| Gate | PASS when | FAIL when |
|---|---|---|
| Exact run selection | Clicking one history row posts only that row's `concept_id` and `run_id` to `/api/concepts/runs/export`, then shows only that run. | IDs are omitted, mixed, or details from a different run appear. |
| Preview details | The selected preview shows its saved query and baseline/candidate IDs with ranks, with no more than 10 organic rows per ranking list and an omitted-row count. | It re-queries Elasticsearch, mixes candidate data, misstates ranks, or displays an unbounded list. |
| Tune details | Training baseline/tuned aggregate metrics and per-query evidence are shown; validation is separate when present or explicitly unavailable; ranked rows are bounded. | Train/validation are conflated, per-query results are lost, or unavailable validation is implied to have a score. |
| Privacy and escaping | Rendered detail omits judgment reasons and source bodies; query/IDs are escaped as text; no injected image/script element is created. | Reasons or source body appear, or supplied markup becomes executable DOM. |
| Errors and layout | A failed export gives a readable inline error without injecting markup; 390px viewport has no horizontal document overflow. | Error handling leaves a blank/broken view, injects markup, or document width exceeds viewport width. |
| Regression | Full test suite passes, including existing profile export behavior; wheel build/install CLI smoke passes if packaging is affected. | Any required suite or package gate fails. |

## Execution evidence

The focused API acceptance and full test suite passed against the Cycle 2 working tree. A 0.3.0 wheel was built, its metadata checked, and the installed CLI help was exercised in a temporary environment. Browser smoke is recorded below; it used a disposable app server on a dynamically allocated port and a temporary SQLite database. The stored fixture used a placeholder corpus name; it made no Elasticsearch requests and did not inspect any user database or credentials. Existing ports 8765 and 8766 were untouched.

| Gate | Status | Command and result |
|---|---|---|
| Focused saved-run API acceptance | PASS | `PYTHONPATH=tests ./.venv/bin/python -m unittest test_concept_live_acceptance.LiveConceptAcceptance.test_saved_experiment_run_export_is_complete_private_and_read_only -v` — 1 test, 0.268s. It exercises exact saved-run export, preview evidence, privacy, and no-write invariants. |
| Full suite | PASS | `./.venv/bin/python -m unittest discover -s tests -v` — 31 tests, 28.880s, `OK` (20 live concept/provider + 11 mocked robustness). The existing profile export checks remain in this run. |
| Wheel and installed CLI | PASS | Environment: repository `.venv` Python 3; isolated target `/tmp/run-history-wheel-qa.3oiTK1`. `./.venv/bin/python -m pip wheel . --no-deps --wheel-dir /tmp/run-history-wheel-qa.3oiTK1/wheels` built the wheel. `unzip -p /tmp/run-history-wheel-qa.3oiTK1/wheels/es_rag_tuning_workbench-0.3.0-py3-none-any.whl '*/METADATA'` reported `Name: es-rag-tuning-workbench`, `Version: 0.3.0`. Installed with `/tmp/run-history-wheel-qa.3oiTK1/venv/bin/python -m pip install --no-deps --no-index /tmp/run-history-wheel-qa.3oiTK1/wheels/es_rag_tuning_workbench-0.3.0-py3-none-any.whl`; from the temporary target directory, `./venv/bin/es-rag-workbench --help` exited 0. Wheel SHA-256: `dde685069d3d254400387e3d6a5f5ff324ff6bbe3f62382fc9095d8fafafb55d`. |

### Delegated work

| Workstream | Owned scope and completed work | Model |
|---|---|---|
| Research | Evaluation/run comparison note for single-run detail, with cross-run comparison as a future extension. | GPT-6 Luna |
| Package/runtime metadata | Package and runtime version metadata bump to 0.3.0. | GPT-6 Luna |
| Frontend | Per-run history detail UI, responsive rendering, and export/download hooks. | GPT-6 Luna |
| Independent acceptance | API acceptance assertions, disposable browser smoke, suite/package gates, and this report. | GPT-6 Luna |

The participating tasks were assigned under GPT-6 Luna; no model difference was reported.

### Browser smoke

| Check | Status | Evidence |
|---|---|---|
| Exact selection request | PASS | Selected tune run `ui-tune-893b4b03`; browser fetch instrumentation observed `{ "concept_id": "cycle2-history-893b4b03", "run_id": "ui-tune-893b4b03" }`. The rendered details matched that run's synthetic query IDs, metrics, and ranked IDs. |
| Preview view | PASS | `ui-preview-893b4b03` showed the saved query, baseline/candidate IDs and positions, 10 rows in each list, and “그 밖의 결과 4개” for each 14-row saved ranking. Injected `<img ...>` text remained text; the detail subtree contained zero `img` and `script` elements. |
| Tune view | PASS | Displayed separate training baseline and tuned metrics, two per-query entries in both variants, saved ID/rank lists capped at 10 with omitted counts, and explicit “검증용 평가 기록 없음”. |
| Privacy | PASS | Detail text contained neither `PRIVATE_REASON_SENTINEL` nor `SOURCE_BODY_MUST_NOT_RENDER`. These sentinels existed only in the test-owned run fixture. |
| Error handling | PASS | Changing the disposable preview row's concept ID to a nonexistent ID returned a safe inline 404 message; no script element appeared. Console recorded expected HTTP 404 resource errors for the missing favicon and deliberately invalid API request; no application JavaScript exception was observed. |
| Mobile overflow | PASS | At viewport width 390px, `document.documentElement.scrollWidth` was 390px. |
| Existing in-result screens/download | NOT RUN | The browser smoke focused on history detail rendering. Existing HTTP preview/tune and profile export coverage is recorded by the full suite above. The JSON download button was not exercised in this cycle. |

Browser command summary (the exact launch shell command and exact CLI argument strings were not retained in the execution log and could not be recovered): the disposable server ran on `127.0.0.1:36757` against the temporary SQLite DB; browser operations used `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh` for `open http://127.0.0.1:36757`, `snapshot`, selector-based `click`, `eval`, `resize 390 844`, `console error`, and `close`. This is a command summary, not a verbatim transcript. The ephemeral service and database were shut down/deleted after the smoke.
