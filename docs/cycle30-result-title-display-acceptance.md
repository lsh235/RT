# Cycle 30 result-title display acceptance

## Scope and baseline

- Baseline: `v0.18.0`, commit `4510e044a585cb256e708c4245caae2e7f15398b`.
- Candidate: `v0.18.1`. The selected result summary is displayed in staged AI coach context. It is display-only and must not enter the provider request or persistent browser state.
- Runtime model identity: **UNVERIFIED**. Requested model was `gpt-6-luna`; QA has no independent runtime identity evidence.
- Browser tests use synthetic results and intercepted requests. No live Elasticsearch or provider account was used.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| BM25, hybrid, and vector selected summary is displayed | **PASS (synthetic browser)** | All three synthetic modes displayed their result summary in the coach readout. |
| Missing or blank summary uses `제목 없음` | **PASS (synthetic browser)** | Whitespace-only and absent summaries each displayed `제목 없음`. |
| Long title truncates at 240 characters or fewer | **PASS (synthetic browser)** | A 300-character summary staged as 240 characters including the final ellipsis. |
| XSS-shaped title is inert and escaped | **PASS (synthetic browser)** | `<img onerror>` remained escaped text; injected sentinel stayed false. |
| Staging makes no provider request; title is not persisted; Send retains query/index/id/concept | **PASS (synthetic browser)** | No session-create/message call occurred during staging. Local/session storage did not contain the title. Explicit Send created one synthetic message POST with context keys `concept`, `document`, and `query`, exact query and document index/ID. The title was absent from the POST body. |
| Clear action and unavailable-provider path | **PASS (synthetic browser)** | Provider state and unavailable indicator were asserted before staging. Clear removed the readout and emptied the persistent status text. |
| Identity, grades, settings, rankings preserved | **PASS (synthetic browser)** | Before/after snapshots matched manual/guided/concept/search inputs, concept settings, saved-grade sentinel, result order/identity/scores, and `state.lastSearch`. |
| 1280px and 390px horizontal overflow | **PASS (synthetic browser)** | At both widths document/body scroll widths equaled the viewport; hit order and coach readout remained stable. |
| Keyboard activation and accessible status structure | **PASS (DOM/keyboard); screen reader NOT RUN** | Enter activated the hybrid result action. One persistent, atomic polite `role=status` node outside the panels was populated after coach activation; the staged readout has no live-region semantics. DOM checks cannot establish actual screen-reader announcement behavior across assistive technology/browser combinations. |
| JavaScript syntax and diff checks | **PASS** | `node --check` for app and fixture; `git diff --check`. |
| Full documented offline unittest suite | **PASS: 101 tests, 2 skips** | Exit 0; `OK (skipped=2)`. Live Elasticsearch skipped because the configured loopback endpoint refused connection. Tokenizer parity skipped because the optional four-asset fixture was not supplied. Existing tests emitted `ResourceWarning` notices for unclosed fixture files; no test failed. |
| Isolated package/page/CLI smoke | **PASS** | Temporary wheel built and installed. Distribution/module versions were `0.18.1`, packaged page was `v0.18.1`, packaged `web/app.js` existed, and installed CLI `--help` exited 0. Wheel SHA256: `ed39ec2d9c823b473c12b9904ca59c78dad63606bc0c14ef055984ed17910ab0`. |
| Live Elasticsearch, real Codex/Copilot, corpus quality, user study | **NOT RUN** | Outside this synthetic QA run. |

## Research evidence and product inference

### W3C evidence checked 2026-10-18

The requested research agent model was `gpt-6-luna`; runtime model identity is **UNVERIFIED**.

- [WCAG 2.2, Success Criterion 4.1.3 Status Messages](https://www.w3.org/TR/WCAG22/): status messages that do not receive focus must be programmatically determinable so assistive technology can present them without moving focus. This supports exposing the staging update through a status semantic; it does not require announcing the full result title.
- [Understanding Success Criterion 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html): explains status-message updates and the distinction between status messages and other live-region content. This supports treating the staging announcement as status feedback while keeping the full staged context as a separate readout.
- [ARIA22: Using role=status to present status messages](https://www.w3.org/WAI/WCAG22/Techniques/aria/ARIA22): an informative technique describing `role="status"`; it is not a normative requirement to show a selected result title or use this exact implementation.

These sources support the status-region approach only. They do not prove that displaying the selected result title improves novice usability. No user study was run.

### Product inference

Showing the selected result summary beside the pending AI coach context may help a user confirm which result they staged before choosing Send. Keeping it display-only preserves the existing request context and avoids expanding what is sent to the provider. This is a usability hypothesis, not a conclusion established by WCAG or the synthetic browser checks; user-study validation remains **NOT RUN**.

## Commands and environment

Browser fixture:

```text
python3 -m http.server 18775 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle30 open http://127.0.0.1:18775/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle30 run-code --filename tests/cycle30_result_title_display_browser.js
```

The initial `open` ran before request interception and logged four API console errors. The fixture reloads after route handlers are installed; final fixture captured zero application console errors. Environment: Node `v22.23.2`, Playwright CLI wrapper `0.1.22`; Chromium build was not captured.

Syntax and full documented offline suite:

```text
node --check es_rag_tuner/web/app.js && node --check tests/cycle30_result_title_display_browser.js && git diff --check
env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v
```

The suite used Python `3.12.3`; 101 tests ran in 7.205 seconds, exit 0, with the two skips listed above.

Package smoke used `/usr/bin/python3` `3.12.3` and a `tempfile.TemporaryDirectory` harness. It copied only `pyproject.toml`, `README.md`, and `es_rag_tuner/` to a temporary source tree, then ran with the temporary directory as CWD:

```text
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <temp>/wheelhouse <temp>/source
python3 -m pip install --no-deps --target <temp>/install <temp>/wheelhouse/es_rag_tuning_workbench-0.18.1-py3-none-any.whl
PYTHONPATH=<temp>/install python3 -c "import importlib.metadata as m, pathlib, es_rag_tuner; p=pathlib.Path(es_rag_tuner.__file__).resolve(); h=(p.parent/'web'/'index.html').read_text(); print(m.version('es-rag-tuning-workbench'), es_rag_tuner.__version__, h.split('id=\"server-version\">',1)[1].split('<',1)[0], (p.parent/'web'/'app.js').is_file())"
PYTHONPATH=<temp>/install <temp>/install/bin/es-rag-workbench --help
```

All four package commands exited 0. Temporary source, wheel, and install trees were removed when the harness exited.

## Run notes and limitations

- The first browser invocation stopped at its initial accessibility assertion against pre-fix markup, which lacked a separate persistent status node. No later gates ran in that attempt. The implementation then added a persistent empty status outside panels and updates it after coach activation; the final fixture passed.
- Intermediate fixture runs exposed harness issues only: expecting clipped content to fail `isVisible`, staging while the search tab was inactive, checking decoded `innerText` instead of escaped HTML, and omitting a selected text field from the synthetic AI scope. These were corrected before the final successful run.
- Synthetic browser results cannot establish live Elasticsearch behavior, provider delivery, answer quality, retrieval quality, actual screen-reader announcements, or user-study outcomes.
- Codebase-memory graph tools were not exposed in this QA session. No graph-coverage or exhaustive repository claim is made.
