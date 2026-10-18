# Cycle 24 search score guidance acceptance

## Scope and baseline

- Baseline supplied for this cycle: `main` at `9d91c2a`, version `v0.17.4`.
- Package checked: `0.17.5`.
- Requested QA model override: `gpt-6-luna`; runtime identity is **UNVERIFIED** because available telemetry does not prove the executing model.
- QA-owned files: [synthetic browser fixture](../tests/cycle24_score_interpretation_browser.js) and this report. Implementation owned `es_rag_tuner/web/app.js`, `es_rag_tuner/web/style.css`, `es_rag_tuner/web/index.html`, `README.md`, `pyproject.toml`, and `es_rag_tuner/__init__.py`. QA made no edits to implementation files and performed no Git operations. The unrelated untracked user documents `docs/agent-sdk-upstream-review-2026-10-18.md` and `docs/novice-retrieval-improvements-2026-10-18.md` were preserved.
- Scope is visible score explanation in BM25, vector, hybrid/RRF, and code+Jira views that show Jira hits with RRF scores. No score calculation, ordering, search request, mode selection, or score-label change is accepted by this check. No live Elasticsearch, user DB/corpus, or provider was used.

## Interpretation and research

Checked 2026-10-18. Elastic documents `_score` as a query relevance score and describes BM25 as the default text similarity; vector scores are derived from the configured similarity metric; and RRF calculates a combined score from result ranks. These sources support the mode distinctions tested here, not any claim about retrieval quality or the behavior of a particular user corpus: [query and filter context](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-filter-context), [BM25 similarity settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity), [dense vector field type](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector), and [reciprocal rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).

The UI guidance says BM25 is a text-match score, not a probability or user relevance grade; vector scores depend on the selected embedding/similarity setup and are not directly comparable with BM25 or other model settings; RRF combines result ranks rather than raw BM25/vector values, whose scales differ, and its score is not a probability. It makes no quality, accuracy, correctness, or relevance verdict.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Mode-specific visible guidance and replacement | **PASS (synthetic)** | The browser drove ordinary BM25, vector, hybrid/RRF, and code+Jira search through the UI. It checked visible summary guidance for each mode and asserted each new mode omitted the prior mode’s distinctive guidance. Code+Jira guidance was checked while synthetic Jira hits carried RRF scores. |
| Hybrid component score caveats | **PASS (synthetic)** | Synthetic hybrid and Jira hits displayed BM25 `18.7500`, vector `0.8123`, and RRF `0.0328`; assertions checked that RRF guidance explains rank fusion, that the displayed raw component scores are not summed, and that BM25/vector raw scores use different scales and cannot be compared directly. The second hit values were `3.5000`, `0.4012`, and `0.0161`. |
| Scores, labels, result order, query and API behavior | **PASS (synthetic)** | For each mode the fixture asserted synthetic hit ID order and displayed numeric scores were unchanged. BM25/vector displayed `7.2500`, `2.5000`; hybrid/code+Jira displayed `0.0328`, `0.0161`; hybrid labels remained `RRF SCORE`. Captured search POSTs were exactly BM25, vector, hybrid, then code_rag with the unchanged synthetic query; the first three used `/api/search` and code_rag used `/api/code-rag`. Rendering created no additional search calls. |
| Bounded language and mobile width | **PASS (synthetic)** | Guidance assertions reject percentage, accuracy, precision, recall, quality guarantee, relevance verdict, or answer-correctness language. At 390×844, document and body scroll widths did not exceed the viewport. |
| Browser console | **PASS (synthetic)** | All `/api/**` requests were intercepted before reload. The fixture observed zero application console errors. Final Playwright console inspection showed 0 errors and 0 warnings, plus two browser verbose password-field notices. Static-server initial navigation had four API errors before fixture interception; those were outside the post-mock check. |
| JavaScript syntax | **PASS** | `node --check es_rag_tuner/web/app.js && node --check tests/cycle24_score_interpretation_browser.js` — exit 0. |
| Offline full suite | **PASS (limited)** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v` — `Ran 101 tests in 7.179s`, `OK (skipped=2)`, exit 0. Exact skips: `test_concept_live_acceptance.LiveConceptAcceptance` because the configured Elasticsearch loopback endpoint refused connection; opt-in tokenizer parity because its isolated fixture did not contain the four pinned tokenizer/config assets. These are skips, not live Elasticsearch or tokenizer-parity passes. A pytest invocation was **NOT RUN** because `.venv` has no `pytest` module; the repository’s documented unittest suite was run instead. |
| Isolated wheel/install/module/CLI | **PASS** | Staged `pyproject.toml`, `README.md`, and `es_rag_tuner/` in `/tmp/cycle24-wheel-8dfenmpg/src`, excluding `*.egg-info`; built using `python3 -m pip wheel --no-deps --no-build-isolation`; installed with `python3 -m pip install --no-deps --target`; from outside the checkout, module and distribution metadata both reported `0.17.5`, packaged `web/app.js` existed, and installed `es-rag-workbench --help` exited 0. Wheel SHA256: `57699c709bb77e24fa95181036484af36d92ea8a1b95c53ecf6c6ddd0d4cfafe`. Temporary staging and installation are outside the repository. |
| Live search, user data, provider, retrieval quality | **NOT RUN** | Browser responses were synthetic and all browser API calls intercepted. The full suite used an unreachable Elasticsearch URL. No live provider, user database/corpus, or user outcome was accessed or evaluated. |
| Runtime model identity | **UNVERIFIED** | `gpt-6-luna` was requested for QA; telemetry does not establish runtime model identity. |

### Browser command

Started `python3 -m http.server 18774 --bind 127.0.0.1 --directory es_rag_tuner/web`, then ran:

```text
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle24 open http://127.0.0.1:18774/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle24 run-code --filename tests/cycle24_score_interpretation_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle24 console
```

The browser fixture returns successfully after all assertions. Its first attempt timed out because setup marked connection state true without enabling the disabled search button; QA corrected the fixture to enable the button and added bounded mode-aware summary waits and failure diagnostics. The final fixture and console command passed. The static server and browser were local only.

No implementation changes were made by QA. The browser fixture and this report are the only QA-owned repository files.
