# Cycle 35 grouped mode comparison acceptance

## Scope and baseline

- Requested model: `gpt-6-luna`; runtime identity: **UNVERIFIED**.
- QA owns only `tests/test_concept_mode_comparison_group.py`, `tests/cycle35_group_mode_comparison_browser.js`, and this report.
- Group comparison contract: `POST /api/concepts/mode-comparison-group` takes a saved `concept_id` and anchor `query_id`; the server derives the normalized/casefolded information-need group and split from saved queries (2–10 members). It rejects blank/missing/out-of-range groups before Elasticsearch search and ignores caller retrieval/group overrides.
- Each saved query gets paired concept-applied BM25 and local E5 retrieval with the same alias, saved filters, and saved size. Rankings and metric joins use exact `(_index, _id)` identities. Only current, non-stale judgments for that query apply. Rating `0` remains graded; null is explicitly unjudged; pin state supplies no rank. Existing C34 judged-only metric definitions remain in force.
- Complete runs expose per-query status and equal-query macro means. nDCG and known-positive recall use only queries with positive grades; judged coverage uses queries with at least one graded judgment. Each metric/mode publishes its denominator; zero denominators produce null. If any query fails, counts and failures remain visible, safe successful paired rows may remain, and aggregate is null. Failures never become zero metrics or one-sided rows.
- No Elasticsearch/source writes, concept/judgment/run writes, or LLM/provider calls. Fixtures use a temporary SQLite database and mocked Elasticsearch with synthetic data only.

## Evaluation boundaries and source references

Sources reviewed 2026-10-18:

- Elastic's [Ranking evaluation API](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval) assigns ratings per test query and grounds them in that query's information need. This supports retaining exact saved-query judgments and reporting paired retrieval metrics per formulation.
- Elastic's [judgment lists guide](https://www.elastic.co/search-labs/blog/judgment-lists) describes a curated set of search queries with relevance ratings for corresponding results. This is evaluation-set context, not evidence that this fixture is representative.
- Microsoft's [RAG evaluators overview](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/rag-evaluators?view=foundry) separates document retrieval metrics from response-generation evaluation. This Cycle 35 fixture measures synthetic retrieval against saved judgments only; it does not evaluate generated answers.

These references motivate the contract and do not validate this implementation or establish search quality. No representative corpus, production judgment set, answer generation, or user study is part of this acceptance.

## Baseline check before implementation

Command:

```bash
./.venv/bin/python -m unittest tests/test_concept_mode_comparison_group.py -v
```

**Expected baseline absence confirmed:** endpoint returned HTTP 404 (`API 경로를 찾을 수 없습니다.`). The invalid-input/no-search test passed because every invalid request was rejected before mocked search. The four positive-contract tests failed at their initial expected HTTP 200 assertion. This is a feature-absence baseline, not a claim that grouped comparison behavior is implemented or accepted. Fixture corrections before this rerun removed duplicate judgment identities and removed assumptions that the API returns raw ranked IDs. Exact identity is now tested by giving the same `_id` different grades under two concrete indices and requiring the paired per-mode metric outcomes to differ; vector relevant recall is zero unless its ranking contains a known positive.

Browser fixture is staged but was not run against baseline: the group action is absent, so it cannot reach its interaction assertions. No full test suite or implementation files were touched. This corrected baseline run reported `Ran 5 tests`; one invalid-input/no-search test passed and four positive-contract tests failed only on expected HTTP 200 versus actual 404. Wait for coordinator implementation handoff before further runs.

## Acceptance gates after handoff

