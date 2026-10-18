# Cycle 41 acceptance: local match group cues

**Checked:** 2026-10-18 (Asia/Seoul)
**Baseline:** commit `cabcaa5bdd0a3531de1511b35104d3b9d34b9b54`, tag `v1.2.1`
**Package version:** `1.2.2` (local no-dependency wheel)
**Requested model:** `gpt-6-luna`; actual runtime identity **UNVERIFIED** by the local harness.

## Scope and evidence boundary

Cycle 41 adds an additive `matched_groups` list to returned private-knowledge preview hits. The accepted IDs are `saved_query`, `concept_expressions`, and `related_terms`. Baseline results carry only the saved-query ID. Expanded results are independently matched against each returned representative FTS row with the same literal-quoted expression builder as ranking. The labels respect positive group weights, per-related-row eligibility, excluded-term removal, document-level exclusion, and the existing result cap.

The API fixture covers query-only, concept-only, related-only, overlapping, title, and source-label matches, a nonmatching control, document exclusion, disabled and empty groups, and a long document whose returned representative chunk is checked independently against per-group SQLite FTS5 `MATCH` queries. A no-label comparison patches only the label attachment function and removes `matched_groups` before comparing full response projections. This verifies that IDs, order, ranks, scores, totals, metrics, and all other response fields are unchanged in the fixture. Metadata assertions allow only fixed IDs and ensure raw terms are absent.

The browser fixture returns separate baseline and expanded lane hits, verifies that their labels stay with their respective rank rows, checks the Korean lexical-cue/non-causal caveat, and retains text-safe rendering and provider-route guards. Browser responses are mocks; they establish presentation behavior only. The local API tests use the account-local SQLite/FTS5 test harness. No live Elasticsearch or vector index, embedding model, AI/provider request, automated tuning, production deployment, representative relevance set, or security audit was exercised. The startup `/api/ai/status` capability check remains part of the existing browser harness; the local preview and rating flow made no AI job/session, Elasticsearch concept, embedding, or tune calls. SQLite `MATCH` uses the configured tokenizer; separate group matches are used because generic FTS5 highlighting does not identify which OR branch matched ([SQLite FTS5 documentation](https://www.sqlite.org/fts5.html)).

## Results

| Gate | Result | Evidence |
|---|---|---|
| C41 / C39 API acceptance | PASS | 14 tests, including exact-representative-row group oracle and no-label full-response projection. |
| C40 weight API regression | PASS | Same API suite: weight metadata safety, magnitude invariance, zero gates, defaults, and C41 behavior passed. |
| C38 knowledge API regression | PASS | 9 tests. |
| C37 authentication API regression | PASS | 17 tests. |
| C41 / C39 browser acceptance | PASS | 14 mocked API requests; baseline/expanded badges, caveat, text safety, local-storage privacy, and provider-route checks passed. |
| C38 knowledge browser regression | PASS | 23 intercepted requests. |
| C37 authentication browser regression | PASS | 26 intercepted requests. |
| JavaScript syntax | PASS | `node --check` on C39 browser harness and application JavaScript. |
| Python syntax | PASS | `compileall` on application package and C39 API test. |
| Local wheel/version | PASS | No-dependency wheel build produced `es_rag_tuning_workbench-1.2.2-py3-none-any.whl`, SHA-256 `8cab47d6297e414c068c3ce424c93f4933473ac792eb5c65d939b9fe4568c7be`. |
| Live Elasticsearch, embeddings, AI/providers | NOT RUN | Outside this local FTS5 acceptance scope; no provider runtime was invoked. |

## Commands and environment

Python: `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python` (Python 3.10.14, existing environment). Node: `v22.23.2`. Browser: Playwright loaded from `/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules`, Chromium `/usr/bin/google-chrome`. No packages were installed.

```text
/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge_evaluation.py' -v
PASS — 14 tests, exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge.py' -v
PASS — 9 tests, exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_cycle37_auth_acceptance.py' -v
PASS — 17 tests, exit 0.

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE39_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle39_knowledge_browser.js
PASS — 14 intercepted API requests; baseline and expanded badge assertions passed.

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE38_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle38_knowledge_browser.js
PASS — 23 intercepted API requests.

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE37_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle37_auth_browser.js
PASS — 26 intercepted API requests.

node --check tests/cycle39_knowledge_browser.js && node --check es_rag_tuner/web/app.js
PASS — exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m compileall -q es_rag_tuner tests/test_knowledge_evaluation.py
PASS — exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/cycle41-wheel
PASS — `es_rag_tuning_workbench-1.2.2-py3-none-any.whl`; SHA-256 `8cab47d6297e414c068c3ce424c93f4933473ac792eb5c65d939b9fe4568c7be`.
```

## Limits

These badges indicate literal lexical matches on the hit's representative FTS5 row, not which terms caused its ranking, semantic relevance, or a relevance judgment. Coverage is limited to returned hits (at most 20 per lane); it does not describe unreturned matches or the entire corpus. Runtime model identity was not exposed and remains **UNVERIFIED**.
