# Cycle 36 group-comparison readiness acceptance

**Date:** 2026-10-18
**Requested model:** `gpt-6-luna`
**Runtime identity:** UNVERIFIED; authoritative runtime metadata was not exposed.
**Release note:** v0.23.1 remains tentative pending coordinator review of this acceptance evidence.

## Scope and environment

The new browser fixture is `tests/cycle36_group_comparison_readiness_browser.js`. It follows the existing C35 `async page => { ... }` fixture style and uses the installed Playwright CLI wrapper after confirming `npx` is available. No test framework was added.

The final app server used a temporary SQLite path, `/tmp/es-rag-cycle36-readiness-final.sqlite3`. The browser started at `about:blank`; the fixture installed its `**/*` route before navigating to the app and intercepted every `/api/**` request, including connection, concept, schema, AI-status, and grouped-comparison routes. Responses used synthetic data. The displayed Elasticsearch URL (`http://127.0.0.1:9200`) was request data only; no app API request reached Elasticsearch or a provider during this corrected run. No corpus or credentials were used.

The fixture seeds a connected and saved two-query group with normalized matching information-need labels and the same `train` split. It also checks an unselected query, a singleton group, a changed-but-unsaved label, disconnected state, a mocked successful reconnect, a malicious query string, and a keyboard-triggered grouped comparison.

## Acceptance results

| Gate | Result | Evidence |
|---|---|---|
| Visible readiness reason, no hover, at 390px; programmatic relationship where appropriate | PASS | `#concept-mode-comparison-group-readiness` is visible and has text; the button references it with `aria-describedby`. Mobile document width equals viewport width (390px). |
| Connected and saved with two same-need/same-split queries | PASS | Hint says `2개 질의가 준비됐습니다` and describes the next comparison work. |
| Insufficient group and no selected row | PASS | Singleton hint asks for another saved query; no-selection hint asks the user to select a saved query. The button uses native `disabled` in both states. |
| Mutating a saved concept | PASS | Hint says the concept changed and must be saved; grouped comparison is disabled. |
| State updates without a grouped-comparison POST until explicit activation | PASS | Query selection, label input, disconnect, and reconnect produced zero grouped-comparison requests. |
| Keyboard activation when ready | PASS | Enter on the focused enabled button sent exactly one POST with `concept_id` and anchor `query_id`; it sent no client-supplied query, information-need, query-list, filter, or size override. |
| Existing C34 comparison and tuning controls; mobile regression | PASS | Browser fixture found `#concept-mode-comparison` and `#concept-tune`; C34 API regressions passed; 390px document width remained 390px. This checks control presence, not a full tuning run. |
| C34 tune metric identity regression | PASS | 2 synthetic/local fixture tests passed; no live Elasticsearch or provider was used. |
| Installable 0.23.1 wheel version | PASS | Installed the built wheel into fresh target `/tmp/cycle36-install.vyHV5h`; isolated import asserted `es_rag_tuner.__version__ == '0.23.1'`. |
| Hostile text handling | PASS | A saved query containing `<img src=x onerror=alert(1)>` appeared as text; no image element or page error resulted. |
| Live-region behavior during input | PASS | Readiness is not a polite live region; typing in an information-need field left the separate comparison-status live region unchanged. |
| Initial state and successful reconnect lifecycle | PASS | Initial hint was visible and nonempty before connecting. A mocked connection flow restored the previously eligible group to ready. |
| Novice user study | NOT RUN | No local empirical usability study was conducted. |
| Screen-reader/device audit | NOT RUN | No assistive-technology/device audit was conducted. |
| Pre-implementation expected-failure capture | NOT RUN | The implementation agent's `index.html`/`app.js` changes were already present at the first browser run. That initial, un-routed navigation is invalid evidence: it reached local `/api/health`, `/api/ai/status`, and `/api/codebase-status` endpoints before fixture routes were installed. `/api/ai/status` calls provider availability probes, so whether those probes made any outbound provider checks is not established by the browser log. No `/api/connect` request appears in the captured local server log, and there is no evidence of an Elasticsearch connection or model inference. The first fixture run also hit a seeding mismatch (`connectedIndex` had not been seeded), not the expected missing-hint failure. It would be inaccurate to call either run a pre-implementation baseline. |

## Commands and results

`command -v npx >/dev/null 2>&1` exited 0.

