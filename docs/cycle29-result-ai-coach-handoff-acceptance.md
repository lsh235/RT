# Cycle 29 result-to-AI-coach handoff acceptance

## Scope and baseline

- Baseline supplied by the coordinator: `main`, `v0.17.9`, commit `b4f9d505548eec6ff15d2e4ff716b72b1daf6194`.
- Candidate: an explicit result-card action stages a visible, clearable result context and message draft in the existing AI coach. It does not create a provider session or post a message until the user explicitly sends.
- Implementation owns product files. QA owns this report and [`tests/cycle29_result_ai_coach_handoff_browser.js`](../tests/cycle29_result_ai_coach_handoff_browser.js). Requested model was `gpt-6-luna`; runtime model identity is **UNVERIFIED**.
- Browser requests use synthetic local fixtures. No live Elasticsearch, provider, corpus, or account is used.

## Research evidence and product inference

### Source evidence from prior Cycle 29 research

This is the coordinator-provided summary of prior research, not new live research performed by QA:

- Elasticsearch's [Explain API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-explain) exposes whether one supplied document matches one supplied query, with a value, description, and detail tree.
- Elastic's [scoring and Explain API article](https://www.elastic.co/search-labs/blog/elasticsearch-scoring-and-explain-api) describes Elasticsearch's scoring calculation. BM25 factors explain mechanics; they are not a human relevance verdict.
- Both sources were checked on `2026-10-18` by the prior research effort.

### Product inference

Cycle 24 already provides score-tree guidance. Repeating another score-tree summary would add little. An explicit handoff to the existing AI coach gives the user an optional way to ask about a specific returned result while preserving the current coach workflow. Requiring a separate Send action keeps staging local and user-controlled. These are product choices, not conclusions established by Elastic documentation. A synthetic browser pass cannot establish that a provider gives a useful interpretation or that the result is relevant.

## Final acceptance results

Final gates ran after the Send-handler fix and the follow-up successful-retry cleanup fix were ready. The first post-Send-fix browser attempt surfaced the fixture's intentionally returned HTTP 503 as a browser console resource error. The fixture was adjusted to represent the same non-OK application response without an underlying non-2xx network status. A later preservation review expanded the pre/post snapshot, and a retry cleanup assertion verifies the staged state/readout is removed after a successful retry and ordinary coach context returns to the current guided query/manual document inputs. The final browser rerun and all other gates below passed after these changes.

| Gate | Status | Evidence |
|---|---|---|
| BM25, hybrid, and vector results expose the handoff action; Enter activates it | **PASS (synthetic browser)** | Synthetic BM25, hybrid, and vector cards staged context. Keyboard Enter activated the hybrid card action. |
| Handoff stages visible context and a message draft, switches to the coach, and does not create a session or post a message | **PASS (synthetic browser)** | Four standalone staging-and-clear cases covered BM25, hybrid, vector, and an unavailable provider. A fifth handoff staged the vector result for the explicit-Send scenario. None of these five handoffs called `/api/ai/sessions/create` or `/api/ai/sessions/message` before explicit Send. Two `/api/ai/status` checks were observed and allowed. |
| Clear action removes staged context; unavailable provider does not block local staging | **PASS (synthetic browser)** | Each staged context exposed `button[data-clear-ai-staged-context]`; the unavailable-provider scenario staged and cleared locally with no session/message call. |
| Explicit Send posts the exact search query and document identity, including fallback and explicit alias index paths | **PASS (synthetic browser)** | Sent query was `exact timeout phrase / cycle29`, matching `state.lastSearch.query`. Vector hit with empty `_index` posted selected index `selected-index` and exact URL-sensitive ID `VECTOR/only?x=a&y=b#section`. Hybrid hit posted exact `_index` `hybrid-alias` and ID `HYB/one?mode=rrf&part=1`. One session create and three message posts occurred only after explicit Send/retry actions. |
| Failed-send retry preserves message and exact context, then clears the sent staged selection | **PASS (synthetic browser)** | A synthetic application-level failure caused the retry path; retry posted the same message and byte-for-byte-equivalent serialized context. After successful retry, `state.stagedAiResultContext` was null, the staged readout was absent, and `aiContext()` used the current guided query and manual document ID rather than the prior result. The fixture returned HTTP 200 and wrapped one marked response as non-OK in `fetch` to avoid a browser network-error console entry; this tests application retry handling, not a real provider/network failure. |
| Handoff preserves user inputs, manual document ID, concept settings, saved-query settings, search settings, result order/scores, and saved-grade sentinel | **PASS (synthetic browser)** | The expanded pre/post snapshots matched for guided/manual/search/concept query inputs; checked text and filter fields plus filter rows; concept name/description/aliases/exclusions/title field, concept weights, result counts and field boosts; both saved-query rows and selected query; search mode/size/RRF constant; grade and note; `state.lastSearch`; and card IDs/order, indices, and scores. This was rerun after adding the preservation assertions. |
| XSS-shaped metadata remains inert; no app console errors | **PASS (synthetic browser)** | `<img>` summary and script-shaped URL-sensitive ID were escaped; the injected flag remained false. Fixture-captured console errors: 0. |
| 1280px and 390px responsive widths have no horizontal overflow; results and staged context remain stable | **PASS (synthetic browser)** | At 1280×900 and 390×844, document/body widths equaled viewport widths; card data and visible context were unchanged across resizing. |
| JavaScript syntax and whitespace validation | **PASS** | `node --check es_rag_tuner/web/app.js`, `node --check tests/cycle29_result_ai_coach_handoff_browser.js`, and `git diff --check` exited 0. |
| Full documented offline unittest suite | **PASS (limited, two skips)** | 101 tests ran, `OK (skipped=2)`, exit 0. The live Elasticsearch class skipped because the configured loopback endpoint refused connection. Optional tokenizer parity skipped because its four pinned fixture assets were not supplied. |
| Isolated wheel, install, module/page version, and CLI smoke | **PASS** | Built and installed `es_rag_tuning_workbench-0.18.0-py3-none-any.whl` outside the checkout. Distribution/module versions were `0.18.0`, packaged `web/app.js` existed, page label was `v0.18.0`, and installed CLI `--help` exited 0. Wheel SHA256: `3d4ba780c2dc56d3877ec549b63e3a09c40b22767aa8735c3d629356acb82998`. |
| Live Elasticsearch, actual corpus, retrieval quality, real Codex/Copilot access or behavior, and user-study behavior | **NOT RUN** | Outside the synthetic acceptance scope. No production or retrieval-quality claim is made. |

