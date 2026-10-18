# Cycle 31 mapped result-title acceptance

## Scope and baseline

- Baseline: `main`, `v0.18.1`, commit `8612b39cbff7db8a8135f735829778da68772c84`.
- Candidate: `v0.19.0`. Ordinary search cards should use the selected searchable, non-nested scalar title field from the current index mapping, with `summary` fallback. The staged AI coach readout should reflect the same displayed title.
- QA owns this report and [`tests/cycle31_mapped_result_title_browser.js`](../tests/cycle31_mapped_result_title_browser.js). Product files are implementation-owned.
- Requested QA model: `gpt-6-luna`; runtime model identity: **UNVERIFIED** (no independent runtime evidence is available).
- Browser checks use synthetic responses and intercepted requests. Live Elasticsearch, provider, corpus, and credentials are outside this run.
- Cycle 30's display-only result staging and Cycle 25/26 mapping-selection/guidance behavior are existing context. This cycle does not retest candidate-pool, information-need grouping, or no-ID lookup work.

## Research evidence and product inference

Official Elastic research was checked `2026-10-18`. The selected-fields, `_source`, and object-field research was completed by the research agent; alias behavior was verified by the coordinator after a research-agent thread-limit error:

- Elastic's [Retrieve selected fields](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrieve-selected-fields) documentation describes `_source` as the default retrieval path, mapping-aware `fields`, omission of missing fields, and array-shaped field values including nested grouping.
- Elastic's [Mapping source field](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/mapping-source-field) documentation explains that `_source` is the original source and can be disabled.
- Elastic's [Object field type](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/object) documentation describes object structure.
- Elastic's [Aliases](https://www.elastic.co/docs/manage-data/data-store/aliases) documentation says an alias can point to one or more indices. Elastic's [Search API](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html) defines each hit's `_index` as the index containing that returned document.

These sources establish response and mapping constraints. They do not establish a novice usability benefit or prescribe this UI behavior. The coordinator inferred that an alias search hit may name a concrete backing index, so a matching selected alias mapping should not be rejected solely because of that string difference; heterogeneous backing mappings still require validation and fallback.

Product inference: showing a title chosen from the current index's selected mapping may make generic corpora easier to scan and may help confirm which result was staged for the AI coach. Synthetic rendering checks cannot establish usability, retrieval quality, or provider answer quality; a user study is **NOT RUN**.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Generic index with matching schema displays selected mapped scalar title on card and staged AI coach readout | **PASS (synthetic browser)** | `cycle31-generic` showed `Generic mapped title` in both locations. Alias `cycle31-alias` also used its matching schema for a hit whose concrete `_index` was `cycle31-concrete-v1`; the card retained the concrete index/ID identity. |
| Existing summary fallback and empty-title behavior | **PASS (synthetic browser)** | Blank, missing, object, array, nested, non-searchable, stale-schema, and unavailable-schema title cases fell back to `_source.summary`. Missing title and summary displayed `제목 없음`. A separate Code RAG result retained its summary display. |
| Safe title rendering, display cap, and XSS inertness | **PASS (synthetic browser)** | Object/array structures were not stringified; nested and non-searchable mapping candidates were rejected. A 300-character title was clipped to 240 characters with an ellipsis. An `<img onerror>` title remained escaped text in both card and staged readout; its sentinel did not run. |
| No per-hit mapping request; staging remains local; explicit Send retains exact query/index/ID/concept and excludes title | **PASS (synthetic browser)** | No mapping/schema endpoint was requested. Staging made no session/message call and title was absent from browser local/session storage. Explicit Send made one synthetic message POST with query `cycle30 exact search query`, document `cycle30-hybrid-alias` / `hybrid-title`, and context keys `concept`, `document`, `query`; the displayed title was absent from the POST body. |
| Grades, search settings, ranking/result identity, keyboard activation, accessible status structure, 1280px/390px layout | **PASS (synthetic browser/DOM)** | Before/after staging snapshots preserved inputs, settings, grade sentinel, scores/order, and last-search state. Enter activated a card action. The persistent polite status structure was present; document/body widths matched viewport at 1280×900 and 390×844. Actual screen-reader announcements were **NOT RUN**. |
| JavaScript syntax and whitespace validation | **PASS** | `node --check` for `app.js` and the Cycle 31 fixture; `git diff --check` exited 0. |
| Full documented offline unittest suite | **PASS (limited, two skips)** | 101 tests ran, `OK (skipped=2)`, exit 0. Live Elasticsearch skipped because loopback connection was refused. Optional tokenizer parity skipped because the isolated four-asset fixture was not supplied. Existing suite emitted `ResourceWarning` notices for unclosed fixture files; no test failed. |
| Isolated wheel/install/module/page/CLI smoke | **PASS** | Built and installed `es_rag_tuning_workbench-0.19.0-py3-none-any.whl` in a temporary staging/install tree. Distribution/module versions were `0.19.0`, packaged page was `v0.19.0`, `web/app.js` existed, and CLI `--help` exited 0. SHA256: `47b12838911d105bfb18745371550e20d9a4b2e3379dc3628a52b3b7acf657ca`. |
| Live Elasticsearch, provider delivery, corpus quality, user study, screen-reader behavior | **NOT RUN** | These were outside the synthetic local QA run. |

