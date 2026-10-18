# Cycle 12 information-need suggestions acceptance

Date: 2026-10-18

Baseline: `1fe2cec` / `v0.12.0`.

Requested model override: `gpt-6-luna`. Runtime identity cannot be independently verified from the available tool output, so application of the override is unverified.

## Scope and boundary

This QA slice checks an optional native `<datalist>` for information-need labels already entered on concept query rows. Suggestions must be derived from the current editor rows, separated by train/validation split, and deduplicated after the UI's defined whitespace normalization and ASCII `A-Z` folding. Unicode casefold-only equivalents such as `Straße` and `STRASSE` may remain separate suggestions; UI deduplication must not falsely merge distinct backend groups. Backend Python casefold grouping and judgment fingerprints remain authoritative and unchanged. Suggestions stay optional, and blank and novel free-text values remain saveable. Suggestions must not change query identity, query text, split, judgment freshness/fingerprint, serialized retrieval requests, or retrieval output.

Automated API acceptance uses a temporary SQLite database and mocked Elasticsearch responses. Browser acceptance uses only synthetic concept data on loopback. No real documents, configured database, credentials, or live Elasticsearch are in scope. A successful wrapper or command alone is not enough to mark a test pass; skipped checks remain `NOT RUN`.

## Acceptance gates

| Gate | Required evidence | Status |
| --- | --- | --- |
| Current split, deduplication, blank filtering, hostile values | Inspect rendered datalist options: only labels from current rows in the same split; whitespace and ASCII case variants collapse to one readable option; `Straße`/`STRASSE` remain distinct; blank omitted; hostile strings appear as literal option values without markup execution. | PASS |
| Refresh behavior | Observe option updates after loading a concept, adding a row, editing a label, deleting a row, and changing split. | PASS |
| Keyboard and free text | In the named browser, focus the label input, type a prefix, use ArrowDown/Enter to select; ordinary typing, clear-to-blank, Tab, and Escape remain usable. No flow requires selection. | PASS in Firefox 156; Chrome headless selection did not verify |
| Save and reload | Save a selected existing label, a novel unselected label, and a blank value; reload and confirm labels plus exact query IDs/text/split. | PASS |
| Retrieval/freshness invariance | Automated check confirms stable query ID/text/split, judgment query fingerprint/freshness, identical serialized mocked search bodies, and identical candidate/baseline hit IDs/order after label changes. | PASS |
| Responsive layout | Inspect 320, 390, 760, and 1280 CSS-pixel viewport widths; no clipping or overlap in the query row or label input. | PASS |
| Bounded offline regression | Focused acceptance, relevant existing regressions, full offline suite with skip reasons, syntax/diff checks, and wheel/install/CLI smoke as feasible. | PASS with two suite skips |
| Assistive technology/browser breadth | Report exact tested browser and AT combinations. Native datalist support is uneven; do not claim universal accessibility from one browser run. | PASS for coverage disclosure; no AT tested |
| Live Elasticsearch/customer data | Deliberately excluded. | NOT RUN |

## Execution record

The implementation-ready signal was received before test commands were started. All temporary databases and browser fixtures used synthetic values under `/tmp` and loopback only.

The acceptance test file is `tests/test_information_need_suggestions_acceptance.py`. Its intended focused command is:

```bash
./.venv/bin/python -m unittest discover -s tests -p 'test_information_need_suggestions_acceptance.py' -v
```

Playwright prerequisite check: `command -v npx` succeeded. Browser work used `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh` (`@playwright/cli` 0.1.22), snapshot-first. Browsers were headless Google Chrome 154.0.8037.97 and headless Firefox 156.0 (Playwright Firefox build `v1553`) on Linux x86_64; Node v22.23.2, npm 10.9.8, repository Python 3.12.3. No assistive technology was available or tested.

### Automated and package evidence