| Gate | Required evidence |
|---|---|
| Saved label isolation and normalization | Whitespace/case variants resolve to q1/q2/q3 from saved data; payload overrides do not change group or query text. |
| Read-only validation | Missing concept/anchor, blank/unlabeled group, singleton, 11-member group, and mixed-split saved group return errors with zero Elasticsearch calls. Blank and mixed-split cases use a controlled raw SQLite fixture because ordinary saved-concept validation strips blank labels and rejects mixed splits. DB table snapshots remain identical after successful, invalid, and partial-failure comparisons. |
| Paired retrieval | Each selected query issues one BM25 and one vector request using same saved alias/filter/size. Exact identities keep equal `_id` values in different indices distinct. |
| Judgment semantics | Current grade 0 is judged, null is unjudged, stale grade excluded, and a pinned positive is not inserted into either ranking. Per-query metrics match C34 semantics. |
| Macro denominator and partial failure | Exact per-query and equal-query macro values are checked for nDCG, judged coverage, and judged-relevant recall, including published denominators. Empty denominators are null. Any failed pair makes aggregate null; successful rows retain both modes and failed queries have no one-sided metrics. |
| Browser/UI | Keyboard activation, hostile saved query rendered as text, complete aggregate display, then a partial response with visible status/failure, no aggregate display, and paired successful row; no horizontal overflow at 390px; C34 single-query/tune actions remain present. The browser fixture verifies rendered state from synthetic API payloads; API pairing and failure counts are checked separately by the HTTP test. |
| Runtime boundary | Synthetic mocked ES and temporary DB only; no live corpus/profile/credential/provider access. |

## Post-patch results

All commands below ran after coordinator handoff against the Cycle 35 implementation. Synthetic API tests use a temporary SQLite file and mocked Elasticsearch; browser `/api/**` responses are intercepted. Runtime identity remains **UNVERIFIED**.

| Gate | Result and evidence |
|---|---|
| Focused Cycle 35 API acceptance | **PASS** — `./.venv/bin/python -m unittest tests/test_concept_mode_comparison_group.py -v`; `Ran 6 tests in 0.628s; OK`. Tests created a temporary database and bound an ephemeral local port. The fixture's Elasticsearch URL `http://127.0.0.1:1` was only a mocked connection value; requests were replaced by test doubles. |
| Browser fixture | **PASS (synthetic browser)** — local app started with `ES_RAG_CONCEPT_DB=/tmp/cycle35-browser.GlLTkw/concepts.sqlite3` at `http://127.0.0.1:18782/`; every `/api/**` response was intercepted by the fixture. Commands: `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle35qa open http://127.0.0.1:18782/` and `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle35qa --raw run-code --filename tests/cycle35_group_mode_comparison_browser.js`. Final fixture result: `PASS`; mobile viewport/body width both 390px; zero captured console errors and page errors. The first run exposed missing required synthetic response fields (`anchor_query_id`, `status`) and a broad assertion that matched the intentional “average hidden” notice; the fixture was corrected and rerun successfully. |
| C34 single-query comparison and tune-identity regression | **PASS** — `./.venv/bin/python -m unittest tests/test_concept_mode_comparison_acceptance.py tests/test_cycle34_tune_metric_identity.py -v`; `Ran 9 tests in 0.650s; OK`. |
| Full offline unittest suite | **PASS** — `env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 ES_RAG_CONCEPT_DB=/tmp/cycle35-offline.5c2Mv6/full-suite.sqlite3 ./.venv/bin/python -m unittest discover -s tests -v`; `Ran 116 tests in 8.069s; OK (skipped=2)`. The live Elasticsearch acceptance class skipped because the configured loopback endpoint refused connection. The tokenizer parity test skipped because its isolated pinned-asset fixture was not present. No live ES request was established. Two `ResourceWarning` messages about unclosed file objects appeared during vector candidate malformed-response tests; those tests and the full run completed successfully. |
| Python/JavaScript syntax and tracked diff whitespace | **PASS** — `node --check es_rag_tuner/web/app.js`; `node --check tests/cycle35_group_mode_comparison_browser.js`; `./.venv/bin/python -m py_compile tests/test_concept_mode_comparison_group.py es_rag_tuner/concepts.py es_rag_tuner/server.py`; `git diff --check`; all exited 0. |
| Isolated package build/install/import smoke | **PASS after QA harness correction** — Python `/usr/bin/python3` 3.12.3, pip 24.0. Full package source was copied to `/tmp/cycle35-package-full.oTpFbs/stage` with `pyproject.toml` and `README.md`; from that stage, `/usr/bin/python3 -m pip wheel --no-deps --no-build-isolation -w /tmp/cycle35-package-full.oTpFbs/wheelhouse .` built `es_rag_tuning_workbench-0.23.0-py3-none-any.whl` (SHA-256 `25c10ea441bcc2c1bddd64e9ca51c9cd2feb263d19ec945e0b5e3fbe2b4dd595`); `/usr/bin/python3 -m pip install --no-deps --target /tmp/cycle35-package-full.oTpFbs/install /tmp/cycle35-package-full.oTpFbs/wheelhouse/es_rag_tuning_workbench-0.23.0-py3-none-any.whl` succeeded. Exact final runtime assertion: `PYTHONPATH=/tmp/cycle35-package-full.oTpFbs/install CYCLE35_INSTALL_ROOT=/tmp/cycle35-package-full.oTpFbs/install/es_rag_tuner /usr/bin/python3 -c 'import os; import es_rag_tuner; from es_rag_tuner import server; from pathlib import Path; root=Path(os.environ["CYCLE35_INSTALL_ROOT"]); assert es_rag_tuner.__version__ == "0.23.0"; assert hasattr(server, "WorkbenchHandler"); assert (root/"web/index.html").is_file(); assert (root/"data/es_jira_index_mapping_and_tuning.json").is_file(); assert (root/"data/grpc_jira_issues_es_bulk.ndjson").is_file(); print("installed_version=0.23.0 server_import=PASS web_assets=PASS data_assets=PASS")'`. An initial smoke assertion used a placeholder install path and failed; the exact rerun passed. This validates local build/install/import only. |
| Live Elasticsearch, real corpus, model download, novice study | **NOT RUN** — outside the authorized synthetic/offline acceptance. |

