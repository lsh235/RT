# Cycle 23 — Empty candidate recovery acceptance

Checked: 2026-10-18
Baseline: `9020438` / `v0.17.3`; implementation version observed: `0.17.4`
QA assignment: requested model override `gpt-6-luna`; runtime model identity **UNVERIFIED** (no runtime telemetry available).

## Scope and evidence boundary

The browser fixture uses synthetic API responses and an in-memory concept. It checks the recovery CTA on two empty information-need result cards, verifies that a baseline-only empty column does not trigger it, and checks that a candidate hit removes it. Before each Enter/Space activation it captures a serialized `collectConcept()` snapshot plus query selection/text and manual ID; after activation it compares those values against the snapshot. It also checks no additional API call or judgment, verifies focus and scroll to `#locate-document-text`, checks the candidate-empty copy does not assert that a document is absent from the index, checks a 390px viewport for horizontal overflow, and records browser console errors after mock installation and reload.

No live Elasticsearch, corpus, provider, or user database was accessed. User testing was **NOT RUN**. These checks establish synthetic UI behavior only; they do not establish retrieval effectiveness or usability improvement.

## Acceptance results

| Gate | Result | Evidence |
| --- | --- | --- |
| Empty concept-applied results describe the current candidate list, without claiming document/index absence | PASS | Two empty information-need cards asserted the concise current-result-list message and rejected absence wording. |
| Recovery CTA is absent for baseline-only emptiness and appears for concept candidate emptiness | PASS | Three-card fixture included two empty candidate results and one baseline-empty/candidate-hit result; ordinary candidate-hit preview also had no CTA. |
| Enter and Space activate CTA, focus/scroll lookup input into view, and preserve query/concept/filter/settings | PASS | Both keys tested; active element and viewport checked; `collectConcept()`, query selection/text and manual ID compared; no additional API calls or judgment controls observed. |
| Multiple information-need cards reuse the recovery affordance | PASS | Two empty cards independently rendered the CTA. |
| 390px viewport has no horizontal overflow | PASS | `documentElement.scrollWidth` and `body.scrollWidth` did not exceed `clientWidth`. |
| No application console errors after routes were mocked and page reloaded | PASS | Fixture captured zero console errors. The Playwright console summary also showed zero errors and warnings; two informational Chrome password-field notices were present. |
| JavaScript syntax | PASS | `node --check tests/cycle23_empty_candidate_recovery_browser.js`; `node --check es_rag_tuner/web/app.js`. |
| Full offline Python suite | PASS | 101 tests, `OK (skipped=2)` using the explicitly unreachable Elasticsearch URL. |
| Isolated wheel/install/version/CLI smoke | PASS | Built and installed a wheel from a temporary source copy; distribution and module versions both `0.17.4`; packaged `web/app.js` present; `python3 -m es_rag_tuner --help` succeeded. |
| Live Elasticsearch/provider/corpus/database checks | NOT RUN | Explicitly outside the synthetic/offline QA boundary. |
| User testing | NOT RUN | No usability claim is made. |

## Exact commands and results

Syntax checks:

```sh
node --check tests/cycle23_empty_candidate_recovery_browser.js
node --check es_rag_tuner/web/app.js
```

Both returned exit code 0. Version inspection found `pyproject.toml = 0.17.4`, `es_rag_tuner.__version__ = "0.17.4"`, and UI text `v0.17.4`.

Browser fixture:

```sh
python3 -m http.server 18769 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle23final open http://127.0.0.1:18769/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle23final run-code --filename tests/cycle23_empty_candidate_recovery_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle23final console
```

Fixture outcome: PASS. The console summary had two informational Chrome password-field notices and zero errors/warnings. A first fixture iteration failed because a debounced readiness request arrived after the API-call baseline was recorded. The fixture was adjusted to wait for readiness status to settle and for 100 ms before starting the CTA assertions; the fresh run passed. A subsequent review found the concept equality check compared two post-activation values. The fixture now snapshots concept/query/manual-ID values before each keypress and compares after activation; the rerun below passed. The static-server page-open happened before route mocking and is excluded from the post-mock console assertion.

Final snapshot-check rerun:

```sh
python3 -m http.server 18769 --bind 127.0.0.1 --directory es_rag_tuner/web
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle23rerun open http://127.0.0.1:18769/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle23rerun run-code --filename tests/cycle23_empty_candidate_recovery_browser.js
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle23rerun console
```

Result: PASS; the fixture's assertions all passed, including pre/post concept snapshot equality for both Enter and Space activations; post-mock console summary reported 0 errors and 0 warnings (two informational password-field notices).

Full offline suite:

```sh
ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 python3 -m unittest discover -s tests -v
```

Result: `Ran 101 tests in 5.840s`, `OK (skipped=2)`, exit code 0. The two skips were (1) live Elasticsearch acceptance: connection refused at the configured unreachable URL; and (2) real tokenizer parity: its isolated fixture containing the pinned tokenizer/config assets was unavailable. No live provider was invoked.

Isolated package smoke used a temporary source copy and target installation, excluding Python caches and egg metadata:

```sh
smoke_root=$(mktemp -d /tmp/cycle23-package-smoke.XXXXXX)
mkdir -p "$smoke_root/src" "$smoke_root/target"
cp pyproject.toml README.md "$smoke_root/src/"
cp -R es_rag_tuner "$smoke_root/src/"
find "$smoke_root/src/es_rag_tuner" -type d \( -name __pycache__ -o -name '*.egg-info' \) -prune -exec rm -rf {} +
find "$smoke_root/src/es_rag_tuner" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir "$smoke_root/wheel" "$smoke_root/src"
python3 -m pip install --no-deps --target "$smoke_root/target" "$smoke_root"/wheel/*.whl
(cd /tmp && PYTHONPATH="$smoke_root/target" python3 - <<'PY'
import importlib.metadata as md
import es_rag_tuner
from pathlib import Path
assert es_rag_tuner.__version__ == md.version('es-rag-tuning-workbench') == '0.17.4'
assert (Path(es_rag_tuner.__file__).parent / 'web' / 'app.js').is_file()
print(es_rag_tuner.__version__, md.version('es-rag-tuning-workbench'))
PY
)
(cd /tmp && PYTHONPATH="$smoke_root/target" python3 -m es_rag_tuner --help)
```

Result: wheel build/install succeeded (`es_rag_tuning_workbench-0.17.4-py3-none-any.whl`); module and distribution metadata both reported `0.17.4`; packaged `web/app.js` was present (217,788 bytes); CLI help exited 0. An initial smoke assertion queried the wrong distribution name (`es-rag-tuner`) and failed to find metadata; correcting it to the built distribution name (`es-rag-tuning-workbench`) passed. No repository source was changed for this correction.

## Research context (checked 2026-10-18)

These are general interaction-design references, not evidence that this RAG workflow is effective:

- [Atlassian Design System — Empty state](https://atlassian.design/content/designing-messages/empty-state/) gives general guidance to explain an empty state and provide a concise next action. This informed the product inference that an empty candidate list should explain its scope and offer a direct recovery action.
- [WAI-ARIA Authoring Practices Guide — Button Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/button/) documents native button semantics and Enter/Space activation, and discusses moving focus to the start of a new context when an action changes context. This informed testing the CTA as a native button and checking focus at the lookup input after activation.

These sources motivate semantics and copy choices only. They do not demonstrate search quality, index completeness, candidate recovery success, or user benefit. User testing remains **NOT RUN**.

## QA-owned files

- `tests/cycle23_empty_candidate_recovery_browser.js`
- `docs/cycle23-empty-candidate-recovery-acceptance.md`
