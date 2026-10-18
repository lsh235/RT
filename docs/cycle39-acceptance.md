# Cycle 39 private knowledge acceptance

**Checked:** 2026-10-18 (Asia/Seoul)
**Baseline:** commit `a0bfa46`, tag `v1.1.0`
**Runtime model identity:** **UNVERIFIED**.

## Scope and evidence boundary

Acceptance covers authenticated saved-concept/query preview against the current account's private SQLite FTS5 corpus and separate local document ratings. It exercises saved scope, literal term handling, ranking and document deduplication, current versus stale judgments, metrics, and corpus fingerprints. The browser flow intercepts API requests with mock responses; it is UI behavior evidence only. The Python API suite uses the local application/database test harness. None of these checks establishes Elasticsearch, vector, embedding, AI-provider, production-security, or automated-tuning behavior.

## Results

| Gate | Result | Evidence |
|---|---|---|
| C39 API acceptance | PASS | 10 tests passed; includes explicit 400 rejection for more than 200 unique query terms with no partial result payload. Saved scope/auth, FTS behavior, exclusions, deduplication, ratings/metrics, staleness, fingerprints, and validation covered. |
| C38 knowledge API regression | PASS | 9 tests passed. |
| C37 auth API regression | PASS | 17 tests passed. |
| C39 browser flow | PASS | 14 intercepted API requests; one error-button click led to exactly one preview request/404. All mock routes fulfilled once. |
| C38 browser regression | PASS | 23 intercepted API calls; private-library workflow and browser privacy checks passed. |
| C37 auth browser regression | PASS | Account create/login/logout, storage, and revoked-session 401 checks passed. |
| JavaScript syntax | PASS | `node --check` on the C39 browser script and app JavaScript. |
| Python syntax | PASS | `compileall` for application package and C39 API test. |
| Wheel build | PASS | Local wheel built without dependency installation or build isolation. |
| Elasticsearch/vector/AI/provider behavior | NOT RUN | Outside the feature's local FTS5 acceptance scope. |

The C39 mock-browser request sequence was: `GET /api/auth/session 200`, `POST /api/auth/login 200`, `POST /api/admin/accounts/list 200`, `GET /api/health 200`, `GET /api/codebase-status 200`, `POST /api/concepts/list 200`, `POST /api/knowledge/list 200`, startup capability check `POST /api/ai/status 200`, then three successful `POST /api/knowledge/concept-preview 200` requests associated with initial preview and the two ratings, two `POST /api/knowledge/judge 200` requests for grades `0` and `3`, and one deliberate `POST /api/knowledge/concept-preview 404` for the error-state UI. The `ai/status` request is a startup capability check; the explicit preview/rating flow made no AI session/job or Elasticsearch concept preview/tune route calls. The mocked browser confirmed text-safe rendering and no document/auth sentinels in localStorage. These statements describe the test fixture and observed browser behavior only.

The error-flow diagnostic was taken after waiting for both judge requests, all three successful preview responses, the re-rendered grade `3`, and success feedback. Immediately around the single error-button click, exactly one preview fetch was observed, with one route event at `2026-10-18` test runtime, resource type `fetch`, the loopback page frame, and no redirects. The browser fetch stack was `api` → `HTMLButtonElement.runKnowledgeEval`; one `page.route("**/*", ...)` was registered and each of 14 intercepted requests was fulfilled exactly once. The initial report of two 404s was due to taking the error-flow baseline before the grade-3 refresh had fully completed; it was not a product duplicate-fetch finding.

## Exact commands and environment

Python interpreter: `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python` (Python 3.10.14, with the project's already-installed `argon2-cffi`). Browser tooling: Node.js with Playwright loaded from `/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules`; Chromium executable `/usr/bin/google-chrome`. No dependencies were installed. The project `.venv` and system Python 3 lacked `argon2`; environment discovery found the existing Python 3.10.14 environment, so all Python acceptance commands used it.

Commands and results:

```text
/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge_evaluation.py' -v
PASS — 10 tests, exit 0, 1.391 s; includes `test_preview_rejects_more_than_200_unique_query_terms_without_partial_results`

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge.py' -v
PASS — 9 tests, exit 0, 1.502 s

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_cycle37_auth_acceptance.py' -v
PASS — 17 tests, exit 0, 3.052 s

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE39_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle39_knowledge_browser.js
PASS — exit 0; 14 intercepted API calls, 7 knowledge calls, one deliberate preview 404; one page route, one fulfillment per request

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE38_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle38_knowledge_browser.js
PASS — exit 0; 23 intercepted API calls, 14 knowledge calls

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE37_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle37_auth_browser.js
PASS — exit 0; 26 intercepted API calls

node --check tests/cycle39_knowledge_browser.js && node --check es_rag_tuner/web/app.js
PASS — exit 0

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m compileall -q es_rag_tuner tests/test_knowledge_evaluation.py
PASS — exit 0

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/cycle39-wheel-rerun
PASS — exit 0; es_rag_tuning_workbench-1.2.0-py3-none-any.whl, SHA-256 d23ca149862fc0c4508622edcce6aba4f5c359ba0dbce44c0bc9d46826b63bad (written to `/tmp/cycle39-wheel-rerun`)
```

The first attempt to import/run the C39 suite with `.venv/bin/python` stopped before tests because `argon2` was unavailable; no test case ran. The existing Python 3.10.14 environment was used instead, without installing packages. The first focused C39 run then exposed a QA fixture defect: its foreign test account was created with one password but the authenticated client used another. After aligning the fixture password, the focused suite passed 9/9. Initial C39 browser attempts also exposed fixture/assertion issues (mock `json()` did not fulfill the route; an `<option>` visibility expectation; expected generic rather than product-specific 404 copy; and an overly broad startup AI capability check). These were corrected in the owned test fixture. The first duplicate-request diagnostic captured an incompletely synchronized regrade; the corrected synchronization above established one request for the one click. No unresolved test failure remains in the listed gates.

## Interpretation limits

FTS5 scores are local, corpus-dependent BM25 ranking values; smaller values rank ahead, and values are not probabilities or directly comparable with Elasticsearch scores. Metrics summarize only current user judgments for the selected saved query/result lists. Unjudged documents are omitted from judged-only nDCG positions rather than treated as grade zero; explicit grade `0` remains a judgment. Query split is context only. These checks do not establish generalization, representative judgments, retrieval quality beyond the fixture/test corpus, downstream answer quality, or security against production threats. Runtime model identity remains **UNVERIFIED**.
