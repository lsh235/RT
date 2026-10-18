# Cycle 28 result highlights acceptance

## Scope and baseline

- Baseline supplied by the coordinator: `v0.17.8`, commit `848d9f700fb3e5269893bd9640278c9db3b9e17d`; candidate version `0.17.9`.
- External research, implementation, and QA agents were requested/assigned `gpt-6-luna`; runtime model identity is **UNVERIFIED** because agent runtime telemetry was unavailable.
- QA-owned files are this report and [`tests/cycle28_result_highlights_browser.js`](../tests/cycle28_result_highlights_browser.js). The implementation worker owns `app.js`, `style.css`, README, and version files. QA makes no implementation or Git changes.
- Browser scenarios use only synthetic responses and an isolated loopback static page. No Elasticsearch, user database, corpus, or credentials are accessed.
- C25 sample chooser, C26 mapping guidance, and C27 selected-sample query handoff are complete and out of this cycle's scope.

## Evidence and interpretation

### Direct source facts

- [`retrieval.py`](../es_rag_tuner/retrieval.py) requests Elasticsearch highlights in `_lexical_search` for `summary`, `error_signature`, `root_cause`, `workaround_or_fix`, `description`, and `rag_chunk_text`; vector retrieval does not request highlights. Reciprocal rank fusion preserves the lexical hit payload, including its highlight data. These source-path facts do not mean every Elasticsearch query returns a fragment.
- [`app.js`](../es_rag_tuner/web/app.js) has `renderHit()` consume `hit.highlight`; `renderResultHighlights()` uses a fixed allowlist, selects the first fragment for a field, displays no more than two fields, and slices each to 240 source characters. It escapes source text and then permits exact `<mark>` and `</mark>` tags. Missing BM25 highlights get neutral absence copy; vector and hybrid vector-only results get lexical-excerpt-unavailable copy that states missing excerpts alone do not imply irrelevance.

### Elasticsearch documentation and product inference

- Elasticsearch documents highlight fragments and notes that complex Boolean queries can produce highlighted terms that are not themselves true matches: [highlighting](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting).
- Elasticsearch's RRF documentation describes highlighting from text sub-retrievers; kNN vector results do not provide vector highlights: [highlighting with RRF](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/rrf.html#highlighting-in-rrf). Vector query documentation describes vector retrieval behavior separately: [vector queries](https://www.elastic.co/docs/reference/query-languages/query-dsl/vector-queries).
- These Elastic documentation sources were checked on `2026-10-18`.
- Showing returned lexical context can help a person inspect why a hit surfaced. This is a product-value inference only; it is not evidence of semantic relevance, retrieval quality, or answer quality. Missing lexical snippets must not be described as proof of no match or irrelevance.

## Acceptance results

Final QA ran after the coordinator's explicit ready signal.

| Gate | Status | Evidence |
|---|---|---|
| Synthetic BM25 result displays a returned fragment, correct allowlisted field label, and visible `<mark>` term | **PASS (synthetic browser)** | BM25 hit showed `요약` and `에러 시그니처` fragments with visible `timeout` and `ECONNRESET` marks. A second card without highlights still rendered. |
| Hybrid result retains/displays returned BM25 highlight; hybrid/vector-only hit with no highlight gets a neutral unavailable note | **PASS (synthetic browser)** | RRF hit retained its `timeout` mark. A synthetic hit with `bm25: null` and a vector score showed “벡터 검색에서 어휘 강조 발췌는 제공되지 않습니다” and explicitly said absence alone does not mean irrelevance. |
| Pure vector mode explains lexical excerpt unavailable; absence text does not imply no match or irrelevance | **PASS (synthetic browser)** | Vector-only result showed the same mode-aware lexical-excerpt explanation and neutral caveat. |
| No `_source` fallback; fixed allowlist only; at most two fields, first fragment per field, at most 240 characters each | **PASS (synthetic browser)** | `_source` sentinel text was not substituted. Second summary fragment, third allowed field, and disallowed `title` field sentinels were absent; exactly two fragments rendered, each at most 240 text characters. |
| XSS-shaped content remains inert; only exact `<mark>` tags become markup | **PASS (synthetic browser)** | `<img>`, `<script>`, and attributed `<mark>` input remained escaped; only exact `<mark>ECONNRESET</mark>` became markup. No injected code ran. |
| Cards without highlights still render and query, scores, and saved-grade state remain unchanged | **PASS (synthetic browser)** | Existing no-highlight BM25 card rendered with score `2.5000`. BM25 scores remained `7.2500, 2.5000`; hybrid remained `0.0328, 0.0161` with RRF labels; vector remained `0.7444` with vector label. All modes retained query `timeout ECONNRESET` and grade sentinel `2`. |
| 1280px and 390px widths have no horizontal overflow; no result-rendering API mutations; zero app console errors | **PASS (Chromium, synthetic browser)** | Both viewport widths passed document/body overflow assertions. Exactly three mocked `/api/search` POSTs were made (one each for BM25, hybrid, vector); no mutation/evaluation endpoint was called. Fixture-captured application console errors: 0. CLI console inspection: 0 errors and 0 warnings, plus 2 Chromium verbose password-field notices. |
| JavaScript syntax, full documented offline suite, isolated 0.17.9 wheel/install/module/CLI smoke, and page/package version labels | **PASS** | Syntax checks exited 0. Offline suite: 101 tests, `OK (skipped=2)`. Wheel build/install, module/distribution checks, and CLI help passed. Browser page, packaged page, package metadata, and module labels reported `v0.17.9` / `0.17.9`. Wheel SHA256: `e340f49ccdb765a938a5a6a0c72c7b978c202ca51563d801104bc440d6b98179`. |
| Live Elasticsearch, actual corpus, retrieval quality, user study, provider readiness | **NOT RUN** | Outside this synthetic QA scope; no live endpoint, user corpus, provider, or user-study conclusion was tested. |

