# Cycle 20 tune readiness acceptance

## Scope and baseline

- Baseline supplied for this cycle: `v0.17.0`, commit `469b6e0`.
- Package checked: `0.17.1`.
- Requested QA model override: `gpt-6-luna`; runtime identity is **UNVERIFIED** because task telemetry does not prove the executing model.
- QA-owned files: [browser fixture](../tests/cycle20_tune_readiness_browser.js) and this report. The implementation worker owned the six implementation files. The two unrelated untracked user documents `docs/agent-sdk-upstream-review-2026-10-18.md` and `docs/novice-retrieval-improvements-2026-10-18.md` were left untouched. No Git operations were performed by QA.
- Scope boundary: UI wording and progressive disclosure of readiness computed by the existing readiness endpoint. Eligibility remains a training-positive-label readiness signal; this acceptance does not assert adequacy, representativeness, retrieval quality, or user benefit. No live Elasticsearch, user database, corpus, credentials, or provider service was accessed.

## Research inputs and interpretation

Checked 2026-10-18. These sources give general content, disclosure, and accessibility guidance; they are **not evidence that this product or its readiness signal improves RAG outcomes**. Applying them here (short status first, optional detail, plain language, visible scope caveat, keyboard-operable native disclosure, and a concise status announcement) is product design inference. User testing is **NOT RUN**.

- [GOV.UK clear structure](https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/clear-structure/)
- [GOV.UK Details component](https://design-system.service.gov.uk/components/details/)
- [GOV.UK Accordion](https://design-system.service.gov.uk/components/accordion/)
- [DfE Plain Language](https://design.education.gov.uk/content-design/plain-language)
- [Home Office Alert guidance](https://design.homeoffice.gov.uk/design-system/components?name=Alert)
- [WCAG 2.2, 4.1.3 Status Messages](https://www.w3.org/TR/WCAG22/#status-messages)
- [W3C Understanding Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Concise readiness and boundary language | **PASS (synthetic)** | Browser fixture exercises ready and not-ready responses. The not-ready copy requires a positive training judgment and says validation-only judgments do not qualify. A separate visible caveat says readiness does not establish label sufficiency, representativeness, or search quality. Ready status is short and separate from quality. |
| Progressive details and count fidelity | **PASS (synthetic)** | Expanded native disclosure shows all mocked training/validation document counts, graded and positive query counts, information-need-group counts, stale exclusion count, the no-minimum caveat, and interpretation limits. Assertions compare text against the exact synthetic response values; no adequacy/search-quality claim is accepted. |
| Empty/loading/error/malformed/stale behavior | **PASS (synthetic)** | Empty concept, delayed loading, malformed structured response, invalid JSON/API parse failure, and a delayed response after concept mutation are exercised. The stale response does not publish readiness for the changed concept. The browser also checks the established server-authoritative tune button behavior remains enabled for a connected saved concept; this browser fixture does not invoke the tune endpoint. |
| Native disclosure and status accessibility | **PASS (synthetic)** | Readiness status has `aria-live="polite"`; the details container itself has no live-region attribute; native `<details>/<summary>` opens and closes on keyboard Enter. User assistive-technology testing was not performed. |
| Mobile and browser console | **PASS (synthetic)** | Headless Chromium at 390×844: document and body scroll widths do not exceed viewport width. The fixture observes zero application console errors after mocked routes are installed and the page is reloaded. Final Playwright console inspection showed 0 errors/0 warnings and two browser verbose password-field notices. Static-server first-open 404/501 messages occurred before route interception and are not included in the post-mock assertion. |
| Syntax | **PASS** | `node --check tests/cycle20_tune_readiness_browser.js` and `node --check es_rag_tuner/web/app.js` exited 0. Environment: Node `v22.23.2`. |
| Full offline suite | **PASS (limited)** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 python3 -m unittest discover -s tests -v` — `Ran 101 tests in 6.326s`, `OK (skipped=2)`, exit 0. Live Elasticsearch acceptance skipped because the configured loopback endpoint refused connection. The opt-in tokenizer parity check skipped because its tokenizer assets were unavailable. These skips are not live-provider or tokenizer-parity passes. Environment: Python `3.12.3`. |
| Isolated wheel/install/module/CLI | **PASS** | Staged only `pyproject.toml`, `README.md`, and `es_rag_tuner/` in a temporary directory while excluding source `*.egg-info`; built with `python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir <tmp>/wheelhouse <tmp>/src`; installed with `python3 -m pip install --no-deps --target <tmp>/install <wheel>`; from outside the repo, verified installed module version and installed distribution metadata both `0.17.1`, packaged `web/app.js` present, and `es-rag-workbench --help` exit 0 (`usage: es-rag-workbench [-h] [--host HOST] [--port PORT]`). All staged files were temporary. |
| Live Elasticsearch / DB / corpus / provider / user outcomes | **NOT RUN** | Browser API responses were synthetic. The full suite was configured with an unreachable loopback Elasticsearch endpoint. No live search, user corpus/database, provider service, or user study was used. |
| Runtime model identity | **UNVERIFIED** | `gpt-6-luna` was the requested QA override. Runtime identity is not established by the available telemetry. |

### Browser command

Started `python3 -m http.server 18769 --bind 127.0.0.1 --directory es_rag_tuner/web`, then ran:

```text
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle20 open http://127.0.0.1:18769/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle20 run-code --filename tests/cycle20_tune_readiness_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle20 console
```

The fixture installs route mocks before reloading the app. No non-loopback target is contacted.

## Iteration notes

- First browser run failed an assertion because QA looked for the visible caveat inside the details container; the implementation places it in a separate persistent paragraph. The assertion was corrected to inspect that paragraph.
- The next run exposed a QA assertion bug: `aria-live` absence is represented as `null`, not a falsey serialized DOM attribute. The assertion now checks exact null and reads the native disclosure tag name directly.
- A mocked HTTP 503 produced a browser “Failed to load resource” console error. To keep the required zero-console-error post-mock gate while still exercising the catch path, the final API-error case returns HTTP 200 with invalid JSON; the separate malformed-structured-response case is also covered.
- Initial wheel metadata inspection from the repository directory found a pre-existing local `0.13.1` egg-info entry, despite the newly built wheel and module being `0.17.1`. The isolated staging was corrected to exclude source egg-info and metadata checks now run with the temporary directory as cwd. Final installed distribution metadata and module version both report `0.17.1`.

No implementation edits were made by QA. The browser fixture and this record are the only QA-owned files.