```bash
ES_RAG_CONCEPT_DB=/tmp/es-rag-cycle36-readiness-final.sqlite3 \
  python3 -m es_rag_tuner.server --host 127.0.0.1 --port 18782

/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh \
  --session cycle36qa open about:blank

/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh \
  --session cycle36qa --raw run-code --filename \
  tests/cycle36_group_comparison_readiness_browser.js
```

The corrected final browser run returned `{"result":"PASS"}`. It recorded zero browser console errors and zero page errors during the intercepted app navigation and interactions. No grouped-comparison request occurred before Enter; keyboard activation produced exactly one grouped-comparison POST. A first attempt to open the app directly before the route was installed is excluded as invalid evidence; its provider-probe scope is described above. A separate `--headed` CLI attempt could not start because this environment has no X server; it did not navigate to the app. The successful run used the default headless browser.

```bash
node --check tests/cycle36_group_comparison_readiness_browser.js
node --check es_rag_tuner/web/app.js
```

Both syntax checks exited 0.

```bash
./.venv/bin/python -m unittest discover -s tests \
  -p 'test_concept_mode_comparison_group.py' -v
```

PASS: 6 tests in 0.634s, `OK`. These are isolated API acceptance tests using test-local mocked connections.

```bash
./.venv/bin/python -m unittest discover -s tests \
  -p 'test_concept_mode_comparison_acceptance.py' -v
```

PASS: 7 tests in 0.642s, `OK`. These C34 API regression tests use local test fixtures; no real Elasticsearch was used.

```bash
./.venv/bin/python -m unittest discover -s tests \
  -p 'test_cycle34_tune_metric_identity.py' -v
```

PASS: 2 tests in 0.002s, `OK`. The tests are synthetic/local and did not contact Elasticsearch or a provider.

```bash
qa_dir=$(mktemp -d /tmp/cycle36-package.XXXXXX)
python3 -m pip wheel . --no-deps --no-build-isolation --wheel-dir "$qa_dir"
```

PASS: built `es_rag_tuning_workbench-0.23.1-py3-none-any.whl` (202,251 bytes; SHA-256 `5f3143b2398fb3fe13b9daef649a7f5c101bfeac378035d3d906e4e72c27f482`). The first wheel attempt with `./.venv/bin/python` failed because that environment does not contain setuptools (`BackendUnavailable: Cannot import 'setuptools.build_meta'`). The system Python has setuptools 68.1.2 and built the wheel successfully without build isolation or dependency installation.

```bash
install_target=$(mktemp -d /tmp/cycle36-install.XXXXXX)
python3 -m pip install --no-deps --no-index --target "$install_target" \
  /tmp/cycle36-package.GSM8dD/es_rag_tuning_workbench-0.23.1-py3-none-any.whl
PYTHONPATH="$install_target" python3 -c \
  'import es_rag_tuner; assert es_rag_tuner.__version__ == "0.23.1"; print(es_rag_tuner.__version__)'
```

PASS: pip installed `es-rag-tuning-workbench-0.23.1` into `/tmp/cycle36-install.vyHV5h`; isolated import printed `0.23.1`. This import did not access the user database or credentials.

The full repository suite was NOT RUN: the documented full suite includes live Elasticsearch/provider checks, and no full-suite command that guarantees an offline-only run was identified. This was kept within the no-real-Elasticsearch/provider boundary. No release, commit, or tag action was performed.

## Official guidance checked 2026-10-18

- The [W3C ARIA Authoring Practices Guide keyboard-interface guidance](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/) describes keyboard operability and focus conventions. It says native `disabled` removes a control from the tab sequence; `aria-disabled="true"` can preserve focusability when discoverability matters, but authors must then implement the disabled behavior. This fixture verifies normal keyboard activation while ready and visible text linked to the control. It does not audit assistive-technology announcements or establish WCAG conformance.
- [GOV.UK button guidance](https://design-system.service.gov.uk/components/button/) says disabled buttons have poor contrast and can confuse some users, advises avoiding them where possible, and recommends using them only when research shows they make the interface easier to understand. The current acceptance confirms an explicit adjacent reason and native disabled behavior while blocked; it is not user research and does not establish that GOV.UK's research condition has been met.
- [W3C cognitive accessibility guidance](https://www.w3.org/WAI/cognitive/) describes supplemental material as guidance beyond WCAG requirements. It supports considering additional cognitive-accessibility needs; it does not turn the fixture's copy checks into a standards audit or usability study.

These sources provide design guidance, not empirical evidence from users of this workbench. No novice study or screen-reader/device audit was planned or performed.
