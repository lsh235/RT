# Cycle 37 local account acceptance

## Scope and evidence boundary

Cycle 37 adds a local account/password boundary around existing saved workbench state. The acceptance target is the stated Cycle 37 contract: loopback-only first-admin bootstrap; opaque HttpOnly sessions; CSRF and Origin checks; active-session authentication for business APIs; admin account management; owner-scoped concepts, versions, judgments, runs, exports, AI sessions, and jobs; and a data-preserving, rerunnable legacy ownership migration.

Private knowledge-document CRUD, Elasticsearch document indexing, and enforced assignee filters over external BM25/vector/hybrid corpora are deferred to the next cycle. This report does not claim those capabilities. All executable fixtures must use temporary SQLite data and mocked Elasticsearch/provider behavior. No live Elasticsearch, provider, credentials, `.env`, or persistent user database is part of this acceptance.

Security references below are implementation guidance, not empirical security proof or a substitute for a security review. Passing local tests does not prove deployment security, browser hardening, or production readiness.

## Baseline

Baseline source: `main` at `6840ce49d292c2cee71f2ae3f48861b9e2c59f05`, version `0.23.1`.

Test-first artifact: `tests/test_cycle37_auth_acceptance.py`. It starts `WorkbenchHandler` on an ephemeral loopback port with a uniquely named temporary SQLite path, then asserts the pre-bootstrap `/api/auth/session` response. Baseline result is an **expected failure** because the endpoint does not exist yet.

Exact command:

```text
python3 -m unittest -v tests/test_cycle37_auth_acceptance.py
```

Environment: repository `/home/sra235/2026/elasticsearch-rag`; `python3 --version` reports `Python 3.12.3`; test-owned temporary directory; `ES_RAG_CONCEPT_DB` points to that directory's `synthetic.sqlite3`; `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1`; HTTP listener binds an OS-assigned `127.0.0.1` port. No ES request is made by this baseline test.

Exact output:

```text
test_session_endpoint_reports_unconfigured_before_bootstrap (tests.test_cycle37_auth_acceptance.Cycle37AuthBaseline.test_session_endpoint_reports_unconfigured_before_bootstrap) ... 127.0.0.1 - - [18/Oct/2026 12:29:55] "GET /api/auth/session HTTP/1.1" 404 -
ERROR

======================================================================
ERROR: test_session_endpoint_reports_unconfigured_before_bootstrap (tests.test_cycle37_auth_acceptance.Cycle37AuthBaseline.test_session_endpoint_reports_unconfigured_before_bootstrap)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/sra235/2026/elasticsearch-rag/tests/test_cycle37_auth_acceptance.py", line 43, in test_session_endpoint_reports_unconfigured_before_bootstrap
    with urllib.request.urlopen(self.base + "/api/auth/session", timeout=5) as response:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 215, in urlopen
    return opener.open(url, data, timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 521, in open
    response = meth(request, response)
               ^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 630, in http_response
    response = self.parent.error(
               ^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 559, in error
    return self._call_chain(*args)
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain
    result = func(*args)
             ^^^^^^^^^^^
  File "/usr/lib/python3.12/urllib/request.py", line 639, in http_error_default
    raise HTTPError(req.full_url, code, msg, hdrs, fp)
urllib.error.HTTPError: HTTP Error 404: Not Found

----------------------------------------------------------------------
Ran 1 test in 0.514s

FAILED (errors=1)
```

The baseline has no implementation findings beyond the directly observed missing session endpoint. The current route inventory was reviewed in `es_rag_tuner/server.py`: GET supports health, token-preview status, and codebase status; POST exposes the current workbench, concept, and AI endpoints. No auth/bootstrap route was present at this baseline.

