# Saved preview-run comparison acceptance

Date: 2026-10-18
Baseline: commit `cf2b906`, tag `v0.3.0`; committed suite baseline 31 tests (20 live concept/provider + 11 mocked robustness).

## PASS / FAIL criteria

| Gate | PASS when | FAIL when |
|---|---|---|
| Selection and identity | A user can accessibly select exactly two persisted preview runs from the same concept. Each artifact request carries its own selected `concept_id` and `run_id`, and the response is checked against that identity. | Fewer/more than two runs are accepted, tune runs or cross-concept runs are accepted, or fetched run identity is mixed or unverified. |
| Same-context comparison | With matching comparison context, show both saved baseline/candidate snapshots and candidate rank movement joined by exact `(index, id)`. State membership as observed only within each saved top-N snapshot. | IDs are joined without index, live search/requery is used, or membership is stated beyond saved top-N. |
| Pins and rank safety | Pin-only rows are represented as pinned/unranked and receive no rank movement. If the saved index UUID identity is unavailable or missing, direct deltas are suppressed; a result row missing its index also fails closed. | A pin-only row receives an organic rank, or incomplete identity is treated as a direct match. |
| Mismatch behavior | Context, baseline, or relevant fingerprint mismatch keeps the two snapshots side-by-side, suppresses direct deltas, and presents a concrete reason. | A mismatch is hidden or direct rank movement remains presented as comparable. |
| Privacy and read-only boundary | Detail contains no grades, judgment reasons, or source body; UI uses only stored export evidence and does not query Elasticsearch. | Human grades/reasons/source text are shown, or current Elasticsearch data is fetched. |
| Robustness and layout | Malformed artifacts and request errors fail safely; markup is escaped; 390px width has no horizontal document overflow. | Bad data crashes the view, markup executes, or page overflows horizontally. |
| Regression | Existing single-run detail and JSON download behavior remain; full suite passes. Node syntax and wheel/install gates are included if their inputs change. | Existing detail/export behavior breaks or a required gate fails. |

## Execution evidence

The focused API acceptance, full test suite, JS syntax, browser smoke, wheel build/install, and installed CLI gates completed. The browser used a temporary SQLite database and a dynamic loopback port; the fixture did not connect to Elasticsearch. No user DB or credential value was read. Existing ports 8765 and 8766 were not used or modified.

| Gate | Status | Exact command / evidence |
|---|---|---|
| Focused two-run API acceptance | PASS | Environment: Python 3.12.3 from repository `.venv`; live Elasticsearch fixture as configured by `ES_RAG_ACCEPTANCE_ES_URL` (default `http://127.0.0.1:9200`). `PYTHONPATH=tests ./.venv/bin/python -m unittest test_concept_live_acceptance.LiveConceptAcceptance.test_two_saved_preview_runs_export_exact_comparison_context -v` — 1 test, 0.240s, `OK`. Creates/removes only its unique `concept-accept-*` index and temporary SQLite DB. |
| Full suite | PASS | `./.venv/bin/python -m unittest discover -s tests -v` — 32 tests in 28.590s, `OK` (21 live concept/provider + 11 mocked provider robustness). Includes existing single-run export/profile parity and the new two-preview export-context case. |
| Browser fixture setup | PASS | `./.venv/bin/python tests/run_preview_comparison_fixture.py`; temporary SQLite database, seeded synthetic records only, loopback port assigned dynamically. Observed ports: `52355` and `52547`. The helper exits on Ctrl-C and deletes the temporary directory. |
| Browser/runtime syntax | PASS | `node --check es_rag_tuner/web/app.js` with Node `v22.23.2`; `./.venv/bin/python -m py_compile tests/test_concept_live_acceptance.py tests/run_preview_comparison_fixture.py`; `git diff --check`. |
| Wheel and installed CLI | PASS | Environment: repository `.venv` Python 3.12.3; isolated target `/tmp/run-compare-wheel-qa.vKia3Z`. `./.venv/bin/python -m pip wheel . --no-deps --wheel-dir /tmp/run-compare-wheel-qa.vKia3Z/wheels` built `es_rag_tuning_workbench-0.4.0-py3-none-any.whl`. `unzip -p /tmp/run-compare-wheel-qa.vKia3Z/wheels/es_rag_tuning_workbench-0.4.0-py3-none-any.whl '*/METADATA' | rg '^Name:|^Version:'` reported package version `0.4.0`. Installed with `/tmp/run-compare-wheel-qa.vKia3Z/venv/bin/python -m pip install --no-deps --no-index /tmp/run-compare-wheel-qa.vKia3Z/wheels/es_rag_tuning_workbench-0.4.0-py3-none-any.whl`; `(cd /tmp/run-compare-wheel-qa.vKia3Z && ./venv/bin/es-rag-workbench --help)` exited 0. Wheel SHA-256: `cc7869b09532f4806a8ad9b2b52ed5e54b0e103e9b0393647805f6d1d1cd56b3`. |

