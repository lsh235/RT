# Tune readiness acceptance

Status: PASS for Cycle 5 readiness gates; broader novice flow NOT RUN. Final rerun includes valid-empty and malformed-schema cases. Base: clean `v0.5.0` commit `260547e`; package output `0.6.0`. QA model: GPT-6 Luna.

## Acceptance criteria

| Gate | PASS when | FAIL when |
|---|---|---|
| Label semantics | A positive non-stale training judgment makes readiness eligible even if the current preview has no positive; validation-only positives, stale-only positives, grade-0-only rows, and pin-only rows do not. A positive rating remains valid when pinned. | Readiness depends on the current preview, counts validation as training, counts pins as grades, or accepts stale/zero-only labels. |
| Counts and scope | Training/validation graded and positive counts and stale count match tune's label-selection rules. Response is aggregate-only, identifies label readiness scope, and includes no document IDs, reasons, or connection data. | Counts include stale rows or pin-only rows, split assignments differ from tune, or private row/connection values leak. |
| Read-only boundary and store availability | `POST /api/concepts/tune/readiness` requires only the current concept; it does not query Elasticsearch or mutate concepts, versions, judgments, or runs. A missing configured DB, missing `judgments` table, or malformed `judgments` schema lacking `concept_id`, `query_id`, or `rating` is explicitly unavailable; a valid empty schema containing required and legacy-compatible columns returns confirmed zero counts. Old judgment schemas without `query_fingerprint` count rows as stale, matching the former empty-string migration default, without migration writes. | Missing or malformed storage is presented as confirmed zero, or a read request creates/migrates database state. |
| UI truth and race handling | UI displays separate training and validation aggregates, tells the novice to rate a saved training-query document as “조금 관련” or higher when no qualifying label exists, says Elasticsearch is checked when tuning runs, clears or marks obsolete results during concept edits and failed loads, and leaves `/api/concepts/tune` as the final truth. | UI presents eligibility as guaranteed tune success, retains stale readiness after an edit/error, or implies retrieval quality. |
| Regression | Existing full suite, browser acceptance, JavaScript/Python syntax, and isolated package/install/CLI gates pass as run. | Required run fails without a fix and rerun, or skipped evidence is reported as PASS. |

## Disposable API fixture

`tests/test_concept_tune_readiness.py` starts the workbench on a dynamically allocated loopback port with temporary SQLite databases. It creates only synthetic concept/query/document values and does not require Elasticsearch. The focused tests cover positive labels on a non-current train query, validation-only positive, stale positive, grade-0 and pin-only rows, positive pinned rating, split-specific counts, response privacy, database immutability across repeated readiness calls, legacy judgments without the fingerprint column, missing DB/table unavailability, a valid complete empty judgment table, and a nonempty malformed judgment table that must return unavailable without mutation.

No user database or credentials are read. Ports 8765 and 8766 are not used or modified.

## Execution evidence

| Gate | Status | Command, environment, result, boundary |
|---|---|---|
| API acceptance | PASS | `./.venv/bin/python -m unittest discover -s tests -p 'test_concept_tune_readiness.py' -v`; repository `.venv` Python 3.12.3; disposable SQLite databases and dynamically allocated loopback ports. 11 tests in 0.616s, `OK`. Covers all-positive/split/stale/pin cases; legacy schema without query fingerprint; absent DB/table returning HTTP 503 without file creation; malformed nonempty table missing `query_id` returning HTTP 503 with identical file bytes; and valid empty complete schema returning zero counts with unchanged file bytes. The endpoint body contains only `{concept}` and its handler calls aggregate readiness without a connection or Elasticsearch request. Seeded concepts, versions, judgments, and runs were unchanged across repeated readiness calls. |
| UI/browser | PASS, retained evidence | The UI/browser smoke on dynamic port `49025` is unchanged: only the backend read-only table-schema guard and test fixtures changed since that run. It covered training/validation counts, novice guidance, stale-response suppression, safe failure copy, and no Elasticsearch request. |
| Full suite | PASS | `./.venv/bin/python -m unittest discover -s tests -v` — 43 tests in 32.572s, `OK` (21 live Elasticsearch/provider, 11 mocked provider robustness, and 11 readiness acceptance), run against the exact source including the schema guard. Live provider/index results are bounded to this test environment; they do not guarantee provider availability or quota. |
| Syntax and whitespace | PASS | Node `v22.23.2`: `node --check es_rag_tuner/web/app.js`; Python `3.12.3`: `./.venv/bin/python -m py_compile tests/test_concept_tune_readiness.py tests/run_tune_readiness_fixture.py`; `git diff --check`. |
| Wheel/install/CLI | PASS | Rebuilt `es_rag_tuning_workbench-0.6.0-py3-none-any.whl` after the backend schema guard, verified METADATA `Name: es-rag-tuning-workbench`, `Version: 0.6.0`; installed in isolated venv `/tmp/es-rag-cycle5-final-wheel.SiE19J/venv` and ran `./venv/bin/es-rag-workbench --help` (exit 0). Wheel SHA-256: `bb1f7d6a9164415e1a4a1925a90b131863a49b7f383041c9efaf06d3d5e08641`. Exact build/install sequence follows below. |
| Broader novice flow | NOT RUN | This focused browser pass covered the readiness panel only; it did not run creation, preview, judgment, actual tuning/apply, and reload as a complete flow. |

