# Match evidence acceptance

Date: 2026-10-18

Status: **PASS; approved acceptance execution completed 2026-10-18**

Scope: Cycle 10 adds field-specific match evidence to the saved-concept document locator. The synthetic suite verifies application logic; the separate disposable Elasticsearch 9.5.5 smoke validates only that single API path/version. Neither establishes broad Elasticsearch version compatibility, production readiness, retrieval quality, or that a candidate is relevant to the saved evaluation query.

## Contract under acceptance

`POST /api/concepts/locate-document` continues to use the saved concept's index and mapping-validated text fields. Elasticsearch highlight options may be requested only for configured, mapped, non-nested scalar fields, with one finite fragment, a modest finite fragment size, and `require_field_match: true`. No `no_match_size`, arbitrary caller field/DSL/index, or unvalidated highlight option is accepted.

The API reports `matched_fields` in configured field order and includes a field only when the hit contains a non-empty string fragment under that exact `hit.highlight` field. `excerpt` and `excerpt_field` come from the first such scalar field and are bounded in application code. `_source` text is not evidence and is never an excerpt fallback. A candidate without scalar highlights remains a candidate with empty `matched_fields` and null excerpt fields. Nested excerpts remain out of scope; nested-only matches must not be represented as root scalar evidence. The UI escapes candidate/highlight data and describes evidence narrowly, without claiming a full relevance judgment.

Cycle 9 constraints remain in force: fixed bounded search, saved index/field authority, no saved evaluation query or filters, root document identity, explicit human grading, stale-target clearing, and safe UI rendering.

## Acceptance matrix

| Gate | PASS | FAIL |
|---|---|---|
| Highlight request scope and options | Captured request contains only configured, mapping-validated scalar fields in the highlight section. Nested `comments.text` is excluded. Each option sets `number_of_fragments: 1`, a positive finite/modest `fragment_size`, and `require_field_match: true`; `no_match_size` is absent. Cycle 9 fixed size/offset/total-hit and caller-scope regressions pass. | Any nested, unmapped, unconfigured, or caller-provided field is highlighted; a fragment option is missing/unbounded; or Cycle 9 scoping/bounds regress. |
| Actual matching field and snippet | A fixture whose only applicable highlight is on non-first configured scalar `body` returns `body` and its exact non-empty fragment as evidence. When multiple configured fields have fragments, `matched_fields` follows configured field order and excerpt comes from the first. | Evidence is inferred from `_source`, field order is wrong, or fragment content/field does not come from the hit's actual highlight entry. |
| No-highlight candidate | A valid hit with no scalar highlight remains a candidate, with `matched_fields: []`, `excerpt: null`, and `excerpt_field: null`; source text is not returned as evidence. | Candidate is dropped solely for lacking evidence, source text is substituted, or a field is claimed without a non-empty string fragment. |
| Nested-only behavior | A nested-only fixture has no scalar excerpt and cannot claim nested highlight data as a root scalar excerpt. UI/copy retains the conservative nested-excerpt boundary. | Nested text is presented as a root excerpt or is listed as scalar `matched_fields`. |
| Safe UI and judgment boundary | Hostile markup-shaped title/snippet/field values remain inert. Only escaped literal `<em>` / `</em>` highlighter wrappers become static `<mark>` tags; arbitrary markup remains text. Lookup/selection neither changes saved query nor creates a judgment. Scope changes clear stale locator state. | Markup executes, highlighter handling trusts arbitrary HTML, selection records a judgment or changes the query, or stale candidate identity survives scope changes. |
| Candidate bounds and result integrity | Excerpts remain bounded in application code; Cycle 9 completion, identity, and fixed result-count checks continue to pass. | Unbounded text or partial/invalid Elasticsearch results appear as successful evidence/candidate output. |

## Execution thresholds

Each gate is **PASS** only with recorded command and observed result. A failed assertion, build/package failure, or installed-app smoke failure is **FAIL** and stops that iteration for correction. A gate not executed or unavailable is **NOT RUN**; it is never implied to pass. Live Elasticsearch is **NOT RUN** if Docker or the official Elasticsearch 9.5.5 image is not already present locally. No image download is permitted for this acceptance; unavailable live validation means no compatibility claim and must be returned to the coordinator for the release decision.

All acceptance APIs use synthetic fixture values, temporary SQLite/home directories, and dynamically allocated loopback ports. Do not inspect or alter the default database, user corpus, or credentials.

## Executable artifact and executed commands