## Browser evidence

| Case | Status | Evidence |
|---|---|---|
| Exact pair selection and export ownership | PASS | Checked accessible preview inputs for `match-a` and `match-b`; the button became enabled only at two selected rows. Instrumented `fetch` captured exactly two POST bodies: `{"concept_id":"synthetic-run-comparison","run_id":"match-b"}` and `{"concept_id":"synthetic-run-comparison","run_id":"match-a"}`. Each response passed the existing exact run identity guard. Seven preview checkboxes included one foreign-concept fixture; after selecting a run, that checkbox and the other-concept rows were disabled. The tune row had no comparison checkbox. |
| Matched context and movement | PASS | Two `.saved-preview-side` panels rendered. `.saved-preview-movements` kept the same document ID in `idx-a` and `idx-b` as separate entries and showed `idx-a/shared` moving 1→2 and `idx-b/shared` 2→1. The new-only row said it appears only in one saved top-N and does not imply absence from the full index. |
| Pin-only row | PASS | `idx-a / pin-only` appeared under `.run-pin-hints`; it had no rank and no movement row. |
| Context, baseline, hash, and missing row index | PASS | UUID mismatch, changed baseline snapshot, shared document source-hash mismatch, and a candidate row missing its index were each tested. The cases retained two side-by-side snapshots, showed a specific reason, and rendered zero direct movement rows. |
| Unavailable saved index UUID identity | PASS | Newly added synthetic preview `identity-unavailable` has `reproducibility.index_identity.available=false` and `uuids=[]`; it was compared with valid preview `match-a` from the same concept and otherwise matching saved context. Browser output retained 2 `.saved-preview-side` snapshots, showed “같은 인덱스인지 확인할 정보가 부족합니다.” and “두 실행이 같은 인덱스에서 수행됐는지 확인할 수 없습니다.”, and rendered 0 `.saved-preview-movements li`. |
| Malformed artifact/error handling | PASS | Browser `fetch` was stubbed to return a wrong format/run identity with HTTP 200. UI showed a safe inline retryable error, left comparison output empty, and created no image or script nodes. |
| Privacy, query escaping, and no requery | PASS | Fixture included a query containing `<img ...>`, a rating/reason sentinel, and a source-body sentinel. Comparison rendered zero `img`/`script` nodes and none of the source/reason/grade sentinels. Resource inspection found no Elasticsearch/9200 requests; the only comparison requests were the two stored-run exports. |
| 390px layout and console | PASS | `resize 390 844`; browser eval reported `innerWidth=390`, `documentElement.scrollWidth=390`, overflow false. Browser console showed one expected 404 for missing `/favicon.ico`; no application JavaScript errors were observed. |
| Copy-only UX follow-up | PASS | After the frontend copy-only patch, reran the selected-count and matched-comparison label checks against fresh synthetic records on dynamic port `38337`. Selected status read `같은 개념의 미리보기 2개를 선택했습니다.` and a check for `synthetic-run-comparison` in that status returned `false`. The matched intro read `두 실행은 같은 질의·필드 구성·검색 방식·필터·후보 및 표시 개수·인덱스·기준선 기록을 공유합니다. 개념 설정 차이를 비교합니다.` |
| Existing detail/download regression | PASS, bounded | The existing detail button rendered saved query and ranking details without source/reason sentinel content. The JSON export action was exercised with `URL.createObjectURL` and anchor-click capture: filename was `es-rag-run-match-a.json`, blob began with the expected `es-rag-experiment-run` format/version JSON. The capture prevented writing a downloaded file to disk; actual OS download persistence was NOT RUN. |