## Commands and environment

Final browser run:

```text
python3 -m http.server 18775 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle29 open http://127.0.0.1:18775/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle29 run-code --filename tests/cycle29_result_ai_coach_handoff_browser.js
```

The initial CLI `open` occurs before the fixture can install request routes and logged four unmocked API errors. The browser fixture then reloads the page after installing route handlers; its captured application console errors during the acceptance run were zero. Playwright reported two Chromium password-field verbose notices on initial navigation; these were not application errors. Chromium build number was not captured.

Syntax and offline suite:

```text
node --check es_rag_tuner/web/app.js && node --check tests/cycle29_result_ai_coach_handoff_browser.js && git diff --check
env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v
```

The offline suite used Python `3.12.3`; Node was `v22.23.2`, `npx` was `10.9.8`, and the Playwright CLI wrapper was `0.1.22`. The two skips are not Elasticsearch or tokenizer-parity passes. Existing tests emitted a few `ResourceWarning` messages for unclosed fixture file objects; they did not fail the suite.

Package smoke used a Python 3 `tempfile.TemporaryDirectory` harness to copy only `pyproject.toml`, `README.md`, and `es_rag_tuner/` into `<temp>/source`, then ran these subprocess commands:

```text
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <temp>/wheelhouse <temp>/source
python3 -m pip install --no-deps --target <temp>/install <temp>/wheelhouse/es_rag_tuning_workbench-0.18.0-py3-none-any.whl
PYTHONPATH=<temp>/install python3 -c "import importlib.metadata as m, es_rag_tuner, pathlib; p=pathlib.Path(es_rag_tuner.__file__).resolve(); h=(p.parent/'web'/'index.html').read_text(); print(m.version('es-rag-tuning-workbench'), es_rag_tuner.__version__, (p.parent/'web'/'app.js').is_file(), h.split('id=\"server-version\">',1)[1].split('<',1)[0])"
PYTHONPATH=<temp>/install <temp>/install/bin/es-rag-workbench --help
```

All four commands ran with `<temp>` as their current working directory; the metadata/module probe and CLI command used `PYTHONPATH=<temp>/install`. The wheel was hashed after build. An earlier probe ran from the repository root and resolved the pre-existing workspace egg-info version `0.13.1` for distribution metadata while the installed module/page were `0.18.0`; the final probes from `<temp>` had no cwd shadowing. The temporary staging tree was automatically removed when the Python harness exited.

## Run notes and limits

The first fixture invocation had a duplicate `const` declaration and stopped at parse time; the QA fixture was corrected. A later fixture comparison used layout-sensitive `innerText` for the grade sentinel and was changed to `textContent`. A fixture navigation omission also left a later result button inside a hidden tab; explicit tab activation fixed it. A preservation review found the original snapshot did not assert the selected filter, concept numeric settings, saved-query rows/selection, or search settings. Those sentinels and comparisons were added. These were QA harness issues, not product findings.

Independent browser QA found two genuine pre-fix product defects. First, the primary Send listener passed its click event to `sendAiMessage(retry = false)`. The truthy event selected the retry path, which returned because `state.aiLastMessage` was empty; no session or message request was made. The implementation changed the listener to call `sendAiMessage()` without passing the event. Second, successful retry left the matching staged result context visible and active, so later ordinary coach messages could inherit stale result context. The implementation now clears the matching staged context on successful delivery, including retry, while retaining a distinct context staged during an in-flight request. The final browser, syntax, offline suite, and package gates passed after both fixes.

The browser fixtures intercept application API requests and use synthetic result cards, provider status, session, and job responses. The failed-send retry is a simulated application-level error. No live Elasticsearch, real document, actual AI provider, provider quota, retrieval accuracy, model quality, human relevance judgment, user behavior, or production installation was tested.

## Codebase exploration note

Graph MCP tools were not exposed in this QA session. The coordinator used bounded direct source reads for the relevant paths; no graph index coverage or graph-derived completeness claim is made here.
