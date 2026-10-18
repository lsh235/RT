# Cycle 25 quickstart sample switcher acceptance

## Scope and baseline

- Baseline supplied by the coordinator: `main` at `75066d1`, version `v0.17.5`. The accepted implementation package reports `0.17.6`.
- Requested QA model: `gpt-6-luna`. Runtime model identity: **UNVERIFIED**; no runtime telemetry exposed the executing model.
- QA-owned files: [synthetic browser fixture](../tests/cycle25_quickstart_samples_browser.js) and this report. QA made no edits to application files and performed no Git operations. The pre-existing untracked user documents were preserved and not opened.
- Browser traffic to every `/api/**` route was intercepted with synthetic data. No Elasticsearch endpoint, credentials, local user database, actual corpus, provider, or user study was used.
- Scope: show zero/one/up to three sample documents from the existing quickstart response, let users browse them, and keep browsing separate from applying field recommendations. Examples are not evidence of whole-index field coverage, searchability, or relevance.

## Interpretation and research

Checked 2026-10-18 against Elastic's official documentation. Search `size` bounds returned hits; `_source` is the original JSON supplied at index time; retrieving `_source` values does not establish that a field is mapped or searchable. Elastic documents mapping-aware `fields` retrieval separately from `_source`, and documents random sampling as a distinct approximate aggregation: [Search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search), [retrieve selected fields](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrieve-selected-fields), [exists query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-exists-query), [random sampler aggregation](https://www.elastic.co/docs/reference/aggregations/search-aggregations-random-sampler-aggregation).

Product inference: because the existing quickstart returns at most three examples, a labelled picker is a useful way to inspect those examples. The UI should describe them as examples and should not imply corpus-wide field presence, searchability, or relevance. This inference is the product judgment tested here; it is not an Elastic guarantee.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Zero and one sample states | **PASS (synthetic)** | Zero samples showed the no-example state and no selector. One sample displayed its ID/title and had no broken selector. |
| Three-sample picker and switching | **PASS (synthetic)** | A native labelled `<select>` showed three options, defaulted to sample 1, and selected samples 2 and 3 with the corresponding ID/title/body values. A nearby caveat identifies the documents as examples. |
| Native picker label and keyboard access | **PASS (Chromium, synthetic)** | `select.labels` contained the visible “예시 문서 선택” label associated through `for="quickstart-sample-select"`. Pressing `ArrowDown` changed the selected value to sample 2 and updated the visible panel; pressing `ArrowUp` returned to sample 1 and updated the panel. Neither key action added an API request or changed the seeded editor/query/grade state. |
| Missing and unusual source values | **PASS (synthetic)** | Sample 2 omitted the suggested title; the UI showed the missing-title message and document ID. An array-valued body field rendered a readable scalar value. A 600-character body remained readable within the 420-character excerpt limit. An HTML-shaped string was escaped; no `<img>` node or event execution appeared. The zero-sample state covered an empty body/example set. |
| Switching remains read-only | **PASS (synthetic)** | Keyboard and pointer selection caused no additional API calls. Field selections, concept query input, and a seeded synthetic saved-grade control remained unchanged. Clicking the separate “추천 필드 적용” action applied the suggested title/text/filter fields without an API request. The grade assertion uses a synthetic UI sentinel, not a persisted user judgment. |
| Desktop/mobile layout and browser console | **PASS (synthetic)** | At 1280×900 and 390×844, document/body widths did not exceed the viewport. Application console errors: 0. Playwright console inspection reported 0 errors and 0 warnings; Chromium emitted two verbose password-field notices. |
| JavaScript syntax | **PASS** | `node --check es_rag_tuner/web/app.js && node --check tests/cycle25_quickstart_samples_browser.js` — exit 0. |
| Full documented unittest suite, offline Elasticsearch endpoint | **PASS (limited)** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v` — 101 tests in 6.792s, `OK (skipped=2)`, exit 0. The live Elasticsearch acceptance class skipped because the explicitly unreachable loopback endpoint refused connection. Optional tokenizer parity skipped because `ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE` was unset; it requires an isolated fixture containing four pinned tokenizer/config assets. These skips are not live Elasticsearch or tokenizer-parity passes. The suite's SQLite use was confined to its disposable test fixtures; no local user database was accessed. |
| Isolated wheel/install/module/CLI smoke | **PASS** | Copied `pyproject.toml`, `README.md`, and `es_rag_tuner/` to a temporary source directory; built with `python3 -m pip wheel --no-deps --no-build-isolation`; installed with `python3 -m pip install --no-deps --target`; from outside the checkout the module and distribution metadata both reported `0.17.6`, packaged `web/app.js` existed, and installed `es-rag-workbench --help` exited 0. Wheel SHA256: `b89df3c637cb3f9f908b33d676c7dff747d5ff7e65ab4b8d181c80c52b1c4a7a`. Temporary staging/install directories were removed automatically. |
| Live Elasticsearch, corpus, provider, retrieval quality, user study | **NOT RUN** | Browser responses were synthetic; the offline suite pointed its live-ES fixture at an unreachable loopback port. No relevance or retrieval-quality claim is made. |
| Runtime model identity | **UNVERIFIED** | `gpt-6-luna` was requested; available telemetry did not identify the runtime model. |

### Browser commands and environment

Environment: Node `v22.23.2`, Python `3.12.3`, `npx` available; local static server bound to loopback only. All app API paths were intercepted before the tested page loads. The quickstart flow issued one quickstart request per zero/one/three-sample case; the app's expected AI-status bootstrap traffic was also mocked. Assertions captured the API-call count before and after changing samples.

```text
python3 -m http.server 18775 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle25b open http://127.0.0.1:18775/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle25b run-code --filename tests/cycle25_quickstart_samples_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle25b console
```

The fixture passed all assertions with exit 0. The initial static page navigation before installing the fixture route showed four expected unmocked API console errors; this was outside acceptance. Subsequent tested navigations had interception active and zero application console errors. The final console command showed no browser errors or warnings, plus two Chromium verbose password-field notices.

No implementation changes were made by QA. The browser fixture and this report are the only QA-owned repository files.