Browser CLI was `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`. For the initial broad smoke, the exact outer shell invocation (including any wrapper/session flags) was not retained; the following is the recorded CLI command summary, with snapshot-dependent element refs as observed:

```text
open http://127.0.0.1:52547
click e159
check e297
check e282
click e184
resize 390 844
open http://127.0.0.1:52355
click e159
clear e185; check e240; check e270; click e184   # index UUID mismatch
clear e185; check e225; check e270; click e184   # baseline mismatch
clear e185; check e210; check e270; click e184   # candidate source-hash mismatch
clear e185; check e195; check e270; click e184   # missing index identity
```

The malformed case used browser `eval` to replace `fetch` for the export route with HTTP 200 JSON `{format:'wrong-format',version:1,run:{run_id:'wrong-id',concept_id:'synthetic-run-comparison',kind:'preview'}}`; the actual full eval expression was not retained. Other `eval` commands inspected request bodies, comparison DOM, privacy sentinels, dimensions, console errors, and existing detail/download behavior. CLI operations were issued from the repository root. Browser evidence is from disposable synthetic SQLite data, not a full novice-flow or live-Elasticsearch UI run; ports 8765/8766 were untouched.

The later copy-only label rerun used this exact CLI command sequence from the repository root against another temporary fixture on port `38337`:

```text
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh open http://127.0.0.1:38337
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e159
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh check e297
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh check e282
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "document.querySelector('#saved-preview-selection-status')?.textContent"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "document.querySelector('#saved-preview-selection-status')?.textContent.includes('synthetic-run-comparison')"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click '#compare-saved-previews'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "JSON.stringify({status:document.querySelector('#saved-preview-selection-status')?.textContent,comparison:document.querySelector('#saved-preview-comparison')?.innerText})"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh close
```

The two check refs came from the immediately preceding snapshot and selected `match-a` / `match-b`. An initial CSS lookup using a presumed input `value` did not match; I re-snapshotted and used the accessible checkbox refs instead. The fixture server was stopped after the run and its temporary SQLite directory was removed.

The unavailable-UUID check used the same fixture helper after adding `identity-unavailable` with an explicitly unavailable identity and an empty UUID list. The exact commands were:

```text
./.venv/bin/python tests/run_preview_comparison_fixture.py
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh open http://127.0.0.1:57121
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e159
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh check e220
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh check e310
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click '#compare-saved-previews'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "JSON.stringify({sides:document.querySelectorAll('#saved-preview-comparison .saved-preview-side').length,mismatch:document.querySelector('#saved-preview-comparison .saved-preview-mismatch')?.innerText,movements:document.querySelectorAll('#saved-preview-comparison .saved-preview-movements li').length})"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh close
```

Output: `{"sides":2,"mismatch":"직접 순위 비교를 표시하지 않았습니다\n\n두 기록은 나란히 볼 수 있지만 아래 조건이 달라 순위 이동으로 해석하지 않습니다.\n\n같은 인덱스인지 확인할 정보가 부족합니다.\n두 실행이 같은 인덱스에서 수행됐는지 확인할 수 없습니다.","movements":0}`. Snapshot refs `e220` and `e310` selected `identity-unavailable` and valid `match-a`. The temporary fixture server was stopped and its SQLite directory removed. No Elasticsearch request was made.
