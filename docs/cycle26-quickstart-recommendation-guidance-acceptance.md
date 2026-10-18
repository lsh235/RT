# Cycle 26 quickstart recommendation guidance acceptance

## Scope and baseline

- Baseline supplied by the coordinator: `main` commit/tag `2ce9578d5479154e9418674be8d6a77473a897f2` / `v0.17.6`; the candidate package version is `0.17.7`.
- Requested and assigned QA model: `gpt-6-luna`. Runtime model identity: **UNVERIFIED**; no runtime telemetry exposed the executing model.
- QA-owned files: [synthetic browser fixture](../tests/cycle26_quickstart_recommendations_browser.js) and this report. No Git mutations were made. The two pre-existing untracked user documents were left unopened and unchanged.
- Browser API requests were intercepted and fulfilled with synthetic fixtures. No actual Elasticsearch endpoint, credentials, local user database, user corpus, provider authentication, or user study was used.
- The repository's codebase-memory graph MCP was unavailable for this task; source claims below were checked directly against the listed bounded code locations. No graph generation or coverage check is claimed.

## Interpretation and sources

### Direct code facts

- `concepts.quickstart()` chooses `text`, `match_only_text`, and `search_as_you_type` fields first for body suggestions. If none exist, it falls back to the app's searchable fields. Its title suggestions use recognized names on nonnested searchable fields and otherwise choose a nonnested searchable fallback. See [`concepts.py`](../es_rag_tuner/concepts.py#L436) (body/title suggestion rules) and [`concepts.py`](../es_rag_tuner/concepts.py#L627) (title validation rejects nested title fields for this workflow).
- The UI now takes the title suggestion from the backend response, displays each recommended field with its mapping type, explains the text-like-first and broader fallback rules, and describes field selection as a rule-based app candidate rather than a semantic judgment. Applying suggestions remains a separate button action. See [`app.js`](../es_rag_tuner/web/app.js#L1025) and [`app.js`](../es_rag_tuner/web/app.js#L1101).

### Product inference and Elasticsearch context

The guidance is an application heuristic. A mapping type and a field name do not establish that the content is semantically suitable for a particular concept, nor that it has usable values across an entire index. Elastic describes `text` fields as analyzed full-text fields, while `keyword` fields are suited to structured values and are not intended for full-text search: [text fields](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/text), [keyword fields](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/keyword). The `index` mapping parameter also has type-dependent behavior, so this UI's candidate list is not a universal statement of Elasticsearch queryability: [index parameter](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/mapping-index). Nested fields require nested-query scope in Elasticsearch; this product's title-field validator separately excludes nested title fields for this workflow: [nested query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-nested-query).

The usefulness of explaining these rules before applying fields is a product inference tested by the browser fixture. It is not a claim about semantic quality or retrieval performance.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Standard text-like body priority and mapping labels | **PASS (synthetic browser)** | Guidance named `text`, `match_only_text`, and `search_as_you_type` priority. Recommendations and expanded mapping details showed types for title, body, and filter candidates. |
| Broader body fallback and keyword-only case | **PASS (synthetic browser)** | Keyword-only mapping displayed keyword types and the broader fallback; guidance said the fallback may include keyword and is not the same as full-text `text` fields. |
| Heuristic, semantic suitability, and index-wide caveats | **PASS (synthetic browser)** | Guidance identified app mapping-name/type rules, said it cannot automatically determine semantic fit, and said sample values do not prove searchability or coverage across the full index. |
| Nested-title regression and backend canonical title | **PASS (synthetic browser)** | With scalar searchable `name` plus nested searchable `comments.title` and backend suggestion `name`, the UI and explicit Apply both kept `name`. The title candidate summary did not promote `comments.title`. |
| Suggestions remain unapplied until explicit Apply | **PASS (synthetic browser)** | Before Apply, synthetic preselected title/body/filter fields, query text, and grade sentinel were unchanged. Apply then selected backend `title`, body `summary`, and filter `tags`. Apply made no API request. |
| Read-only behavior and mocked API boundary | **PASS (synthetic browser)** | Every `/api/**` request was intercepted. The fixture observed exactly three quickstart reads for the three scenarios, expected health/codebase/AI-status requests, and no forbidden mutation endpoint calls. |
| HTML escaping | **PASS (synthetic browser)** | A synthetic mapping name containing `<img ... onerror=...>` rendered escaped as text; no image element or script execution appeared. |
| Desktop/mobile layout and console | **PASS (Chromium, synthetic browser)** | At 1280×900 and 390×844, document and body widths matched the viewport (1280px and 390px respectively). Captured application console errors during intercepted scenarios: 0. The initial page opened before route installation showed four unmocked API errors; that navigation was outside acceptance and was followed by intercepted test navigations. |
| JavaScript syntax | **PASS** | `node --check es_rag_tuner/web/app.js && node --check tests/cycle26_quickstart_recommendations_browser.js` — exit 0. |
| Full documented unittest suite with unreachable Elasticsearch URL | **PASS (limited)** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v` — 101 tests in 6.774s, `OK (skipped=2)`, exit 0. The live Elasticsearch class skipped because the configured loopback endpoint refused connection. Optional tokenizer parity skipped because no isolated fixture containing the four pinned tokenizer/config assets was supplied. These skips are not live Elasticsearch or tokenizer-parity passes. |
| Isolated wheel/install/module/CLI smoke | **PASS** | A temporary staging copy of `pyproject.toml`, `README.md`, and `es_rag_tuner/` built a wheel with `python3 -m pip wheel --no-deps --no-build-isolation`; isolated `pip install --no-deps --target` succeeded. Outside the checkout, module and distribution metadata both reported `0.17.7`, packaged `web/app.js` existed, and `es-rag-workbench --help` exited 0. Wheel SHA256: `302027afc5d28c908daa54748d99dceca70f5ef95ac315e0e417c4d5e4c3369b`. Temporary source, wheel, and install directories were removed automatically. |
| Live Elasticsearch, actual corpus, provider authentication, retrieval quality, user study | **NOT RUN** | Browser routes were synthetic and the unit suite's live Elasticsearch target was intentionally unreachable. No production, relevance, or retrieval-quality claim is made. |
| Runtime model identity | **UNVERIFIED** | `gpt-6-luna` was requested and assigned, but runtime telemetry did not identify the executing model. |

### Browser command and environment

Environment: Node `v22.23.2`, Python `3.12.3`, Playwright CLI wrapper, Chromium, and a loopback-only static server. The fixture intercepted every `/api/**` route before navigating its tested scenarios.

```text
python3 -m http.server 18775 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle26 open http://127.0.0.1:18775/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle26 run-code --filename tests/cycle26_quickstart_recommendations_browser.js
node --check es_rag_tuner/web/app.js && node --check tests/cycle26_quickstart_recommendations_browser.js
```

The browser fixture completed with exit 0. The later synthetic scenarios recorded `/api/health`, `/api/codebase-status`, `/api/ai/status`, and `/api/concepts/quickstart`; there were three quickstart calls, one per scenario. It recorded zero application console errors and no forbidden mutation endpoint calls. All API responses came from the fixture.

### Isolated package smoke command

The temporary staging script copied only the project metadata, README, and package source into a fresh temporary directory, then ran the following package commands from outside the checkout:

```text
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <temporary>/wheelhouse <temporary>/source
python3 -m pip install --no-deps --target <temporary>/target <temporary>/wheelhouse/es_rag_tuning_workbench-0.17.7-py3-none-any.whl
python3 -c "import importlib.metadata as m, es_rag_tuner, pathlib; print(pathlib.Path(es_rag_tuner.__file__).resolve()); print(m.version('es-rag-tuning-workbench')); print(es_rag_tuner.__version__); print((pathlib.Path(es_rag_tuner.__file__).parent/'web'/'app.js').is_file())"
<temporary>/target/bin/es-rag-workbench --help
```

Build, install, module smoke, and CLI help each exited 0. The wheel digest and versions are recorded above. This validates a local wheel build and isolated import/entry point only; it does not establish a published release or deployment readiness.

No live Elasticsearch, production corpus, provider, semantic suitability, retrieval quality, or user-study conclusion is claimed.