## Iteration notes

The first focused run failed because the count fixture changed a query that also held a current grade-0 judgment, correctly making that row stale. The fixture now isolates stale evidence on its own query. An early browser attempt also triggered readiness before injecting its synthetic mapping into the page, producing an expected HTTP 400 from an empty `text_fields` payload. The final browser setup injects the mapping before loading the concept. Both were fixture corrections, not implementation failures. Review also found the original “empty table” fixture had only `concept_id`; after required-column validation was added, QA replaced it with a complete empty schema and added a nonempty table missing `query_id`, then reran the focused and full suites. The first package smoke used the base version `0.5.0` and was not accepted for Cycle 5 after review required a minor bump; the implementation updated both package version declarations to `0.6.0`, and the wheel/install/CLI gate passed on the rebuilt `0.6.0` artifact.

### Browser and package commands

The final browser run used the disposable fixture on `http://127.0.0.1:49025` and the Playwright wrapper at `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`. Fixture startup:

```text
./.venv/bin/python tests/run_tune_readiness_fixture.py
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh open http://127.0.0.1:49025
```

The page setup injected a synthetic `body` mapping before loading the concept so no mapping or Elasticsearch request was needed:

```text
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval '(async()=>{await loadConcepts();const concept=state.concepts[0];state.schema=[{name:"body",type:"text",searchable:true,nested:false}];state.schemaIndex="synthetic-index";populateConcept(concept);renderSchemaChoices(concept.corpus);updateTuneReadiness();await new Promise(r=>setTimeout(r,700));return JSON.stringify({detail:document.querySelector("#tune-readiness-detail").innerText,concept:collectConcept()})})()'
```

Race and error command:

```text
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval '(async()=>{const original=window.fetch.bind(window);let release;let blocked=false;window.fetch=async(input,init)=>{if(String(input).includes("/api/concepts/tune/readiness")&&!blocked){blocked=true;await new Promise(r=>release=r)}return original(input,init)};updateTuneReadiness();await new Promise(r=>setTimeout(r,350));const row=[...document.querySelectorAll(".concept-query-row")].find(x=>x.dataset.queryId==="train-other");row.querySelector(".saved-query-split").value="validation";row.querySelector(".saved-query-split").dispatchEvent(new Event("change",{bubbles:true}));await new Promise(r=>setTimeout(r,500));const edited=document.querySelector("#tune-readiness-detail").innerText;release();await new Promise(r=>setTimeout(r,100));const afterLate=document.querySelector("#tune-readiness-detail").innerText;window.fetch=async(input,init)=>String(input).includes("/api/concepts/tune/readiness")?new Response(JSON.stringify({error:"synthetic"}),{status:503,headers:{"Content-Type":"application/json"}}):original(input,init);updateTuneReadiness();await new Promise(r=>setTimeout(r,400));const failed=document.querySelector("#tune-readiness-detail").innerText;window.fetch=original;return JSON.stringify({edited,lateResponseIgnored:edited===afterLate,afterFailedRequest:failed})})()'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval 'JSON.stringify(performance.getEntriesByType("resource").map(x=>x.name).filter(x=>x.includes(":9200")||x.includes("/api/concepts/tune/readiness")))'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh console error
```

The race/failure check delayed one readiness response, changed the saved query split, confirmed the new ineligible result remained after releasing the old response, then injected a synthetic HTTP 503 and checked the generic unavailable message. Captured resource URLs contained three local readiness requests and no Elasticsearch URL. The fixture process and browser were stopped after the check.

Wheel/install command (temporary path from this run):

```text
qa_dir=/tmp/es-rag-cycle5-final-wheel.SiE19J
./.venv/bin/python -m pip wheel . --no-deps --wheel-dir "$qa_dir/wheels"
./.venv/bin/python -m venv --without-pip "$qa_dir/venv"
"$qa_dir/venv/bin/python" -m ensurepip --upgrade
"$qa_dir/venv/bin/python" -m pip install --no-deps --no-index "$qa_dir"/wheels/*.whl
(cd "$qa_dir" && ./venv/bin/es-rag-workbench --help)
```