## Commands and environment

The successful browser acceptance used the repository's Playwright CLI wrapper and loopback static server:

```text
python3 -m http.server 18775 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle28 open http://127.0.0.1:18775/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle28 run-code --filename tests/cycle28_result_highlights_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle28 console
node --check es_rag_tuner/web/app.js && node --check tests/cycle28_result_highlights_browser.js
ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v
```

Environment: Node `v22.23.2`, Python `3.12.3`, `npx` available, repository Playwright CLI wrapper, Chromium. The exact Chromium build number was not captured.

The Playwright `open` command was run once before installing the fixture's API routes and logged four unmocked API errors; this navigation was outside the acceptance scenarios. The fixture installs its route interception before its tested `page.goto()`. During the tested scenarios, the fixture observed three `POST /api/search` calls in BM25, hybrid, vector order, with no mutation/evaluation endpoint. Application console errors were zero. The 1280×900 and 390×844 viewport checks both passed.

The offline suite command used the deliberately unreachable endpoint and finished with 101 tests in 6.784s, `OK (skipped=2)`. `LiveConceptAcceptance` skipped because loopback connection was refused. Optional real-tokenizer parity skipped because its isolated fixture with four pinned tokenizer/config assets was not supplied. Neither skip is a live Elasticsearch or tokenizer-parity pass.

For package smoke, a temporary staging copy of `pyproject.toml`, `README.md`, and `es_rag_tuner/` was built and installed into a temporary target. The first isolated CLI invocation omitted the temporary target from `PYTHONPATH` and could not import the module; rerunning with `PYTHONPATH=<temporary>/target` passed. The target directory is necessary for invoking a `--target` install outside an environment's normal `site-packages`. The successful command forms were:

```text
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <temporary>/wheelhouse <temporary>/source
python3 -m pip install --no-deps --target <temporary>/target <temporary>/wheelhouse/es_rag_tuning_workbench-0.17.9-py3-none-any.whl
PYTHONPATH=<temporary>/target python3 -c "import importlib.metadata as m, es_rag_tuner, pathlib; p=pathlib.Path(es_rag_tuner.__file__).resolve(); print(m.version('es-rag-tuning-workbench')); print(es_rag_tuner.__version__); print((p.parent/'web'/'app.js').is_file()); print((p.parent/'web'/'index.html').read_text().split('id=\"server-version\">',1)[1].split('<',1)[0])"
PYTHONPATH=<temporary>/target <temporary>/target/bin/es-rag-workbench --help
```

Build, install, import/version inspection, and CLI help exited 0 on the successful run. Wheel SHA256 is recorded above. The temporary staging, wheel, and target directories were removed automatically. No production installation or published release was tested.

The browser fixture intercepts all `/api/**` requests during tested scenarios. QA edited only the assigned browser fixture and acceptance report; no Git mutation was made. Pre-existing unrelated documents were left untouched.

## Limits

Synthetic response rendering checks UI behavior only. It cannot establish that a live Elasticsearch request returns highlights, that fragments identify true semantic matches, that users find the feature useful, or that retrieval or RAG quality improved. No live service, user corpus, database, or credentials are part of this QA scope.
