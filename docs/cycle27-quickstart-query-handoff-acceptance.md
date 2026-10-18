# Cycle 27 quickstart to guided-query handoff acceptance

## Scope and baseline

- Baseline supplied by the coordinator: commit `f16938bd6d7b75258498e17471420561d2c90793` / tag `v0.17.7`; the candidate is expected to be `0.17.8`.
- QA owns this report and `tests/cycle27_quickstart_query_handoff_browser.js` only. QA does not modify implementation files or Git state.
- The test fixture uses synthetic quickstart API responses and an isolated loopback static page. It does not connect to Elasticsearch or load a user corpus or credentials.
- The codebase-memory skill was applied, but its graph MCP tools were not available in this session. Relevant source inspection was bounded to the quickstart rendering and event handling in `es_rag_tuner/web/app.js` and the guided-query controls in `es_rag_tuner/web/index.html`.
- Requested/assigned model: `gpt-6-luna`. Runtime model identity: **UNVERIFIED** unless execution telemetry is made available.

## Acceptance results

Final QA ran after the coordinator's ready signal, including a rerun after the page version label was corrected from `v0.17.5` to `v0.17.8`.

| Gate | Status | Evidence |
|---|---|---|
| Zero samples show no handoff action | **PASS (synthetic browser)** | Empty sample list showed no handoff action. |
| One unusable sample shows no handoff action | **PASS (synthetic browser)** | A singleton containing whitespace-only title and non-scalar body values showed no handoff action. |
| One usable sample has no picker and its action is safe | **PASS (synthetic browser)** | No selector was rendered. Clicking the action inserted `Usable title Usable body`, focused the guided input, made no API request, and preserved field selections, concept query text/selection, and synthetic saved-grade state. |
| Selected sample supplies a deterministic plain-text phrase of at most 500 characters | **PASS (synthetic browser)** | Selecting sample 2 of 3 produced and inserted exactly `Second title Second body`. The long sample produced a 312-character phrase, inserted into the plain-text guided textarea. |
| Switching samples uses the current selection | **PASS (synthetic browser)** | Selected sample 2 before clicking; the guided input matched sample 2. |
| HTML-shaped source remains inert text | **PASS (synthetic browser)** | `<img ... onerror=...>` remained escaped in panel markup, with no image element or event execution. |
| Handoff only populates and focuses the guided input | **PASS (synthetic browser)** | Handoff made no API request and preserved selected title/body/filter fields, concept query text/selection, and a synthetic saved-grade sentinel. It focused the guided input. The separate “이 내용으로 결과 보기” action remained present. |
| Keyboard access, 1280px/390px responsive layout, zero app errors | **PASS (Chromium, synthetic browser)** | Native button activated with Enter. At 1280×900 and 390×844, document/body widths matched the viewport. Captured app console errors: 0. Playwright console showed 0 errors and 0 warnings; Chromium emitted 2 verbose password-field notices. |
| Page/package version-label consistency | **PASS** | Browser `#server-version`, wheel metadata, and module reported `v0.17.8` / `0.17.8` after the coordinator corrected the stale page label. |
| JavaScript syntax | **PASS** | `node --check es_rag_tuner/web/app.js && node --check tests/cycle27_quickstart_query_handoff_browser.js` — exit 0. |
| Full offline unittest suite | **PASS (limited)** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v` — 101 tests in 6.780s, `OK (skipped=2)`, exit 0. `LiveConceptAcceptance` skipped because the unreachable loopback Elasticsearch endpoint refused connection. Optional real-tokenizer parity skipped because the isolated fixture of four pinned tokenizer/config assets was not supplied. These are not live ES or tokenizer-parity passes. |
| Isolated 0.17.8 wheel/install/module/CLI smoke | **PASS** | Wheel built and installed into a temporary target. Distribution and module both reported `0.17.8`; packaged `web/app.js` existed; packaged label was `v0.17.8`; `es-rag-workbench --help` exited 0. Wheel SHA256: `11a55f7b0e453f957a230ec7276ce8aab504b6acfd97228340bf96351a0174a4`. |
| Live Elasticsearch, user corpus, retrieval quality, provider, user study | **NOT RUN** | These are outside this synthetic QA scope and must remain explicitly unclaimed. |

## Browser command and environment

Local command sequence used for the synthetic browser run:

```text
python3 -m http.server 18775 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle27qa2 open http://127.0.0.1:18775/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle27qa2 run-code --filename tests/cycle27_quickstart_query_handoff_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle27qa2 console
```

Environment: Node `v22.23.2`, Python `3.12.3`, `npx` available, Playwright CLI wrapper, and Chromium. The fixture intercepted every `/api/**` route. It observed 20 mocked calls total across the four cases (0 samples, one unusable sample, one usable sample, and three samples): four each to `/api/concepts/quickstart`, `/api/health`, and `/api/codebase-status`, plus eight `/api/ai/status` calls. Changing sample selection, clicking handoff, keyboard activation, and resizing made no additional requests. All captured app console errors: 0. The initial `open` command preceded fixture route installation and showed four unmocked API errors; that initial navigation was outside the acceptance scenarios. Later intercepted scenarios passed. Browser console inspection showed 0 errors and 0 warnings, plus two Chromium verbose password-field notices.

The exact syntax and offline suite commands were:

```text
node --check es_rag_tuner/web/app.js && node --check tests/cycle27_quickstart_query_handoff_browser.js
ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v
```

The isolated smoke used a temporary staging copy of `pyproject.toml`, `README.md`, and `es_rag_tuner/`, and ran these exact build/install/import/CLI command forms from outside the checkout:

```text
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <temporary>/wheelhouse <temporary>/source
python3 -m pip install --no-deps --target <temporary>/target <temporary>/wheelhouse/es_rag_tuning_workbench-0.17.8-py3-none-any.whl
python3 -c "import importlib.metadata as m, es_rag_tuner, pathlib; print(pathlib.Path(es_rag_tuner.__file__).resolve()); print(m.version('es-rag-tuning-workbench')); print(es_rag_tuner.__version__); print((pathlib.Path(es_rag_tuner.__file__).parent/'web'/'app.js').is_file()); print((pathlib.Path(es_rag_tuner.__file__).parent/'web'/'index.html').read_text().split('id=\"server-version\">',1)[1].split('<',1)[0])"
<temporary>/target/bin/es-rag-workbench --help
```

All four package commands exited 0. The temporary source, wheel, and install directories were removed automatically. No production install or published release was tested.

## Limits

Synthetic browser evidence cannot establish live Elasticsearch behavior, corpus coverage, retrieval quality, provider availability, production readiness, or user-study outcomes. The offline test suite's deliberately unreachable Elasticsearch URL also cannot establish live Elasticsearch behavior. No user database, corpus, or credentials were accessed.
