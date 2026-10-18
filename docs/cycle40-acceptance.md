# Cycle 40 weight behavior acceptance

**Checked:** 2026-10-18 (Asia/Seoul)
**Baseline HEAD:** `9a0d7755fa53bfd868ce13474bdb3ddd1c52e52b`
**Baseline tag:** `v1.2.0` at `9a0d7755fa53bfd868ce13474bdb3ddd1c52e52b`
**Package version checked:** `1.2.1`
**Runtime model identity:** **UNVERIFIED** (not exposed by the local test/runtime harness).

## Scope and evidence boundary

Cycle 40 adds backward-compatible `weight_behavior` metadata to `/api/knowledge/concept-preview`. API assertions cover its safe, term-free shape, positive magnitude invariance for local baseline and expanded results and metrics, separate zero gates, and defaults when legacy concepts omit weight settings. The browser fixture checks that the Korean summary presents saved values and counts, describes FTS5 numeric magnitudes as non-ranking, distinguishes local SQLite from Elasticsearch, and that the explicit preview flow makes no embedding, AI job/session, or tune calls.

The Python API tests run the local application with disposable account-local SQLite state. Browser tests intercept API responses with mocks while serving the static UI through an isolated loopback workbench. They establish UI behavior against the fixture, not a live service. No live Elasticsearch/provider integration, embedding execution, production readiness, representative retrieval quality, or broad quality claim was tested. Startup `/api/ai/status` remains an existing mocked capability check; the explicit local preview/ratings flow made no AI job/session calls. Graph/index/coverage tools were unavailable and were not used.

## Results

| Gate | Result | Evidence |
|---|---|---|
| C40 API acceptance | PASS | 13 tests; magnitude invariance, independent zero gates, missing-setting defaults, and safe metadata assertions included. |
| C38 knowledge API regression | PASS | 9 tests. |
| C37 auth API regression | PASS | 17 tests. |
| C40 browser flow | PASS | 14 mocked API requests; summary values/counts and SQLite/Elasticsearch distinction asserted; all routes fulfilled once. |
| C38 browser regression | PASS | 23 intercepted API requests. |
| C37 auth browser regression | PASS | 26 intercepted API requests; account, login/logout, storage, and revoked-session gates passed. |
| JavaScript syntax | PASS | `node --check` on the C39 browser harness and application JavaScript. |
| Python syntax | PASS | `compileall` on `es_rag_tuner` and the C40 API test. |
| Wheel build | PASS | Local no-dependency, no-isolation build produced the 1.2.1 wheel. |
| Live Elasticsearch, embedding, AI/provider behavior | NOT RUN | Outside this local FTS5 acceptance scope; no provider runtime was invoked. |

## Exact commands and environment

Python: `/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python` (Python 3.10.14, existing environment). Node: `v22.23.2`. Browser: Playwright from `/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules`, Chromium `/usr/bin/google-chrome`. No dependencies were installed.

```text
/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge_evaluation.py' -v
PASS — 13 tests, exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_knowledge.py' -v
PASS — 9 tests, exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m unittest discover -s tests -p 'test_cycle37_auth_acceptance.py' -v
PASS — 17 tests, exit 0.

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE39_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle39_knowledge_browser.js
PASS — 14 mocked API requests; browser summary assertions passed.

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE38_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle38_knowledge_browser.js
PASS — 23 intercepted API requests.

PYTHON=/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python NODE_PATH=/home/sra235/.npm/_npx/31e32ef8478fbf80/node_modules CYCLE37_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle37_auth_browser.js
PASS — 26 intercepted API requests.

node --check tests/cycle39_knowledge_browser.js && node --check es_rag_tuner/web/app.js
PASS — exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m compileall -q es_rag_tuner tests/test_knowledge_evaluation.py
PASS — exit 0.

/home/sra235/.pyenv/versions/3.10.14/envs/unsloth-env/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/cycle40-wheel
PASS — `es_rag_tuning_workbench-1.2.1-py3-none-any.whl`, SHA-256 `765ccba814347e8c2f95acb0d3f6b78b42f4a7cf20c067f24724d459dbc086fd`.
```

## Interpretation limits

Local FTS5 weight magnitudes are reported for inspection; only positive/zero eligibility gates inclusion of the corresponding expression group, and magnitudes do not affect local scores or ranks. Numeric boosts in the separate Elasticsearch workflow apply to its Elasticsearch corpus, which may differ from the account's private SQLite library. This is acceptance evidence for the local contract and test fixtures only. No runtime model identity was exposed, so it remains unverified.
