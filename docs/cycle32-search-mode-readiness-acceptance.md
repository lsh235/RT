# Cycle 32 search-mode readiness acceptance

## Scope and baseline

- Baseline: `main`, `v0.19.0`, commit `1935783e05413077b82b7a083579367c4b04d012`.
- Candidate: `v0.20.0`. An inline, state-driven readiness helper below Search mode should explain vector prerequisites for vector, hybrid, and code + Jira (`code_rag`), show partial vector coverage, and offer a shortcut to the existing embedding setup details. BM25 remains unaffected.
- The first vector-dependent query on an uncached local model must ask for explicit confirmation before it can cause the approximately 2.24 GB first-time model download. Mode changes, setup shortcuts, and cancellation must not send requests.
- QA owns this report and [`tests/cycle32_search_mode_readiness_browser.js`](../tests/cycle32_search_mode_readiness_browser.js). No product files are QA-owned.
- Requested QA model: `gpt-6-luna`; runtime model identity: **UNVERIFIED** unless independent evidence is available.
- Graph MCP is unavailable in this QA context. Bounded source checks and coordinator/research-agent notes are used; no graph coverage claim is made.

## Research evidence and product inference

Official Elastic documentation checked `2026-10-18`:

- [Dense vector field](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector): `dense_vector` fields store dense vectors and have a configured dimension.
- [kNN search](https://www.elastic.co/docs/solutions/search/vector/knn) and the [kNN query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-knn-query): vector queries require a compatible vector field and query vector dimensions; kNN scores documents with values for the queried vector field.
- [Exact kNN](https://www.elastic.co/docs/solutions/search/vector/knn/exact-knn): exact kNN scores the documents considered by the query against their vector values.
- [Hybrid search](https://www.elastic.co/docs/solutions/search/hybrid-search) and [Reciprocal rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion): hybrid search combines lexical and vector result lists; RRF merges ranked lists.

A matching vector dimension alone does not prove that stored document vectors were produced by the same embedding model as a query vector. The readiness UI should report observable local prerequisites and coverage, bounded to the latest connection, without implying vector/model identity or retrieval quality.

Product inference: a concise readiness hint near Search mode may help users recognize known prerequisites before a vector-dependent request. The setup shortcut and explicit download confirmation may make the existing local-model setup easier to find while keeping first-time download under user control. Elastic documentation does not establish a novice usability benefit; user study is **NOT RUN**.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| BM25 remains usable and unaffected across readiness states | **PASS** | Synthetic fixture ran BM25 against missing mapping, dimension mismatch, absent runtime, zero vectors, and unknown vector count. Each request kept the exact `cycle32 exact query` and selected index. |
| Readiness updates on mode and selected-index/connect changes | **PASS** | BM25 hides the helper; vector modes show the polite status. The real index-change handler reconnects and reports the latest selected index. Disconnection after editing the endpoint was not retained in the final fixture. |
| Missing/mismatched vector mapping, missing FastEmbed runtime, zero vectors, and unknown vector count block vector/hybrid/code_rag with zero search requests | **PASS** | For each synthetic blocked state, all three modes produced no `/api/search`, `/api/code-rag`, or `/api/vectorize` request. Copy did not promise the first-query download while known prerequisites were blocked. |
| Setup shortcut only expands/focuses existing embedding-status details; mode switch and shortcut make no API request or persistence write | **PASS** | Enter on `[data-open-embedding-setup]` opened the existing details and moved focus inside it. Search state, filters, saved grade, result markup, local/session storage were unchanged. Mode selection also left requests and storage unchanged. |
| Partial N/M vector coverage is explicit; hybrid and code_rag explain their vector dependency | **PASS** | Synthetic 3/10 status restricted vector candidates to 3 documents. Hybrid names vector and lexical lanes; code_rag names the Jira vector/lexical paths and separate code candidates. |
| Ready status is bounded to the latest connection and states stored-vector model identity is unknown | **PASS** | Synthetic ready index reported 10/10 and referred to the latest connection; copy says stored-vector model origin and compatibility are unknown. |
| Uncached local-model confirmation names the ~2.24 GB first-query download; cancel sends no request, accept sends exactly one intended search request | **PASS WITH LIMIT** | Test shim recorded the exact `window.confirm` prompt. Cancel caused no search/vectorize request; accept caused one vector search preserving query and index. Playwright CLI auto-handles native modal dialogs, so native modal appearance itself is **NOT VERIFIED**. |
| Query, index, mode/settings, grades/result order, keyboard use, live status semantics, and 1280px/390px layout remain intact | **PASS WITH LIMIT** | Fixture checked exact request query/index, preservation snapshots, Enter activation of setup shortcut, status semantics, and no horizontal overflow at 1280 and 390 pixels. It did not separately keyboard-activate the search button. |
| Browser fixture, JavaScript syntax, `git diff --check`, 101+ offline suite, isolated v0.20.0 wheel/module/page/CLI smoke | **PASS** | Browser fixture passed; JS syntax and diff checks passed; offline suite ran 101 tests with two expected skips; isolated wheel/module/page/CLI smoke passed. Exact commands and environment are below. |
| Live Elasticsearch/provider, actual model download, screen reader, corpus quality/user study | **NOT RUN** | Synthetic browser responses and isolated package checks only. No live Elasticsearch/provider, real model download, screen-reader audit, corpus-quality assessment, or user study was performed. |

## Commands and environment

Implementation-ready signal received from coordinator before final gates. QA ran on Linux 6.18.54.1-microsoft-standard-WSL2, Node `v22.23.2`, Python `/usr/bin/python3` `3.12.3`, Playwright CLI `0.1.22`; requested model `gpt-6-luna`, runtime model identity **UNVERIFIED**.

Commands:

```bash
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle32g open http://127.0.0.1:18777/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle32g --raw run-code --filename tests/cycle32_search_mode_readiness_browser.js
node --check es_rag_tuner/web/app.js
node --check tests/cycle32_search_mode_readiness_browser.js
git diff --check
env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v
```

The offline suite result was `Ran 101 tests in 6.810s; OK (skipped=2)`. Expected skips were the live Elasticsearch acceptance setup (loopback port 1 refused the connection) and the opt-in real tokenizer test (no pinned tokenizer fixture supplied). The suite emitted two Python `ResourceWarning`s for unclosed test HTTP fixture files; there were no failures.

The isolated v0.20.0 package smoke used a temporary staging copy containing only `pyproject.toml`, `README.md`, and `es_rag_tuner/`; `/usr/bin/python3 -m pip wheel --no-deps --no-build-isolation` built `es_rag_tuning_workbench-0.20.0-py3-none-any.whl`, SHA256 `072ea4ef32c56c81d2c96e485ba27dcf632bd7298edf28cbfaa1ab3831c467bc`. It installed with `pip install --no-deps --target`, verified module version and packaged HTML/JS/CSS plus readiness hook, ran `python -m es_rag_tuner --help`, then launched the isolated package on port `18778` with a temporary SQLite path and checked `GET /` and `GET /api/health` (200, v0.20.0). Both package smoke commands exited 0.

Browser fixture endpoint calls were intercepted; the page was served locally on port `18777` in a separate `cycle32g` session. The final fixture returned `consoleErrors: []`, desktop viewport `1280/1280` and mobile viewport `390/390` document/body widths, zero code-rag/vectorize calls, and the expected BM25/vector search-call list. Live Elasticsearch/provider and actual model download were not contacted.

## Run notes and limitations

- Fixture contract: `#search-mode-readiness[role="status"][aria-live="polite"]` and `[data-open-embedding-setup]`, with all `/api/**` calls intercepted. Since the Playwright CLI auto-handles native modal dialogs, the fixture shims `window.confirm` to record exact prompt text and deterministically return cancel/accept. This verifies the production call boundary and request gating, but not browser-native modal appearance.
- Existing setup details are within the collapsed `.sample-maintenance` disclosure. The helper shortcut must only open/focus that existing section.
- The baseline UI does not expose stored vector model identity. Readiness must not claim that the stored vectors and query vectors use the same model.
- Initial fixture corrections: the search panel was hidden on page load, so the fixture now opens the Search tab. A mode-change check initially overlapped asynchronous post-connect `concepts/runs`, `ai/status`, and `quickstart` refresh calls; the fixture now waits for the connect button to re-enable after the real index-change connection. A filtered request counter was also corrected to compare vector counts against prior vector counts rather than total searches. The Playwright CLI's automatic native-dialog handling conflicted with a page dialog listener; deterministic `window.confirm` shimming resolved the harness conflict. One early pass with the native-dialog listener exited successfully while leaving a modal reported by the CLI; it is superseded by the final clean shimmed pass.
- The QA fixture and report are the only QA-owned files. No commit, tag, or push was made. Unrelated existing untracked review documents were left untouched.