`tests/test_match_evidence_acceptance.py` uses a synthetic Elasticsearch HTTP service and a disposable SQLite database. It records the request body and tests highlight scope/options, actual non-first-field evidence, ordered multi-field evidence, no-highlight behavior, nested exclusion, output bounds, and UI escaping/judgment separation.

The following focused acceptance and offline suite commands were executed after coordinator approval; interpreter/version, counts, skips, and exact outcomes are recorded below:

```bash
python3 -m unittest discover -s tests -p 'test_match_evidence_acceptance.py' -v
python3 -m unittest discover -s tests -p 'test_document_lookup_acceptance.py' -v
env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=offline://disabled python3 -m unittest discover -s tests -v
```

Wheel build/install, installed CLI help, health/assets, synthetic browser evidence, and an isolated live API smoke against the already-present official Elasticsearch 9.5.5 image were also completed. The browser fixture returned an excerpt such as `<em>actual evidence</em><img id="evidence-xss" src=x onerror="window.__evidenceXss=true">`; assertions verified the mark text, absence of an image DOM node, literal hostile text, and a false XSS sentinel. Candidate selection preserved the saved query and produced zero judgment calls. The live smoke covered one disposable synthetic Elasticsearch 9.5.5 instance only; it does not establish broad version compatibility, production readiness, or retrieval quality.

| Gate | Status | Exact command and observed evidence |
|---|---|---|
| New match-evidence acceptance | **PASS** | Exact command and results below; 6 tests passed. |
| Cycle 9 document-lookup acceptance | **PASS** | Exact command and results below; 14 tests passed. |
| Full offline regression suite | **PASS** | Exact command and results below; 65 passed, 2 expected skips. |
| Wheel/package build and isolated install | **PASS** | 0.11.0 wheel built without index access; isolated no-dependency install and CLI help succeeded. |
| Installed CLI, health, and static assets | **PASS** | Installed CLI returned health version 0.11.0; page, JS, and CSS were HTTP 200 with expected markers. |
| Synthetic browser/XSS and locator workflow | **PASS** | Headless Chromium at 390×844: static mark rendered, hostile img remained literal/inert, selection preserved query and caused no judgment, and scope reset cleared the target. |
| Live Elasticsearch 9.5.5 smoke | **PASS (one synthetic disposable instance)** | Docker 29.7.2 used the already-present official image (ID `sha256:952a43cd5ab721f7032b2dfd4dcc86a76ba9a791b4c34a223292cf26a832e040`) with `--pull=never`. A disposable single-node 9.5.5 container served a synthetic index/document; Workbench locate API returned the actual body highlight. This is evidence for this exact image/version and synthetic path only, not broad compatibility or production readiness. No image download or user data was used. |
| Runtime model identity | **UNVERIFIED** | Requested override: `gpt-6-luna`. Runtime identity is not observable from this agent's session metadata or available tools. |

## Execution record

Environment: `python3 --version` and `/usr/bin/python3 --version` both returned `Python 3.12.3`. All tests used synthetic data and the acceptance tests' temporary SQLite databases/loopback listeners. Packaging and installed-app smoke used `/tmp/cycle10-match-acceptance.tGu8cN`; installed health process had `HOME=/tmp/cycle10-match-acceptance.tGu8cN/health-home` and `ES_RAG_CONCEPT_DB=/tmp/cycle10-match-acceptance.tGu8cN/health.sqlite3`. Browser process used `HOME=/tmp/cycle10-match-acceptance.tGu8cN/browser-home` and `ES_RAG_CONCEPT_DB=/tmp/cycle10-match-acceptance.tGu8cN/browser.sqlite3`. No default DB, user corpus, credentials, or provider services were accessed.

### Synthetic tests

```text
python3 -m unittest discover -s tests -p 'test_match_evidence_acceptance.py' -v
Ran 6 tests in 1.049s
OK

python3 -m unittest discover -s tests -p 'test_document_lookup_acceptance.py' -v
Ran 14 tests in 1.075s
OK

env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=offline://disabled python3 -m unittest discover -s tests -v
Ran 65 tests in 4.354s
OK (skipped=2)
```

The full-suite skips were `LiveConceptAcceptance` because the configured URL intentionally used the `offline` scheme, and pinned tokenizer parity because its opt-in isolated tokenizer fixture was not enabled. Both skips were expected; the suite made no live ES call.

### Wheel, install, CLI, health, and assets

