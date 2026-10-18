# Cycle 43 private vector acceptance

## Scope and evidence boundary

Cycle 43 adds an explicit, account-private vector generation alongside existing BM25 sync/search. This acceptance used temporary SQLite databases, authenticated loopback requests, a fake loopback Elasticsearch HTTP server, deterministic tokenizer/embedding stubs, and mocked browser API responses. It did not contact a live Elasticsearch cluster, provider, or external model service. These results establish application behavior against the local fake protocol boundary; they are not live-cluster compatibility or retrieval-quality evidence.

Requested implementation model override: **gpt-6-luna**. Runtime identity is **UNVERIFIED**; the environment does not expose a model identity that QA can independently confirm.

The QA environment used Python 3.10.14 from `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python`, Node.js with Playwright from `/tmp/cycle42-playwright/node_modules`, and `/usr/bin/google-chrome`. The installed FastEmbed runtime was unavailable (`runtime_installed: false`; recipe value `fastembed_version: "not-installed"`). The pinned tokenizer files were not cached. No real embeddings or real E5 token counts were produced.

## Acceptance gates

| Gate | Result | Evidence and limits |
| --- | --- | --- |
| 1. BM25-only use without optional vector dependencies | **PASS** | C43 test blocks the embedding call and reports `vector_state=not_indexed` after BM25 sync; BM25 private search succeeds. No model or tokenizer download is attempted by BM25. |
| 2. Explicit vector action, consent, and safe generation publication | **PASS** | Missing `allow_model_download: true` is rejected before index creation. Missing tokenizer/model and partial bulk failure do not move the prior alias. The failure/retry assertions use fake ES and stubbed local dependencies. |
| 3. E5 recipe, mapping, and 512-token passage boundary | **PASS — fail-closed path** | Tests check exact `passage: ` / `query: ` formatting, 1024 dimensions, indexed `dense_vector`/cosine mapping, stored recipe including tokenizer revision and FastEmbed version, and complete source coverage across deterministic tokenizer-offset passages. When the pinned tokenizer is unavailable, sync fails with an actionable error before publishing a generation. The whitespace tokenizer stub exercises offset/chunk coverage only; because the real tokenizer cache was absent, no claim is made that real E5 tokenization was measured in this run. |
| 4. Owner filters, hybrid fusion, and separate lanes | **PASS** | Fake ES request bodies contain the authenticated owner term in BM25 and kNN pre-filter. Forged owner/index fields do not choose the account alias. Hybrid rank output checks `_score = 1/(60+rank)` across contributing lanes, named `retrieval_scores`, and `lane_ranks`. A simulated shared vector/mapping error returns `shared_search.state=unavailable` while private hybrid results continue; browser coverage distinguishes that from a successful empty shared search. C42 transport regression requires foreign vector/hybrid aliases to return 403 before fake ES is called. |
| 5. Empty, stale, missing-runtime, mapping, and retrieval-race handling | **PASS** | Tests cover empty state, stale pre-search state, an edit during retrieval, missing FastEmbed, missing tokenizer, over-limit query, incompatible mapping, recipe/version mismatch, and failed vector generation. These states return no private vector/hybrid hits. |
| 6. UI consent and status/result labels | **PASS** | Browser tests mock API responses. They check cancellation makes no vector-sync request, confirmed sync sends `allow_model_download: true`, BM25/vector/hybrid labels, private/shared lane separation, shared-unavailable versus successful-empty text, and that `code_rag` remains gated by shared vector readiness. |
| 7. Regression/build checks | **PASS** | Focused C42 private knowledge, C43 private vector, knowledge CRUD/evaluation, and auth suites passed. C42 and C43 browser smokes, Python compile, Node syntax/whitespace checks, and wheel build passed. Exact commands and counts are below. |

## Commands and results

All Python acceptance fixtures used temporary SQLite and fake loopback ES. No live endpoint or user private document was used.

- `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_cycle42_private_knowledge_acceptance.py' -v` — **PASS**, 16 tests. This includes explicit 403 assertions for foreign private vector/hybrid alias requests and verifies no fake ES request was made.
- `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_cycle43_private_vector_acceptance.py' -v` — **PASS**, 9 tests.
- `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge.py' -v` — **PASS**, 9 tests.
- `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge_evaluation.py' -v` — **PASS**, 14 tests.
- `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_cycle37_auth_acceptance.py' -v` — **PASS**, 17 tests.
- `NODE_PATH=/tmp/cycle42-playwright/node_modules CYCLE42_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python node tests/cycle42_private_knowledge_browser.js` — **PASS**, mocked API browser smoke; sync retry, empty/stale status, and separate result lanes.
- `NODE_PATH=/tmp/cycle42-playwright/node_modules CYCLE43_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python node tests/cycle43_private_vector_browser.js` — **PASS**, mocked API browser smoke; consent cancellation/confirmation, explicit download flag, mode labels, shared unavailable versus empty, and `code_rag` gate.
- `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m compileall -q es_rag_tuner && node --check es_rag_tuner/web/app.js && node --check tests/cycle42_private_knowledge_browser.js && node --check tests/cycle43_private_vector_browser.js && git diff --check` — **PASS**, no diagnostics.
- `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/cycle43-wheel-final` — **PASS**, built `es_rag_tuning_workbench-1.4.0-py3-none-any.whl`, 242,392 bytes, SHA256 `bfaa2fc50ade093b1a641084e97f1972efe8e6f879f4ee05d21dd4803d2ab432`.

## NOT RUN

- Live Elasticsearch dense-vector mapping, kNN pre-filter behavior, alias atomicity, and refresh visibility: **NOT RUN**; no disposable live ES cluster was configured for this acceptance.
- Real FastEmbed model loading/embedding, pinned tokenizer download/cache, and real 512-token passage counts: **NOT RUN**; FastEmbed was not installed and the tokenizer cache was absent. The fail-closed missing-tokenizer behavior passed. Synthetic tokenizer/embedding fixtures are not retrieval-quality evidence.
- Search relevance, ranking quality, external provider delivery, production credentials, load/soak, and production database durability: **NOT RUN**.

## QA-owned files

- Added `tests/test_cycle43_private_vector_acceptance.py` and `tests/cycle43_private_vector_browser.js`.
- Updated C42 private-knowledge assertions and browser mock expectations for the C43 empty/not-indexed states, while retaining the foreign-alias 403/no-ES assertion.
- No files were staged, committed, or tagged by QA.