Full isolated package staging/build/install/runtime commands (the wheel was built from the staged copy, not the working tree):

```bash
mkdir -p /tmp/cycle35-package-full.oTpFbs/stage /tmp/cycle35-package-full.oTpFbs/wheelhouse /tmp/cycle35-package-full.oTpFbs/install
cp pyproject.toml README.md /tmp/cycle35-package-full.oTpFbs/stage/
cp -a es_rag_tuner /tmp/cycle35-package-full.oTpFbs/stage/
cd /tmp/cycle35-package-full.oTpFbs/stage
/usr/bin/python3 -m pip wheel --no-deps --no-build-isolation -w /tmp/cycle35-package-full.oTpFbs/wheelhouse .
/usr/bin/python3 -m pip install --no-deps --target /tmp/cycle35-package-full.oTpFbs/install /tmp/cycle35-package-full.oTpFbs/wheelhouse/es_rag_tuning_workbench-0.23.0-py3-none-any.whl
PYTHONPATH=/tmp/cycle35-package-full.oTpFbs/install CYCLE35_INSTALL_ROOT=/tmp/cycle35-package-full.oTpFbs/install/es_rag_tuner /usr/bin/python3 -c 'import os; import es_rag_tuner; from es_rag_tuner import server; from pathlib import Path; root=Path(os.environ["CYCLE35_INSTALL_ROOT"]); assert es_rag_tuner.__version__ == "0.23.0"; assert hasattr(server, "WorkbenchHandler"); assert (root/"web/index.html").is_file(); assert (root/"data/es_jira_index_mapping_and_tuning.json").is_file(); assert (root/"data/grpc_jira_issues_es_bulk.ndjson").is_file(); print("installed_version=0.23.0 server_import=PASS web_assets=PASS data_assets=PASS")'
```

No commit or tag was created. The workspace contained other implementation/document changes outside QA ownership; those files were left untouched by this QA task.

## Final UI polish rerun

After the UI-only rendering change in `es_rag_tuner/web/app.js`, the requested targeted checks were rerun against the final source:

- `node --check es_rag_tuner/web/app.js` — **PASS**. The browser fixture also passed `node --check tests/cycle35_group_mode_comparison_browser.js` after adding explicit `status: "complete"` values to its synthetic query rows.
- Browser: started the local app with `ES_RAG_CONCEPT_DB=/tmp/cycle35-polish-browser.3d271j/concepts.sqlite3` at `http://127.0.0.1:18782/`, then ran `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle35-final open http://127.0.0.1:18782/` and `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle35-final --raw run-code --filename tests/cycle35_group_mode_comparison_browser.js` — **PASS**. The rendered successful query row contains `상태: 완료`; partial failure, paired metrics, aggregate suppression, and 390px layout checks also passed with zero fixture-captured console/page errors.
- Earlier focused API (**6 tests**), C34 comparison/tune identity (**9 tests**), full offline suite (**116 tests, 2 skipped**), and isolated package smoke remain valid: this polish changed only the UI renderer and the synthetic browser fixture; their Python source paths were unchanged.
