# Cycle 44 positive-target miss acceptance

## Scope and evidence boundary

The browser fixture validates the positive judgments from a saved tune against the saved, per-query baseline and tuned rank snapshots. The expected identity is `(query_id, index, document_id)`. Train and validation are evaluated independently; validation is a separate check and does not tune settings. A displayed miss means only that a positively judged document is outside the recorded tuned top-K for that saved query. It does not establish corpus-wide recall, document availability, or answer quality.

The browser script uses synthetic API responses and a temporary local database. It did not contact Elasticsearch, an AI provider, or user data.

Requested implementation model override: **gpt-6-luna**. Runtime model identity is **UNVERIFIED** because it is not surfaced for independent verification.

## Acceptance criteria

| Gate | PASS | FAIL | Current status |
| --- | --- | --- | --- |
| Split isolation and empty query | A fixture with positive train and validation queries using disjoint saved query IDs reports each lane's own misses. A saved train query with no judgments and no output snapshot key does not make the lane inconclusive or appear as a miss. | Either lane is suppressed due to the other split's judgments, or a query with no judgments is treated as missing evidence/a miss. | **PASS** |
| Positive grades and identity | Ratings 1–3 are eligible; 0, null, and invalid ratings are excluded. Matching uses the full `(query_id, index, document_id)` triple, preserving same IDs across indices and repeated document identity across distinct queries. | Any excluded rating appears, or any distinct triple is collapsed. | **PASS** |
| Tuned K, grade, and baseline context | A target at tuned rank K is not a miss; a target beyond K or absent from tuned results is a miss. Displayed targets show their numeric grade and baseline rank when available. | K boundary is off by one or grade/baseline rank context is wrong or absent. | **PASS** |
| Unavailable evidence | Missing validation output and missing/malformed in-split query snapshots show an unavailable/inconclusive status, never “no misses.” | Incomplete snapshots are reported as a successful empty miss set. | **PASS** |
| Bounded list | Each lane displays at most 20 rows and states the exact remaining count. | More than 20 rows are shown or the omitted count is wrong/absent. | **PASS** |
| Safe rendering | Hostile query/document strings appear as literal text and create no HTML elements or script effects. | Injected markup or script execution occurs. | **PASS** |
| Handoff | The handoff fills the exact saved query and document ID, retains the exact index, and makes the explicit diagnosis control available without issuing diagnosis/API calls. Changing `#index-name`, `#es-url`, saved concept scope, applied settings, or starting a connect/refresh attempt disables the old report handoff. Restoring URL text does not restore an old connection generation. | Values are imprecise, diagnosis runs automatically, or a changed scope/connection attempt leaves an old handoff active. | **PASS — current run** |
| Connection-origin invalidation | Changing `#es-url` through input/change disables the report handoff; restoring the old text and reconnecting do not revive a report from the earlier connection generation. | Any old handoff becomes enabled again before a fresh tune report. | **PASS — current run** |
| Applied-setting invalidation | Calling `applyTunedSettings()` with a setting different from the report scope immediately disables the old report handoff. | A stale report handoff remains enabled after settings change. | **PASS — current run** |
| Judgments without positive ratings | A split with judgment rows but only 0/null ratings explicitly says there are no positive ratings to compare, without claiming no misses. | The split reports an empty miss set or fails to distinguish no-positive-labels from zero misses. | **PASS — current run** |
| Connect/refresh invalidation | Clicking connect/refresh with unchanged Elasticsearch URL and index values disables the old report while the mocked request is pending and keeps it disabled after success. | The old report handoff remains or becomes enabled after the connection attempt. | **PASS — current run** |
| Connect/tune response race | A tune started while refresh is pending and completed after refresh does not restore an old-generation handoff. | The late tune response enables a handoff based on the previous connection generation. | **PASS — current run; pending state checks currently mounted buttons, and late response handoff remains disabled** |
| Positive labels with invalid identity | A positive grade with missing or blank `document_index` or `document_id` makes that split inconclusive and does not report no positive ratings or no misses. | Invalid positive identities are ignored as if no positive labels existed, or the split claims no misses. | **PASS — current run** |
| Browser health and isolation | Script exits successfully with no page errors, console errors, or failed browser requests; all API responses are synthetic. | Any browser error/request failure occurs or a non-mocked external service is contacted. | **PASS — exit 0; no console errors, page errors, or request failures; synthetic local responses only** |

The prior 15-case C44 browser run passed. The first expanded 18-case attempt had a fixture-only timeout: it queried a stale handoff locator after the overlapping tune rerendered the report. The fixture now checks currently mounted handoff buttons during the pending tune and verifies the late response's newly rendered handoff. The corrected expanded run passed all 18 cases. Overall C44 browser acceptance is **PASS** for this run. No production or live Elasticsearch evidence is claimed.

## Execution record