| Gate | Status | Exact command/environment/result/boundary |
| --- | --- | --- |
| Focused Cycle 12 acceptance | PASS | `./.venv/bin/python -m unittest discover -s tests -p 'test_information_need_suggestions_acceptance.py' -v`; Python 3.12.3; 2 tests in 0.142s. Temporary SQLite, synthetic labels/IDs, mocked Elasticsearch responses. Confirms selected, novel, hostile-looking, and blank values save/reload; exact query rows stay intact; judgment query fingerprint/freshness and mocked search request bodies plus returned IDs/order stay unchanged after label-only edits. |
| Cycle 11 group regression | PASS | `./.venv/bin/python -m unittest discover -s tests -p 'test_information_need_groups_acceptance.py' -v`; 7 tests in 0.191s, `OK`. |
| Tune readiness regression | PASS | `./.venv/bin/python -m unittest discover -s tests -p 'test_concept_tune_readiness.py' -v`; 12 tests in 0.643s, `OK`. |
| Full offline suite | PASS with skips | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:9 ES_RAG_ACCEPTANCE_SOURCE_INDEX=cycle12-synthetic-unused ./.venv/bin/python -m unittest discover -s tests -v`; 74 tests in 5.108s, `OK (skipped=2)`. The live Elasticsearch class skipped because the deliberately refused loopback endpoint returned connection refused. Tokenizer parity skipped because its isolated fixture of four pinned tokenizer/config assets was not supplied. These skips are not passes. |
| Syntax and whitespace | PASS | `node --check es_rag_tuner/web/app.js`; `./.venv/bin/python -m py_compile tests/test_information_need_suggestions_acceptance.py`; `git diff --check` over changed tracked files — all exited 0. |
| Wheel | PASS | `./.venv/bin/python -m pip wheel . --no-deps --wheel-dir /tmp/es-rag-cycle12-package.nb6BMA/wheel`; built `es_rag_tuning_workbench-0.12.1-py3-none-any.whl`, 176141 bytes, SHA-256 `4986d71f0f59d8ab966779d25d03f500b525e7314f90daa411acd7ba13e0b145`. |
| Isolated install and CLI | PASS | Created `/tmp/es-rag-cycle12-package.nb6BMA/venv`, installed the wheel with `/tmp/es-rag-cycle12-package.nb6BMA/venv/bin/python -m pip install --no-deps --no-index /tmp/es-rag-cycle12-package.nb6BMA/wheel/es_rag_tuning_workbench-0.12.1-py3-none-any.whl`; `/tmp/es-rag-cycle12-package.nb6BMA/venv/bin/es-rag-workbench --help` exited 0. |
| Installed service smoke | PASS | Started the isolated installed CLI on `127.0.0.1:57432` with `ES_RAG_CONCEPT_DB=/tmp/es-rag-cycle12-package.nb6BMA/concepts.sqlite3`; `/api/health` returned `{"ok":true,"version":"0.12.1"}`. Synthetic concept save/list preserved exact selected label and blank query rows. No Elasticsearch request was made. |

### Browser evidence

Synthetic fixture: temporary SQLite at `/tmp/es-rag-cycle12.CRhTJu/concepts.sqlite3`, workbench at `http://127.0.0.1:57431`, concept `cycle12-browser-fixture`. Because this app populates saved concepts after connection, the CLI invoked the page's existing `loadConcepts()` helper to populate the selector from the synthetic local API; the concept itself was selected and loaded with the normal UI controls. For UI save/reload, the page was given one synthetic `body` text-field schema via `renderSchemaChoices()` (no Elasticsearch connection or request), then the normal Save and Load UI controls were used.

Rendered options showed same-split values only. The `train-a` and `train-b` rows had `Ops owner`/`ops owner` spellings; each list collapsed their identity to one readable option. The blank train row omitted empty entries. The validation row did not show train-only labels. Both `Straße` and `STRASSE` were present as separate options. The hostile-looking value `literal <img src=x onerror=alert(1)>` appeared literally; `document.querySelectorAll('img').length` returned `0`.

