# Contributing

Thanks for helping improve the local Elasticsearch search and RAG quality workbench. Contributions should keep its local-first scope, preserve clear evaluation limits, and include evidence for behavior changes.

## Development setup

Requirements: Python 3.10 or newer, Node.js 20 or newer for browser checks, and a supported Elasticsearch endpoint only for live integration checks.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
npm ci
```

The Python lock pins the default runtime and developer test dependencies. The browser lock is `package-lock.json`. The default test suite uses local fixtures and does not need Elasticsearch credentials or provider API keys:

```bash
.venv/bin/python scripts/run_offline_tests.py
```

Build and install the wheel in a clean temporary virtual environment:

```bash
.venv/bin/python scripts/package_smoke.py
```

The browser smoke test needs a Chromium install:

```bash
npx playwright install chromium
npm run test:browser
```

The browser checks run the local page smoke, synthetic Cycle 44 positive-target-misses regression, and synthetic R03 first-use flow. The fixtures block browser requests outside the workbench and fulfill API calls with synthetic data. The R03 flow uses a fresh temporary SQLite database and does not contact Elasticsearch. Both launchers use the repository `.venv` interpreter automatically when present. To select another interpreter, set `PYTHON` explicitly: in POSIX shells use `PYTHON="$(pwd)/.venv/bin/python" npm run test:browser`; in PowerShell use `$env:PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path` followed by `npm run test:browser`.

## Optional external checks

Live Elasticsearch acceptance tests create and delete a UUID-named `concept-accept-*` index. Use only a disposable cluster and a dedicated test identity with permission limited to that fixture index. The configured source index, if it exists, is read-only and fingerprinted before and after the run.

```bash
ES_RAG_RUN_LIVE=1 \
ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:9200 \
ES_RAG_ACCEPTANCE_SOURCE_INDEX=dedicated-read-only-reference \
ES_RAG_ACCEPTANCE_PYTHON="$PWD/.venv/bin/python" \
.venv/bin/python -m unittest discover -s tests -p 'live_concept_acceptance.py' -v
```

Provider-backed checks are opt-in. They may send explicitly selected prompt/document context to the provider and may incur provider usage. Set only the credentials needed for the specific check. CI never receives provider secrets. Current default tests use mocks; there is no live-provider test in this repository yet.

Run the read-only environment report with `es-rag-workbench doctor` or `python -m es_rag_tuner doctor`. It reads only the cluster root endpoint. `ES_URL`, `ES_API_KEY`, or the pair `ES_USERNAME` and `ES_PASSWORD` may be supplied through the environment; credentials are not included in its output. Vector support is estimated from the reported product, build flavor, and version. OpenSearch plugin availability and mappings are not inspected, so kNN support can remain unknown; the estimate is not an API probe.

## Change and review expectations

- Keep changes focused and describe user-visible behavior, compatibility, and any migration impact.
- Add or update deterministic tests for changed behavior. Keep external-service tests separate and opt-in.
- Include exact commands and results for offline, browser, and live checks that you ran. Mark unrun checks clearly.
- Do not use mock, sample-corpus, or local-only results as production readiness or general corpus-quality evidence.
- Update [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- Do not commit credentials, local data, caches, or generated build artifacts.
- The Apache-2.0 declaration applies to project code. Rights for the bundled Jira issue sample corpus have not been established by that declaration; do not redistribute those records as Apache-licensed content.