Coordinator authorization received for this QA pass. Environment: Node.js `v22.23.2`; Python `3.10.14` for browser subprocesses and `3.12.3` for compile/wheel commands; Google Chrome `154.0.8037.97`; Playwright resolved from `/tmp/cycle42-playwright/node_modules`.

The final C44 browser command was:

```sh
NODE_PATH=/tmp/cycle42-playwright/node_modules \
CYCLE44_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome \
PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python \
node tests/cycle44_positive_target_misses_browser.js
```

Historical result before the latest review additions: **PASS, exit 0** on the 15-case fixture, with 24 synthetic API calls and zero console errors, page errors, or failed requests. The first authorized 18-case attempt then failed with a fixture-only locator timeout:

```text
locator.isDisabled: Timeout 30000ms exceeded.
Call log:
  - waiting for locator('#tune-positive-target-misses').locator('[data-testid="positive-target-miss"]').filter({ hasText: 'train-miss' }).first().locator('[data-testid="positive-target-handoff"]')

    at main (/home/sra235/2026/elasticsearch-rag/tests/cycle44_positive_target_misses_browser.js:281:34)
```

That timeout occurred after starting a tune while mocked refresh was pending. The fixture queried a removed prior-report handoff after rerender. The assertion was updated to inspect mounted handoff buttons. The corrected expanded run below is the current result.

Current authorized expanded run: **PASS, exit 0**. Exact output:

```json
{"result":"PASS","cases":["train/validation isolation","unjudged saved train query","visible numeric grade","rating and identity filtering","tuned top-K boundary","baseline rank","validation unavailable","incomplete snapshots","20-row cap","HTML escaping","exact handoff and explicit diagnosis","index-change and dirty-scope handoff disable","URL/connection-generation invalidation","applyTunedSettings invalidation","same-values connect/refresh invalidation","connect/tune response race","judgments without positive ratings","positive judgments with missing/blank identity"],"apiCalls":41,"consoleErrors":[],"pageErrors":[],"requestFailures":[]}
```

Other required checks:

| Check | Exact command | Result |
| --- | --- | --- |
| App JavaScript syntax | `node --check es_rag_tuner/web/app.js` | **PASS, exit 0**, no diagnostics. |
| Python compile | `python3 -m compileall -q es_rag_tuner` (`python3` = 3.12.3) | **PASS, exit 0**, no diagnostics. |
| Wheel build | `wheel_dir=$(mktemp -d /tmp/cycle44-wheel-XXXXXX) && python3 -m pip wheel --no-deps --no-build-isolation . --wheel-dir "$wheel_dir"; result=$?; printf 'WHEEL_DIR=%s\n' "$wheel_dir"; exit "$result"` | **PASS, exit 0**; `WHEEL_DIR=/tmp/cycle44-wheel-rNHTmv`, `/tmp/cycle44-wheel-rNHTmv/es_rag_tuning_workbench-1.4.1-py3-none-any.whl`, 238,017 bytes, SHA256 `571e87fea693c8f78c3f710aa35a38b6956a28dda7394163aae3fe442cb480ba`. |
| Existing C37 browser regression | `NODE_PATH=/tmp/cycle42-playwright/node_modules CYCLE37_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python node tests/run_cycle37_browser_regression.js` | **PASS, exit 0**; C34/C35/C36 browser fixtures all passed against synthetic local responses, with no console or page errors. |

The current 18-case script covers train/validation isolation, a saved train query without judgments, visible numeric grades, grade and identity filtering, the tuned top-K boundary, baseline rank context, unavailable and malformed snapshots, the 20-row cap/remainder, HTML escaping, exact non-automatic handoff, index-change and dirty-scope disabling, connection-origin generation invalidation, `applyTunedSettings()` invalidation, same-values connect/refresh invalidation, the in-flight connect/tune response race, a split with judgments but no positive ratings, and positive judgments with missing/blank identity. Every tune rerun snapshots the form's current `collectConcept()` value. All 18 cases passed in the current run.

## Final versioned artifact and whitespace check

After the project version was bumped, a fresh wheel was built with:

```sh
wheel_dir=$(mktemp -d /tmp/cycle44-wheel-final-XXXXXX) && python3 -m pip wheel --no-deps --no-build-isolation . --wheel-dir "$wheel_dir"; result=$?; printf 'WHEEL_DIR=%s\n' "$wheel_dir"; exit "$result"
```

Result: **PASS, exit 0**. Artifact: `/tmp/cycle44-wheel-final-kg9Pbi/es_rag_tuning_workbench-1.5.0-py3-none-any.whl`; size **238,055 bytes**; SHA256 `5dc8305d662b642303c7431ebb028af4aa512b4fc242da08a529760fe6a6bad6`. The wheel's `METADATA` reports `Name: es-rag-tuning-workbench` and `Version: 1.5.0`.

Final whitespace check: `git diff --check` — **PASS, exit 0**, no output.
