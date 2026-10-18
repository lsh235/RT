# Cycle 15 hybrid alias identity acceptance

## Scope and baseline

- Baseline: tag `v0.13.1`, commit `4fbc58e12488e21df9122b6ef4fe4627874b12d3` on `main`.
- Requested model: `gpt-6-luna`. Runtime identity is **UNVERIFIED**; no runtime metadata was supplied that proves the executing model.
- Scope: synthetic acceptance of `retrieval.search(mode="hybrid")` identity and reciprocal-rank fusion behavior, plus repository verification gates recorded below.
- This test uses deterministic in-process BM25/vector lane responses and a stubbed vector count. It does not contact Elasticsearch or an embedding provider.

## Result definitions

- **PASS**: the stated command completed with exit status 0 and its checks met the acceptance criteria.
- **FAIL**: the command completed but an assertion, build, install, or smoke check failed. Failures must be returned to implementation with the exact command and evidence.
- **NOT RUN**: the gate was not executed. It is not evidence of passing.

## Acceptance cases

`tests/test_hybrid_alias_identity_acceptance.py` invokes the public hybrid `retrieval.search()` function with deterministic lane stubs and checks:

1. Repeated `_id` values from `docs-000001` and `docs-000002` stay as two result identities, with only their originating lane scores attached.
   The hybrid `total` also counts the two concrete identities separately.
2. An identical `(index, id)` returned in both lanes fuses once, keeps both source scores, and receives `1/61 + 1/61` RRF score. Lane-only rank-2 candidates score `1/62` and retain deterministic stable order.
3. Hits without `_index` retain the existing empty-index fallback consistently across lanes and fuse as one identity.
4. Lane calls and vector count continue using the same saved alias, `docs-alias`.

## Source review

The prior Cycle 14 research note records the official Elasticsearch Search API response contract: each hit includes `_index`, the name of the index containing that document, so alias searches can return a concrete backing-index identity. Source: [Search API response](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html), accessed 2026-10-18. This is documentation evidence only; it is not validation against a live cluster.

## Verification record

Implementation readiness was explicitly reported before these gates ran. Results below refer to the current shared worktree; no files were staged, committed, or tagged by this QA work.

| Gate | Status | Command / evidence |
|---|---|---|
| Focused hybrid alias identity acceptance | **PASS** | `python3 -m unittest discover -s tests -p 'test_hybrid_alias_identity_acceptance.py' -v` — 3 tests passed. |
| Relevant vector/BM25/concept regressions | **PASS** | `python3 -m unittest discover -s tests -p 'test_vector_candidate_discovery_acceptance.py' -v` — 8 passed; `python3 -m unittest discover -s tests -p 'test_concept_tune_readiness.py' -v` — 12 passed; `python3 -m unittest discover -s tests -p 'test_vector_alias_compatibility_acceptance.py' -v` — 6 passed. |
| Full repository suite | **PASS (mixed local/live)** | `python3 -m unittest discover -s tests -v` — 112 tests passed, 1 skipped, exit 0. This was not fully offline: `tests/test_concept_live_acceptance.py` ran its live-ES fixture against its default endpoint because no `ES_RAG_ACCEPTANCE_ES_URL` override was set. Skip reason: optional tokenizer parity test requires an isolated fixture with four pinned tokenizer/config assets. |
| Static checks | **PASS** | `python3 -m py_compile es_rag_tuner/retrieval.py es_rag_tuner/server.py`; `node --check es_rag_tuner/web/app.js`; `git diff --check` — all exit 0. Python 3.12.3; Node version was not separately recorded. |
| System-Python wheel/install/CLI smoke | **PASS** | System Python 3.12.3, pip 24.0. In a temporary staging copy of `pyproject.toml`, `README.md`, and `es_rag_tuner/`, ran `python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <stage>/wheel <stage>/src`, then `python3 -m pip install --no-deps --target <stage>/install <stage>/wheel/es_rag_tuning_workbench-0.13.2-py3-none-any.whl`. Installed `es-rag-workbench --help` returned 0; installed CLI loopback `/api/health` returned HTTP 200 and `{"ok": true, "version": "0.13.2"}`. CLI process stopped and temporary staging directory removed. The repository `.venv/bin/python` resolves to `/usr/bin/python3`, so system Python was used directly. |
| Existing concept live-ES fixture | **PASS (limited)** | The suite contacted Elasticsearch at default `http://127.0.0.1:9200` (sanitized to loopback host/port); `LiveConceptAcceptance.setUpClass` requires an HTTP 200 root response with version metadata, then creates a unique `concept-accept-*` fixture, writes only its six synthetic documents, and deletes that fixture in `tearDownClass`. The suite exited 0, so teardown completed without error. No Elasticsearch version was retained in the test output. The default source-index `_count` check was attempted for `jira-grpc-issues-9-5-5`; the test catches lookup errors and emits no status, so its existence and whether its before/after fingerprint ran cannot be established from the recorded output. No source contents or fingerprint values are reported here. |
| Cycle 15 live hybrid alias behavior | NOT RUN | The full suite's live fixture does not exercise hybrid RRF with duplicate IDs across alias backing indices. No Cycle 15-specific live alias fixture was run. |
| Real FastEmbed/provider execution | NOT RUN | Synthetic tests stub retrieval lanes; they do not initialize an embedding model. |
| Browser/Playwright same-ID action flow | **PASS (synthetic)** | Served the UI using `python3 -m http.server 18765 --bind 127.0.0.1 --directory es_rag_tuner/web`; opened `http://127.0.0.1:18765/index.html` with `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`. A `run-code` flow injected two hybrid hits with `_id="duplicate"` at `docs-000001` and `docs-000002`, stubbed `/api/document` and `/api/explain`, then clicked the second hit's open and explain buttons. Captured calls carried `index="docs-000002"` and `id="duplicate"` for both routes; opened source summary was `source-docs-000002` and explanation text was `1.2000 — explain-docs-000002`. The first CLI attempt could not click because the fixture left the search panel hidden; activating the panel resolved this harness visibility issue, not a product failure. Browser closed and local static server stopped. |

## Evidence limits

The focused hybrid acceptance and browser flow are synthetic. The browser gate exercised the actual UI event handlers while intercepting document/explain APIs in-page; it did not run a persisted judgment flow or contact Elasticsearch. The full repository suite did contact the loopback Elasticsearch endpoint through the pre-existing `LiveConceptAcceptance` fixture, as detailed above; this is separate from Cycle 15 alias/RRF validation. The source index's availability/fingerprint outcome is uncertain from the recorded logs. No live Elasticsearch alias behavior or real embedding execution is claimed. Model identity remains **UNVERIFIED**.
