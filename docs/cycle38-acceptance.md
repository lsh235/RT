# Cycle 38 private knowledge acceptance

## Result

**Backend, mocked browser UI, and package checks: PASS for the checks run below.** These results cover isolated local HTTP, SQLite, and browser fixtures. They do not establish production security, multi-OS-user isolation, secure erasure, or Elasticsearch/provider behavior.

The configured model runtime identity was not exposed to this task; model identity is **unverified**.

## Environment and commands

- Checkout: `/home/sra235/2026/elasticsearch-rag`
- Python: `3.10.14` from `PYENV_VERSION=3.10.14/envs/unsloth-env`; system Python 3.12 lacked `argon2`, and `pytest` was not installed. The repository tests use `unittest`.
- Fixture: temporary SQLite state, two authenticated accounts (administrator and regular user), loopback HTTP server, and `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1`.
- `PYENV_VERSION=3.10.14/envs/unsloth-env python -m unittest discover -s tests -p 'test_knowledge.py' -v` — **PASS, 9 tests**.
- `PYENV_VERSION=3.10.14/envs/unsloth-env python -m unittest discover -s tests -p 'test_cycle37_auth_acceptance.py' -v` — **PASS, 17 tests**.
- `PYENV_VERSION=3.10.14/envs/unsloth-env python -c 'import unittest; loaded=unittest.defaultTestLoader.discover("tests", pattern="test_*.py"); cases=[]; walk=lambda suite: [walk(x) if isinstance(x, unittest.TestSuite) else cases.append(x) for x in suite]; walk(loaded); selected=[t for t in cases if t.__class__.__module__ != "test_concept_live_acceptance"]; print("offline selected tests:", len(selected), "excluded live module:", len(cases)-len(selected)); result=unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected)); raise SystemExit(not result.wasSuccessful())'` — **PASS, 142 tests, 1 skipped**; excluded the 21 tests in `test_concept_live_acceptance`.
- `PYENV_VERSION=3.10.14/envs/unsloth-env python -m compileall -q es_rag_tuner tests/test_knowledge.py` — **PASS**.
- `PYENV_VERSION=3.10.14/envs/unsloth-env python -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/cycle38-wheel` — **PASS**, wheel `es_rag_tuning_workbench-1.1.0-py3-none-any.whl`, SHA-256 `5253f960130123dc1cbed928d32a34a3255019a6b833e3ea5755275df20836f3`.
- `node --check tests/cycle38_knowledge_browser.js` — **PASS**.
- `NODE_PATH=/tmp/cycle37/node_modules CYCLE38_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome PYENV_VERSION=3.10.14/envs/unsloth-env node tests/cycle38_knowledge_browser.js` — **PASS**, Chrome `154.0.8037.97`, Playwright `1.64.1`, 22 mocked API calls, 14 knowledge API calls.

The first test attempt with system `python3` stopped before collecting tests because `pytest` and `argon2` were unavailable. The `unittest` suite was then run with the repository-compatible Python environment. An early API run also found that omitted and empty `source_label` values returned 400 despite the field defaulting to empty and being optional in the UI. The backend validation was corrected during the cycle; the retained regression now passes for both omission and an explicit empty value.

## Gate results

| Gate | Result | Evidence and boundary |
|---|---|---|
| Account isolation, admin scope, forged owner fields, foreign/unknown IDs | PASS | Two authenticated accounts can list/search/get only their own items. Supplying `owner_id` or `account_id` does not change scope. Foreign and unknown get/update/delete IDs return matching 404 status and bodies. |
| CRUD, chunk preview, ranking, index consistency, rollback, repeatable init | PASS | Create/update/delete and FTS result updates verified; literal query terms rank matching content and operator-shaped text does not execute as FTS syntax. Injected create/update/delete write failures leave prior document, chunk, and FTS rows intact. Repeated schema initialization and eight concurrent first opens/creates preserve one owner marker and exactly eight document/chunk/FTS rows. |
| Chunk and validation boundaries | PASS | Unicode code-point coverage, 200-code-point overlap, 1,800-code-point maximum, and UTF-8 byte accounting checked. Empty content, missing title, oversized source label, and 1 MiB + 1 byte document rejected. A 1 MiB document preview succeeds; its JSON request is below the server's 2 MiB request cap. Per-account byte quota and document-count enforcement checked with lowered test constants. |
| Auth, CSRF, and origin | PASS | Anonymous knowledge access rejected; invalid CSRF rejected; foreign origin rejected. Auth regression suite also passed all 17 tests. |
| Search without Elasticsearch; response content | PASS | Search and CRUD passed while `concepts.request` was patched to fail on any Elasticsearch call; configured endpoint was unreachable. Invalid/oversized-content responses did not include submitted document text. This validates the local route fixture only. |
| Browser import/paste, preview, save, list/open/search/edit/delete/logout, storage leakage | PASS for mocked UI flow | Real static UI ran in Chrome against deterministic mocked APIs. It imported `.md`, previewed and saved, listed/opened/searched, pasted and saved an edit, searched the edited text, deleted, and logged out. HTML-looking body text remained text (`<img>`/`<script>` elements were not created). Document text, filename, login password, session marker, and CSRF marker were absent from localStorage. API-level account isolation/IDOR evidence is separate in `tests/test_knowledge.py`; this browser fixture does not validate the real API or cross-account browser isolation. |
| Safe offline regression, static and package checks | PASS for selected offline coverage | The offline selection passed 142 tests with 1 existing skip; the 21 cases in `test_concept_live_acceptance` were excluded. The new 9-test knowledge suite and 17-test auth suite passed independently; Python compile, wheel build, and wheel contents check passed. Live Elasticsearch/provider checks were NOT RUN; no disposable Elasticsearch fixture was supplied for this acceptance pass. |

## Acceptance limits

- The HTTP server has a 2 MiB JSON body limit. The 1 MiB document boundary fits within it for the tested ASCII content; escaping can increase JSON size for some text, so the full nominal content boundary is not guaranteed for every encoding/body representation.
- The account isolation proof is within the application's account-resolved local SQLite storage and authenticated API. It does not protect against another local OS user or process with access to the data directory.
- The browser smoke mocks all `/api/**` routes and validates UI wiring and rendering only. It does not replace the separate authenticated API/IDOR tests or prove real backend integration in a browser.
- FTS5/BM25 behavior was checked only against small deterministic fixtures, not as a production relevance evaluation.
- SQLite deletion is not proof of secure erasure; WAL, backups, and snapshots can retain data.