After adding the protected-route inventory assertion, the same command was rerun against the unchanged implementation. This is a second **expected baseline failure**. The test patched each existing handler method, so it made no Elasticsearch/provider calls and avoided workbench-state side effects. It observed 41 existing business POST routes returning HTTP 200 anonymously, the three not-yet-implemented admin routes returning HTTP 404, and private GET `/api/token-preview/status` and `/api/codebase-status` returning HTTP 200. `/api/health` returned HTTP 200. Result: `Ran 2 tests in 0.547s`, `FAILED (failures=1, errors=1)`. An isolated rerun of the inventory assertion reported `Ran 1 test in 0.546s`, `FAILED (failures=1)`; its failure summary counted 46 failures to deny (41 current POST routes, three absent admin routes, and two private GETs). The separate session test remains `urllib.error.HTTPError: HTTP Error 404: Not Found`. The exact original single-test baseline output above is retained unchanged.

## Test and fixture plan

The API fixture will use an ephemeral loopback listener and a per-test temporary SQLite database. It will mock external Elasticsearch and provider calls. The test plan covers:

1. Every route in the captured route inventory fails closed for an unauthenticated caller, with health as the only minimally public endpoint; private GETs return no data.
2. Two accounts cannot list, read, update, restore, or export each other's concepts, versions, judgments, or runs, including guessed IDs and forged request owner IDs. Ownership is derived from the authenticated principal.
3. AI session history/reset and AI job read/cancel remain bound to their owning account.
4. Missing or foreign CSRF tokens, wrong Origin, expired/revoked sessions, and disabled-account sessions are rejected.
5. Invalid-login errors are generic and repeated failures are throttled.
6. First-admin bootstrap is loopback-only, single-use, and race-safe; login/logout/password change, admin account list/create/disable work; the last enabled admin cannot be disabled; password/hash fields never appear in responses.
7. Legacy concepts, versions, judgments, and runs are preserved and assigned only to the first bootstrap admin; rerunning migration leaves them unchanged.
8. C34/C35/C36 API and browser regression fixtures remain executable after auth fixture updates.
9. Browser coverage starts from `about:blank`, binds a unique temporary database and local port, installs a `**/*` route before navigation, and mocks every `/api/**` request. It exercises login, authenticated UI, logout, admin controls, and confirms no password/session/CSRF token in localStorage.

At handoff, tests will record exact commands, environment, exit status, output, and every NOT RUN gate. Planned offline checks include `node --check`, Python compilation, isolated wheel build/install/import, and the full safe offline suite when implementation is ready. No check will be reported PASS if it was not run.

## Security guidance sources

- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [argon2-cffi PasswordHasher API](https://argon2-cffi.readthedocs.io/en/stable/api.html)

These sources inform the test expectations (authorization per object/action, generic authentication failures, slow password hashing, synchronizer-token/Origin defenses, and protected session identifiers). They do not establish that this application is secure.

## Implementation and final QA results

### Backend acceptance: first implementation run

Environment: Python 3.12.3; system Python and repository `.venv` did not have the declared `argon2-cffi` dependency. Installed `argon2-cffi==25.1.0` and its wheel dependencies into `/tmp/cycle37-qa-deps` only; no repository or persistent environment files were changed. The acceptance fixture uses its own temporary SQLite path and a loopback HTTP listener. ES URL is the closed local sentinel `http://127.0.0.1:1`; provider, ES validation, and AI worker submission are mocked in the tests that exercise those paths.

Exact command:

```text
PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests/test_cycle37_auth_acceptance.py
```

Result: **FAIL**, `Ran 17 tests in 2.926s`, `FAILED (failures=2)`. Fifteen tests passed, including the anonymous route inventory, login/session and account controls, CSRF/Origin/expiry/disable/last-admin checks, login throttling, response/log secrecy, AI owner checks, CLI bootstrap/recovery, and legacy migration checks. Two failures need implementation follow-up:

- `Cycle37AuthAPI.test_concurrent_secondary_database_initialization_is_owner_marked` (`tests/test_cycle37_auth_acceptance.py:414`): simultaneous secondary DB initialization returned `OperationalError('database is locked')`; expected both connections to initialize with exactly one owner marker.
- `Cycle37AuthAPI.test_two_account_concepts_versions_judgments_runs_and_exports_are_isolated` (`tests/test_cycle37_auth_acceptance.py:472`): first concept save returned HTTP 500, `{"error": "내부 오류: cannot start a transaction within a transaction"}`. Current source inspection points to `_connect_db()` opening `BEGIN IMMEDIATE` while creating the owner marker and holding it through the yielded connection, followed by `save_concept()` opening another transaction. This is an implementation finding; the test remains unchanged.

The initial attempt before installing the declared dependency used `python3 -m unittest -v tests/test_cycle37_auth_acceptance.py` and exited 1 before running tests with `ModuleNotFoundError: No module named 'argon2'`. This is an environment dependency gap, not an acceptance assertion result.

Safe AI regression command, after updating its direct internal calls to use an explicit `owner_id`:

```text
PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests.test_ai_robustness
```

Result: **PASS**, `Ran 11 tests in 0.005s`, `OK`. No provider or Elasticsearch calls were made.

Browser tests, C34/C35/C36 browser regression, and the full safe offline suite: **NOT RUN** pending resolution of the two backend failures and UI handoff. No live Elasticsearch/provider test was run.

### Static and packaging checks

These checks ran with the implementation state from the backend acceptance run above. They do not replace the failing API assertions.

| Exact command | Result |
| --- | --- |
| `node --check tests/cycle37_auth_browser.js` | **PASS**, exit 0, no output |
| `node --check tests/cycle34_mode_comparison_browser.js && node --check tests/cycle35_group_mode_comparison_browser.js && node --check tests/cycle36_group_comparison_readiness_browser.js` | **PASS**, exit 0, no output |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m compileall -q es_rag_tuner tests` | **PASS**, exit 0, no output |
| `python3 -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/cycle37-wheel` | **PASS**, exit 0; built `es_rag_tuning_workbench-1.0.0-py3-none-any.whl`, SHA-256 `63880a29ac420885d6b9bdc7daa522d570244644f009770acf52049d910a06d5` |
| `python3 -m pip install --no-deps --target /tmp/cycle37-wheel-install /tmp/cycle37-wheel/es_rag_tuning_workbench-1.0.0-py3-none-any.whl` | **PASS**, exit 0 |
| `cd /tmp && PYTHONPATH=/tmp/cycle37-wheel-install:/tmp/cycle37-qa-deps python3 -c 'import es_rag_tuner; from es_rag_tuner import auth, server; print(es_rag_tuner.__version__)'` | **PASS**, exit 0; printed `1.0.0` |

Wheel build/install/import used `/tmp` outputs and the isolated dependency target; it did not install into the active Python environment or alter project build artifacts intentionally.

### Final offline acceptance rerun

The initial implementation-run failures above are historical and were resolved before this final run. The shared API fixtures now bootstrap an isolated admin for each test and attach the session cookie, same-origin Host/Origin, and CSRF token for authenticated POSTs. Assertions were kept intact. The separate bounded production fix in `es_rag_tuner/concepts.py` makes readiness reads resolve the server-bound owner database while retaining read-only behavior.

Environment for these runs: Python 3.12.3; Node.js 22.23.2; Playwright 1.61.1 from the Codex runtime; `/usr/bin/google-chrome`; `PYTHONPATH=/tmp/cycle37-qa-deps`; unreachable ES sentinel `http://127.0.0.1:1`; each HTTP/browser fixture created its own temporary SQLite DB and ephemeral loopback port. Browser fixtures started at `about:blank`, installed the API interception before application navigation, and returned synthetic responses for every `/api/**` request. No real ES/provider, `.env`, credentials, or persistent user database was used.

| Exact command | Result |
| --- | --- |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests/test_cycle37_auth_acceptance.py` | **PASS**, 17 tests in 3.014s (final isolated rerun). Includes anonymous route inventory/private GET denial, two-account owner/IDOR checks for saved state and AI sessions/jobs, CSRF/Origin/expiry/disable handling, login throttling/generic errors, bootstrap and recovery, admin lifecycle/last-admin guard, password change, legacy migration/rerun, concurrency, type validation and secret/log checks. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests.test_ai_robustness` | **PASS**, 11 tests. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests.test_concept_information_need_preview_acceptance tests.test_concept_mode_comparison_acceptance tests.test_concept_mode_comparison_group` | **PASS**, 19 tests. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests.test_chunk_input_acceptance tests.test_document_lookup_acceptance tests.test_match_evidence_acceptance tests.test_vector_alias_compatibility_acceptance tests.test_vector_candidate_discovery_acceptance` | **PASS**, 38 tests. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests.test_information_need_groups_acceptance tests.test_information_need_suggestions_acceptance` | **PASS**, 9 tests. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests.test_token_preview_acceptance` | **PASS**, 18 tests, 1 skipped. Skip: opt-in parity requiring isolated pinned tokenizer assets. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests.test_concept_tune_readiness` | **PASS**, 12 tests, including secondary-account read-only readiness behavior. |

Full safe offline suite command:

```sh
PYTHONPATH=/tmp/cycle37-qa-deps ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 python3 - <<'PY' > /tmp/cycle37-offline-suite.log 2>&1
import unittest
loader = unittest.TestLoader()
discovered = loader.discover("tests", pattern="test_*.py")
suite = unittest.TestSuite()
def keep_offline(nodes):
    for item in nodes:
        if isinstance(item, unittest.TestSuite):
            yield from keep_offline(item)
        elif item.__class__.__module__ not in {"test_concept_live_acceptance", "tests.test_concept_live_acceptance"}:
            yield item
suite.addTests(keep_offline(discovered))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
PY
status=$?; tail -n 22 /tmp/cycle37-offline-suite.log; exit "$status"
```

Result: **PASS**, exit 0, `Ran 133 tests in 16.097s`, `OK (skipped=1)`. The one skip is the tokenizer parity case described above. `tests/test_concept_live_acceptance.py` was explicitly excluded; live Elasticsearch/provider validation is **NOT RUN**.

### Browser and final build gates

The browser runtime dependencies were supplied through `NODE_PATH=/home/sra235/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.61.1/node_modules`; browser launch used `CYCLE37_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome` and `PYTHONPATH=/tmp/cycle37-qa-deps`.

| Exact command | Result |
| --- | --- |
| `PYTHONPATH=/tmp/cycle37-qa-deps NODE_PATH=/home/sra235/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.61.1/node_modules CYCLE37_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/cycle37_auth_browser.js` | **PASS**, exit 0; JSON result reports `apiCalls:22`, admin create, login/logout, storage secrecy and revoked-session UI gate all true. |
| `PYTHONPATH=/tmp/cycle37-qa-deps NODE_PATH=/home/sra235/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.61.1/node_modules CYCLE37_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome node tests/run_cycle37_browser_regression.js` | **PASS**, exit 0; C34 single-query, C35 grouped comparison, and C36 group-readiness browser fixtures all report PASS. Synthetic ES responses only. |
| `node --check tests/cycle37_auth_browser.js && node --check tests/run_cycle37_browser_regression.js && node --check tests/cycle34_mode_comparison_browser.js && node --check tests/cycle35_group_mode_comparison_browser.js && node --check tests/cycle36_group_comparison_readiness_browser.js` | **PASS**, exit 0. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m compileall -q es_rag_tuner tests` | **PASS**, exit 0. |
| `python3 -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/cycle37-wheel-final-20261018` | **PASS**, exit 0; built `es_rag_tuning_workbench-1.0.0-py3-none-any.whl`, SHA-256 `1b5c2a83249e4eb13521aab9ebbb2ef41309ea64fae7d0c1026ddeb5fceb29c4`. |
| `python3 -m pip install --no-deps --target /tmp/cycle37-wheel-install-final-20261018 /tmp/cycle37-wheel-final-20261018/es_rag_tuning_workbench-1.0.0-py3-none-any.whl` | **PASS**, exit 0. |
| `cd /tmp && PYTHONPATH=/tmp/cycle37-wheel-install-final-20261018:/tmp/cycle37-qa-deps python3 -c 'import es_rag_tuner; from es_rag_tuner import auth, server; print(es_rag_tuner.__version__)'` | **PASS**, exit 0; printed `1.0.0`. |

The first C37 browser attempt timed out because the fixture attempted to operate on a row while the preceding account-update refresh was replacing it. The fixture now waits for the account-list request and refreshed display-name input before testing reset; the subsequent C37 browser run passed. C35's synthetic state now sets the connected-index readiness fields required by the current UI. These were fixture synchronization/state corrections; the final browser run found no remaining UI regression.

Final gate disposition: offline/API/browser/static/package checks above **PASS**. Pinned-tokenizer parity remains **SKIPPED**. Live ES/provider validation and deployment/security review remain **NOT RUN**. These outcomes do not establish production security; the cited OWASP and argon2-cffi materials remain guidance rather than empirical proof.

### Post-review dummy-hash fix rerun

After the review change that caches one process-local Argon2id dummy hash, an additional deterministic regression assertion was added to `test_generic_login_errors_and_throttle`: during an unblocked unknown-username login, the test wraps the configured hasher, makes `hash()` raise if invoked, and asserts `hash.assert_not_called()` while still requiring the generic HTTP 401 response. This checks the no-per-request-hash behavior without relying on timing measurements.

Requested model: `gpt-6-luna`; runtime identity: **UNVERIFIED**.

| Exact command | Result |
| --- | --- |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m unittest -v tests/test_cycle37_auth_acceptance.py` | **PASS**, exit 0, `Ran 17 tests in 3.007s`, `OK`; includes the deterministic unknown-user no-hash assertion. |
| Exact full safe offline command shown immediately below | **PASS**, exit 0, `Ran 133 tests in 16.109s`, `OK (skipped=1)`. Live acceptance remains excluded; pinned-tokenizer parity remains skipped. No live ES/provider calls were made. |
| `PYTHONPATH=/tmp/cycle37-qa-deps python3 -m compileall -q es_rag_tuner tests` | **PASS**, exit 0. |
| `python3 -m pip wheel --no-deps --no-build-isolation . --wheel-dir /tmp/cycle37-wheel-post-dummy-20261018` | **PASS**, exit 0; built `es_rag_tuning_workbench-1.0.0-py3-none-any.whl`, SHA-256 `a20254b5d86059874add9a3e89387f06db395dbd622432afa356b29247f25e2c`. |
| `python3 -m pip install --no-deps --target /tmp/cycle37-wheel-install-post-dummy-20261018 /tmp/cycle37-wheel-post-dummy-20261018/es_rag_tuning_workbench-1.0.0-py3-none-any.whl` | **PASS**, exit 0. |
| `cd /tmp && PYTHONPATH=/tmp/cycle37-wheel-install-post-dummy-20261018:/tmp/cycle37-qa-deps python3 -c 'import es_rag_tuner; from es_rag_tuner import auth, server; print(es_rag_tuner.__version__)'` | **PASS**, exit 0; printed `1.0.0`. |

Exact safe offline command:

```sh
PYTHONPATH=/tmp/cycle37-qa-deps ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 python3 - <<'PY' > /tmp/cycle37-offline-suite-post-dummyhash-with-assertion.log 2>&1
import unittest
loader = unittest.TestLoader()
discovered = loader.discover("tests", pattern="test_*.py")
suite = unittest.TestSuite()
def keep_offline(nodes):
    for item in nodes:
        if isinstance(item, unittest.TestSuite):
            yield from keep_offline(item)
        elif item.__class__.__module__ not in {"test_concept_live_acceptance", "tests.test_concept_live_acceptance"}:
            yield item
suite.addTests(keep_offline(discovered))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
PY
status=$?; tail -n 22 /tmp/cycle37-offline-suite-post-dummyhash-with-assertion.log; exit "$status"
```

Test-authoring note: an initial attempt to patch `auth._hasher.hash` directly failed because the `PasswordHasher.hash` instance attribute is read-only (`AttributeError`). The test now patches the module's `_hasher` reference with a wrapping mock instead; the final test and full suite pass. This was a test instrumentation issue, not an application failure. The C37 and C34-C36 browser runs from the prior final QA were not repeated because the only production change was in authentication's unknown-user hash handling; the C37 API test and full offline suite were rerun after that change.
