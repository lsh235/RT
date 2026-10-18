# Cycle 16 concept candidate pool acceptance

## Scope and baseline

- Baseline: `main`, `v0.13.2`, commit `928478a`.
- Requested model: `gpt-6-luna`. Runtime identity is **UNVERIFIED**; no runtime metadata proves the executing model.
- Acceptance is for the UI-only union of saved-query BM25 concept candidates and the bounded vector-candidate response. No backend route or database schema was added for the pool.
- Prior scope and evidence references: [Cycle 13 candidate-pool research](cycle13-candidate-pool-research-2026-10-18.md) and [Cycle 13 vector-candidates acceptance](cycle13-vector-candidates-acceptance.md). No new broad external research was performed.

## Source review

This cycle reuses the Cycle 13 official-source set, accessed **2026-10-18**: [Elasticsearch Search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search), [Elasticsearch kNN query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-knn-query), and [NIST's pooling limits study](https://www.nist.gov/publications/bias-and-limits-pooling-large-collections). Upstream facts describe bounded search/kNN behavior and the limits of judging a sampled pool. The product inference is that the UI may combine the already-supported BM25 and vector candidate responses while retaining per-mode provenance and labeling the result incomplete; upstream documentation does not validate this application's UI or imply exhaustive relevance. No new browsing was done because this iteration composes existing endpoints and adds no new upstream integration.

## Result definitions

- **PASS**: the named command or fixture completed with exit status 0 and all listed assertions held.
- **FAIL**: an assertion or check failed. The exact evidence is recorded; it is not reclassified as passing because the cause appears test-only.
- **NOT RUN**: the gate was not executed, or the test intentionally skipped. It is not evidence of passing.

## Synthetic acceptance

The browser fixture rendered BM25 and vector responses through the actual UI handlers using intercepted synthetic APIs. It exercised:

- Exact `(concrete index, document ID)` union: the same ID at `docs-a` and `docs-b` remained distinct; exact overlap at each index fused once.
- BM25-only, vector-only, and overlap provenance with their within-lane ranks. A vector-only row had no BM25/organic rank.
- A four-row pool bounded by `2 × size` for `size=3`, with no mutation to the BM25 result ranks or scores when candidates were combined.
- Exact query/index/document judgment payloads. A saved null remained JSON `null`; a saved zero remained numeric `0`.
- Vector request failure removed the combined pool, showed an error, and preserved the BM25 comparison.
- Delayed vector success and delayed vector error after an auth-field input change did not repopulate the pool, overwrite the context-change message, remove the BM25 comparison, or re-enable the stale request button.

## Verification record

Implementation readiness was reported before gates ran. The full suite was isolated from the default Elasticsearch endpoint with an explicit unreachable loopback URL. Other discovered HTTP fixtures use dynamic loopback servers; acceptance servers and concept databases use temporary directories. Provider/embedding execution paths are mocked or opt-in in the tests reviewed before the suite.

| Gate | Status | Command / evidence |
|---|---|---|
| Focused source-level pool acceptance | **PASS** | `python3 -m unittest discover -s tests -p 'test_concept_candidate_pool_acceptance.py' -v` — 4 passed. |
| Restored document-lookup scope-change regression | **PASS** | `python3 -m unittest tests.test_document_lookup_acceptance.DocumentLookupAcceptance.test_ui_clears_candidates_and_selected_target_on_scope_changes -v` — 1 passed after implementation restored the original direct listener registration and kept pool invalidation as a separate listener. |
| Existing vector and concept regressions | **PASS** | `python3 -m unittest discover -s tests -p 'test_vector_candidate_discovery_acceptance.py' -v` — 8 passed; `python3 -m unittest discover -s tests -p 'test_concept_tune_readiness.py' -v` — 12 passed. |
| Playwright CLI synthetic browser flow | **PASS (synthetic)** | Served `es_rag_tuner/web/` with `python3 -m http.server 18766 --bind 127.0.0.1 --directory es_rag_tuner/web`; opened through `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`. `run-code --filename /tmp/cycle16-pool-flow.js` rendered synthetic BM25/vector responses, clicked the actual pool and judgment controls, and injected immediate failure plus delayed success/error after auth input change. Captured rows: `docs-a/shared` BM25#1/vector#1; `docs-b/shared` BM25#2/vector#2; `docs-a/bm25-only` BM25#3/vector absent; `docs-c/vector-only` BM25 absent/vector#3/organic rank absent. Judgment requests preserved `(cycle16-pool,q16,docs-a,bm25-only,null)` and `(cycle16-pool,q16,docs-c,vector-only,0)`. Failure/stale checks passed. APIs were intercepted in-page; no ES or embedding provider was contacted. Temporary browser fixture script was removed. |
| Static checks | **PASS** | After the listener fix: `node --check es_rag_tuner/web/app.js`; `python3 -m py_compile tests/test_concept_candidate_pool_acceptance.py`; `git diff --check` — all exit 0. |
| Full repository suite | **PASS** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 python3 -m unittest discover -s tests -v` — 95 tests ran, 2 skipped, 0 failures, exit 0. The initial run before the listener fix had one failure at `tests/test_document_lookup_acceptance.py:388` because it expected the literal direct-listener registration. The exact regression then passed, and the complete suite passed after the fix. |
| Wheel, isolated install, and CLI smoke | **PASS** | Using `/usr/bin/python3` 3.12, copied only current `pyproject.toml`, `README.md`, and `es_rag_tuner/` into temporary staging, then ran `python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <temp>/wheelhouse <temp>/src` and `python3 -m pip install --no-deps --target <temp>/install-target <temp>/wheelhouse/es_rag_tuning_workbench-0.14.0-py3-none-any.whl`. Wheel SHA-256: `1133f1d8e07e5702d3f9afb6b3c570c40eb902dc63f6a9b656d97fa6cc847dd0`. With `PYTHONPATH=<temp>/install-target`, import verification reported `es_rag_tuner.__version__ == 0.14.0` and packaged `web/app.js` present; `<temp>/install-target/bin/es-rag-workbench --help` exited 0. No dependency resolution or application startup occurred; staging and install target were removed after verification. |
| Live Elasticsearch / saved-corpus access | **NOT RUN for Cycle 16** | The live suite class was skipped because the explicit URL `http://127.0.0.1:1` refused connection (`[Errno 111] Connection refused`). The second suite skip was the opt-in real-tokenizer parity test, which requires an isolated fixture of pinned tokenizer/config assets. No default or configured customer endpoint was used. |
| Real FastEmbed/model execution | **NOT RUN** | Candidate responses were synthetic; tests exercise stubs or require the opt-in local tokenizer asset fixture. |

## Evidence limits

The browser acceptance proves client behavior against deterministic synthetic API responses, not live Elasticsearch retrieval quality or persistent storage. The pool is a bounded sample, not a complete candidate set. Candidate display does not change BM25 ranks or evaluation metrics by itself; explicit grading uses the existing judgment route. Runtime model identity remains **UNVERIFIED**.