```bash
PIP_NO_INDEX=1 /usr/bin/python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/cycle10-match-acceptance.tGu8cN/wheelhouse .
python3 -m venv /tmp/cycle10-match-acceptance.tGu8cN/installed-venv
PIP_NO_INDEX=1 /tmp/cycle10-match-acceptance.tGu8cN/installed-venv/bin/python -m pip install --no-deps /tmp/cycle10-match-acceptance.tGu8cN/wheelhouse/es_rag_tuning_workbench-0.11.0-py3-none-any.whl
/tmp/cycle10-match-acceptance.tGu8cN/installed-venv/bin/es-rag-workbench --help
```

Build output: `es_rag_tuning_workbench-0.11.0-py3-none-any.whl`, 174,245 bytes, SHA-256 `54db8e25e081fdbf2e6b650b28727eec72489612b1387ce6fb38ca432879d0a4`. `--help` exited 0 and showed the local workbench usage/options. The installed CLI was launched with `--host 127.0.0.1 --port <port selected by binding 127.0.0.1:0>` under the temporary health `HOME`/SQLite environment above. Observed: `GET /api/health` → `200 {"ok": true, "version": "0.11.0"}`; `GET /` → 200 with `id="server-version">v0.11.0</span>`; `GET /app.js` → 200 with `renderLocatorHighlight`; `GET /style.css` → 200 with `locator-candidate`.

### Synthetic browser/XSS and locator workflow

Prerequisite check: `command -v npx` → `/usr/bin/npx`; `npx --version` → `10.9.8`. Browser driver: `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh` (CLI 0.1.22). The installed app ran at `http://127.0.0.1:39247` with the temporary browser environment above. Commands: `playwright_cli.sh open http://127.0.0.1:39247`, `playwright_cli.sh resize 390 844`, `playwright_cli.sh snapshot`; a Playwright `eval` installed a fixture-only `fetch`, populated a synthetic saved concept/query, and returned one candidate with excerpt `<em>actual evidence</em><img id="evidence-xss" src=x onerror="window.__evidenceXss=true">`; then `playwright_cli.sh click e142`, `playwright_cli.sh snapshot '#locate-document-results'`, and a browser evaluation inspected DOM/text/sentinel state. Observed: `markText="actual evidence"`, `imageNode=false`, `literalHostile=true`, `xssFired=false`; saved query was `saved-query-id`; before selection no judgments were called. Clicking candidate `e192` set document ID `doc-1` and index `saved-index`, preserved query `saved-query-id`, and left judgment calls at zero. Dispatching `input` after changing the index cleared the locator ID, stored index, and results. Document/body widths were both 390 pixels at a 390-pixel viewport. Browser console showed one pre-existing local page error at initial open; it did not affect the measured browser actions. No real ES or provider endpoint was contacted by the browser fixture.

### Disposable live Elasticsearch 9.5.5 API smoke

Image availability was inspected before execution; the exact official image was already local. Container invocation (port was dynamically selected as 54081 and bound only to loopback):

```bash
docker run --pull=never --rm --name cycle10-match-es-de8cacb6 \
  -p 127.0.0.1:54081:9200 \
  -e discovery.type=single-node -e xpack.security.enabled=false \
  -e 'ES_JAVA_OPTS=-Xms512m -Xmx512m' \
  docker.elastic.co/elasticsearch/elasticsearch:9.5.5
```

A Python `urllib` smoke script waited for `GET /`, asserted version `9.5.5`, created index `cycle10-synthetic` with scalar `title`, `body`, `summary`, nested `comments.text`, and keyword `tenant`, then indexed only synthetic `doc-1` with `rarephrase` in `body` and nested `comments.text`. It started the Workbench HTTP handler on a second dynamically allocated loopback port with `ES_RAG_CONCEPT_DB` in a `TemporaryDirectory`, saved a synthetic concept, and called `POST /api/concepts/locate-document` with locator text `rarephrase`; caller-supplied highlight options were also included as an ignored input. Results: ES root HTTP 200/version 9.5.5; mapping HTTP 200/acknowledged; synthetic index request HTTP 201/created; concept save HTTP 200; locate HTTP 200/one candidate. Candidate evidence was `matched_fields=["body"]`, `excerpt_field="body"`, excerpt `The unique cycle ten <em>rarephrase</em> appears in this temporary acceptance document.`, `excerpt_is_nested=false`. The saved query decoy was absent and nested highlight did not become scalar evidence. Container was stopped with `docker stop --time 10 cycle10-match-es-de8cacb6`; exit 143 from the supervising wrapper is the expected consequence of this explicit shutdown, and `--rm` removed the container. The live smoke validates this synthetic API path against this exact ES image/version only; it does not establish production data compatibility or retrieval quality.