Refresh was observed after concept load, adding a row, editing a label (`Network owner` appeared in other same-split rows), deleting the row (the value disappeared), and changing a row from train to validation (its list switched to the validation label only). A UI save and reload preserved `train-b` / `who owns the service` / `train` / `ops owner`, `train-empty` / `show a blank training label` / `train` / `Arbitrary new label`, and `validation` / `validate the owner` / `validation` / blank, with the remaining query IDs and fields intact.

At 320, 390, 760, and 1280 CSS pixels, `document.documentElement.scrollWidth` equaled the viewport width. Query rows and their label fields stayed within the row bounds; the 320/390 layouts stacked the controls, while 760/1280 used the wider row layout. Geometry inspection found no horizontal clipping or field overlap. No screenshot is retained.

The keyboard popup selection test **PASSed in headless Firefox 156.0**. On the synthetic concept, the target train row had one option, `Ops`; focusing its blank information-need input, typing the non-exact prefix `O`, and pressing ArrowDown then Enter changed the input value to `Ops`. This verifies native keyboard selection in this browser. In headless Chrome 154, the same prefix sequence left the value as `O`, so Chrome did not verify native selection. Headed CLI launch failed because no X server or `$DISPLAY` is available; `xvfb-run` is not installed. Ordinary free typing worked, clearing produced a blank value, Escape left it blank, and Tab moved focus to the split control. One browser pass does not establish universal datalist support or assistive-technology accessibility.

To close the engine gap, the authorized command `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh install-browser firefox` downloaded Firefox 156.0 (`playwright firefox v1553`) to `/home/sra235/.cache/ms-playwright/firefox-1553`. No repository dependency or source file changed. The CLI reported version `0.1.22`; `install-browser --list` then showed the matching Firefox 1553 under Playwright `1.64.0-alpha-1790635538000`.

Exact browser commands for the Firefox keyboard path:

```bash
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox open http://127.0.0.1:57433 --browser firefox
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox eval "loadConcepts()"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox select e83 cycle12-firefox-keyboard
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox click e84
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox click e109
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox eval "Array.from(document.querySelectorAll('.concept-query-row')[1].querySelector('datalist').options,o=>o.value)"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox click e210
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox type O
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox press ArrowDown
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox press Enter
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle12-firefox eval "JSON.stringify({value:document.querySelectorAll('.saved-query-information-need')[1].value,options:Array.from(document.querySelectorAll('.concept-query-row')[1].querySelector('datalist').options,o=>o.value),active:document.activeElement.className})"
```

The options command returned `["Ops"]`; the final command returned `{"value":"Ops","options":["Ops"],"active":"text-input saved-query-information-need"}`. The synthetic Firefox database lived at `/tmp/es-rag-cycle12-firefox.meRqyc/concepts.sqlite3`; the browser session and loopback server were closed, and that temporary directory was removed. The Firefox browser remains installed in the Playwright cache as authorized.

The browser console included a favicon 404 and repeated `/api/concepts/tune/readiness` 400 responses while using a synthetic concept without a live Elasticsearch mapping; neither came from the suggestion list. Two Chromium verbose password-field form advisories also appeared. No injected image element or JavaScript execution from the hostile option was observed.

## Subagent record

| Role | Responsibility | Requested override | Runtime identity |
| --- | --- | --- | --- |
| QA | Add and run bounded synthetic/API and browser acceptance; record regression/package evidence and skips. | `gpt-6-luna` | Unverified; runtime identity is not exposed. |

## Final disposition

The bounded API, browser keyboard selection in Firefox, layout, save/reload, retrieval-invariance, offline regression, and package gates pass. Assistive-technology compatibility and live Elasticsearch acceptance remain `NOT RUN`; full offline suite skips are recorded above and are not passes. This does not establish universal native datalist accessibility or production Elasticsearch behavior.