## Commands and environment

Environment: Linux loopback static server, Node `v22.23.2`, Python `3.12.3`, Playwright CLI wrapper at `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`. Chromium build number was not captured. The isolated package smoke used `/usr/bin/python3` `3.12.3`.

Browser fixture commands:

```text
python3 -m http.server 18776 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle31 open http://127.0.0.1:18776/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle31 run-code --filename tests/cycle31_mapped_result_title_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle31 console
```

The separate initial `open` occurred before the fixture installed API interception and showed four API console errors. The fixture then navigated after route interception. Final fixture result: `v0.19.0`, one synthetic provider message POST after explicit Send, context keys `concept,document,query`, responsive checks passed, and zero fixture-captured application console errors. The CLI console inspection after the final run showed zero errors and zero warnings; it listed two Chromium verbose password-field notices.

The first browser fixture run failed because the long-title assertion used row index 7 after two new rows had been added. It staged the non-searchable fallback title (41 characters). The fixture indices were corrected (nested 6, non-searchable 7, missing-all 8, long 9), and the rerun passed. A later temporary assertion assumed a synthetic hit from an unrelated index would use the selected alias's summary fallback; alias-safe rendering intentionally reuses the selected alias mapping for concrete backing-index hits, so this assertion tested an invalid fixture assumption and was removed. The dedicated alias-to-concrete scenario passed. No product changes were made by QA.

Syntax, diff, and full offline suite commands:

```text
node --check es_rag_tuner/web/app.js
node --check tests/cycle31_mapped_result_title_browser.js
git diff --check
env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v
```

The suite ran 101 tests in 6.776 seconds, exit 0, `OK (skipped=2)`. `LiveConceptAcceptance` skipped because the deliberately unreachable loopback Elasticsearch endpoint refused connection. Tokenizer parity skipped because its isolated fixture containing the four pinned tokenizer/config assets was not supplied.

Isolated package smoke used a temporary staging copy of `pyproject.toml`, `README.md`, and `es_rag_tuner/`, then ran these command forms with `/usr/bin/python3` `3.12.3`:

```text
/usr/bin/python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <temp>/wheelhouse <temp>/source
/usr/bin/python3 -m pip install --no-deps --target <temp>/install <temp>/wheelhouse/es_rag_tuning_workbench-0.19.0-py3-none-any.whl
PYTHONPATH=<temp>/install /usr/bin/python3 -c "import importlib.metadata as m,pathlib,es_rag_tuner; p=pathlib.Path(es_rag_tuner.__file__).resolve(); h=(p.parent/'web'/'index.html').read_text(); print(m.version('es-rag-tuning-workbench'),es_rag_tuner.__version__,h.split('id=\"server-version\">',1)[1].split('<',1)[0],(p.parent/'web'/'app.js').is_file())"
PYTHONPATH=<temp>/install <temp>/install/bin/es-rag-workbench --help
```

Build, install, version/page/module inspection, and CLI help exited 0. Wheel SHA256 is recorded above. Temporary source, wheel, and install trees were removed automatically. No production installation or published release was tested.

## Run notes and limitations

- The browser fixture is derived from the Cycle 30 synthetic browser scenario and adds generic-index mapped-title, alias-to-concrete-index, summary fallback, malformed/nested/non-searchable value, stale-mapping, unavailable-mapping, no-extra-request, and separate Code RAG summary-preservation checks.
- Codebase-memory graph MCP tools were not exposed in this QA session. No graph coverage or exhaustive repository claim is made.
- Requested model was `gpt-6-luna`; runtime model identity is **UNVERIFIED**.
- Synthetic browser and offline package checks do not establish live Elasticsearch behavior, provider delivery, corpus/retrieval quality, answer quality, or assistive-technology announcements.
