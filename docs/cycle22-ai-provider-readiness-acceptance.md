# Cycle 22 AI provider readiness acceptance

## Scope and baseline

- Baseline supplied for this cycle: `main` / `v0.17.2`, commit `c1d3941`.
- Package checked: `0.17.3`.
- Requested QA assignment: `gpt-6-luna`; runtime model identity is **UNVERIFIED** because available telemetry does not establish it.
- QA-owned files: [synthetic browser fixture](../tests/cycle22_ai_provider_readiness_browser.js) and this report. Implementation work was limited to copy and package metadata. QA made no source edits or Git operations. Unrelated user documents `docs/agent-sdk-upstream-review-2026-10-18.md` and `docs/novice-retrieval-improvements-2026-10-18.md` were preserved.
- Scope: distinguish a provider SDK/login/account/catalog readiness probe from the success, entitlement, or usage of a specific inference request. No live provider, Elasticsearch, user database, or corpus access occurred.

## Research and interpretation

Sources checked 2026-10-18. They describe SDK operations and status/catalog APIs separately from message/turn execution. That supports the narrow product-copy distinction that a status probe is not itself an inference result. This is general SDK/product-design inference, **not evidence of a provider defect or proof of live inference behavior**. The Sign in with ChatGPT app-server source concerns that separate OAuth configuration and is not treated as a statement about this workbench's existing SDK authentication route. User testing and live provider checks are **NOT RUN**.

- [GitHub Copilot SDK/CLI compatibility](https://docs.github.com/en/copilot/how-tos/copilot-sdk/troubleshooting/compatibility) lists `getAuthStatus()` as a login-state check separately from `sendAndWait()` for sending a message and waiting for completion.
- [GitHub Copilot SDK Node.js README](https://github.com/github/copilot-sdk/blob/main/nodejs/README.md) documents `send()` and `sendAndWait()` as message execution operations.
- [OpenAI Codex Python SDK API reference](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md) exposes `account(...)`, `models(...)`, and `thread.run(...)` as distinct operations.
- [OpenAI Sign in with ChatGPT Codex app-server guide](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) says, for that OAuth/app-server configuration, that a returned model list can be a bundled client catalog rather than an entitlement check; a completed inference turn verifies access for that request. This separate integration path is not evidence about the current app's runtime or account entitlement.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Ready status wording and inference boundary | **PASS (synthetic)** | With `available: true`, browser UI says `SDK·로그인 상태 확인됨`. It does not say “요청 가능” or promise a response. Explanatory text says it checks only SDK/login, that provider access or usage limits can cause the actual model response to fail, and that response status is known from the request result. |
| Other provider states and no inference on status check | **PASS (synthetic)** | Mocked sign-in-required, SDK-missing, and unavailable responses show distinct existing setup guidance and keep send disabled. The fixture records AI routes and verifies refresh/status checks call only `/api/ai/status`; no session creation, message, or job route is called. |
| App-scoped session caveat | **PASS (synthetic)** | Ready-state help text says the conversation is a separate session in this app and does not load existing Codex/Copilot chats. |
| Accessibility and narrow viewport | **PASS (synthetic)** | Status keeps `aria-live="polite"`. Headless Chromium at 390×844 reports both document and body widths within the viewport. After mocked routes are installed and the app reloads, the fixture records zero application console errors. Final Playwright console inspection had 0 errors and 0 warnings; it displayed two browser verbose password-field notices. Initial static-server errors occurred before mock installation and reload. |
| Provider send gating | **PASS (synthetic)** | With a synthetic connected state and ready provider, send is enabled; for sign-in-required, missing SDK, and unavailable states, send stays disabled. No inference request was sent. |
| Package/module/UI versions | **PASS** | `pyproject.toml`, `es_rag_tuner.__version__`, and `#server-version` all report `0.17.3`; isolated installed module and distribution metadata also report `0.17.3`. |
| Syntax | **PASS** | `node --check tests/cycle22_ai_provider_readiness_browser.js` and `node --check es_rag_tuner/web/app.js` exited 0. |
| Full offline suite | **PASS (limited)** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 python3 -m unittest discover -s tests -v` — `Ran 101 tests in 6.342s`, `OK (skipped=2)`, exit 0. Live Elasticsearch acceptance skipped because the loopback endpoint refused connection; tokenizer parity skipped because its opt-in tokenizer assets were unavailable. These are not live Elasticsearch/provider or tokenizer-parity passes. |
| Isolated wheel/install/module/CLI smoke | **PASS** | Temporary staging copied only `pyproject.toml`, `README.md`, and `es_rag_tuner/` while excluding `*.egg-info`. `pip wheel --no-deps --no-build-isolation` built `es_rag_tuning_workbench-0.17.3-py3-none-any.whl`; `pip install --no-deps --target` installed it. From outside the repository, installed module version and distribution metadata were both `0.17.3`, packaged `web/app.js` was present, and `es-rag-workbench --help` exited 0 (`usage: es-rag-workbench [-h] [--host HOST] [--port PORT]`). Temporary staging was removed. |
| Live provider / Elasticsearch / database / corpus / user testing | **NOT RUN** | Provider status and response bodies were synthetic browser fixtures. The full suite used the explicitly unreachable loopback Elasticsearch address. No live inference, user database/corpus, or user study was tested. |
| Runtime model identity | **UNVERIFIED** | `gpt-6-luna` was the requested QA assignment; runtime identity is not established by available telemetry. |

## Browser command and limits

Started `python3 -m http.server 18769 --bind 127.0.0.1 --directory es_rag_tuner/web`, then ran:

```text
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle22pass open http://127.0.0.1:18769/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle22pass run-code --filename tests/cycle22_ai_provider_readiness_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle22pass console
```

The fixture intercepts all `/api/**` requests before reload and provides only synthetic provider status/version data. This validates UI wording, state selection, and local gating; it does not establish account entitlement, actual response success, usage, or current provider availability.

## Iteration note

An initial fixture version used a readiness-label phrase while waiting for the unavailable status, but the UI status is shorter and the detailed setup text carries the explanation. The assertion was corrected to check the actual status label plus setup hint. A first draft also expected a numbered sixth step in the novice quickstart; the browser task does not use README step numbering, and the final fixture/report is scoped to the requested provider-readiness UI only. No implementation defect or acceptance failure remained open.
