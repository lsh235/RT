# Document lookup acceptance

Date: 2026-10-18

Status: **Executed after coordinator approval; synthetic gates passed**

Baseline: `4a79a36` / annotated `v0.9.0`

This acceptance artifact covers a text locator for users who remember title/body words but do not know a document ID. The evidence is limited to synthetic fixtures. No claim about a live corpus, production Elasticsearch behavior, retrieval quality, or document absence is made here.

## Agreed API contract

`POST /api/concepts/locate-document` accepts `{ "connection": {...}, "concept_id": "...", "text": "..." }`. The saved concept is authoritative for the corpus index, validated `corpus.text_fields`, optional `title_field`, current mapping metadata, and saved evaluation queries/filters. The caller cannot choose an index, fields, DSL, pagination, or result size. The locator phrase is separate from the saved evaluation query and saved concept filters are omitted.

A completed successful response has `{ "index", "fields", "candidates" }`. Each candidate has `document_index`, root `document_id`, nullable `score`, bounded `title` and `excerpt`, `excerpt_field`, and `excerpt_is_nested`. At most ten candidates are returned. Nested matches identify the root hit; without a matching nested inner hit, nested content is not claimed as an excerpt. The UI uses `#locate-document-text`, `#locate-document-button`, `#locate-document-results`, and candidate buttons with `data-document-index` / `data-document-id`. Choosing a candidate fills the known-ID input; human grading remains a separate action.

## Acceptance matrix

| Gate | PASS when | FAIL when |
|---|---|---|
| Saved scope and caller input | Captured request targets only the saved concept index and uses searchable fields from saved `corpus.text_fields` plus the configured `title_field` when it is not already in that list. Caller-supplied `index`, `fields`, DSL, query, and `size` do not widen or replace that scope. The returned effective field list matches the actual locator scope. | A configured title is omitted from lookup, or any caller field, index, query DSL, or pagination setting reaches Elasticsearch as authority. |
| Fixed bounds | Every request uses `size: 10`, `from: 0`, and `track_total_hits: false`; source includes are deduplicated mapped `source_field` paths from selected fields only. API returns at most ten candidates and display strings are clipped. | Size, offset, exact hit count, wildcard source fields, or unselected source values are exposed. These bounds describe returned results, not Elasticsearch's internal work. |
| Mapping and nested identity | Query fields are grouped using current mapping `nested_path`; nested groups use their mapping-derived path. A nested match yields the root `_index`/`_id`, never a nested-object identity. A nested excerpt is omitted unless it comes from the matching nested object. | Nested fields are queried as root fields, a path is guessed from UI input, a nested ID is substituted for root identity, or unrelated nested text is presented as the match. |
| Locator/evaluation separation | Search has the submitted locator text and no saved evaluation query or saved concept filter. The saved query list remains unchanged after lookup. | The locator rewrites a saved query, applies evaluation filters, or implies a candidate is relevant to the saved query. |
| Completed zero-hit state | Only HTTP success with explicit `timed_out: false`, valid shard metadata reporting zero failures, and a list-valued empty `hits.hits` is rendered as no candidates. Candidate hits must include valid root index/document identity. Copy says no match was returned for this search and does not claim the document is absent. | HTTP failure, transport timeout, missing/non-false `timed_out`, missing/invalid shard failure metadata, missing/non-list hits, malformed hit identity, failed shards, or partial results are presented as a clean zero-hit result or as proof of absence. |
| Judgment boundary and target freshness | Lookup and candidate selection create no judgment. Selection only supplies the candidate's root index/ID to the existing explicit load/diagnose flow; the saved query selection stays intact. Changing/loading a concept, filling an example concept, changing selected index, Elasticsearch URL, or connection settings clears old candidates and any locator-selected ID/index. A manually typed known ID may remain, but a known-ID fetch/diagnosis after a scope change uses the current selected scope and cannot silently reuse the previous candidate's index. A judgment exists only after a human uses the explicit rating control. | Finding or selecting a candidate records a label or changes which saved query is being evaluated, or a prior candidate/selected index survives a scope change and is reused by the known-ID route. |
| Safe rendering and narrow layout | Candidate title, IDs, field names, and excerpt are HTML-escaped before rendering; browser acceptance with HTML-like synthetic values creates no executable element. At a narrow viewport, locator input and candidate action stack into one column without horizontal overflow. | Candidate content executes as markup/script or locator controls overflow / become unusable on mobile. |

## Executable test artifact

`tests/test_document_lookup_acceptance.py` is designed for offline synthetic acceptance. It starts the app and a fake Elasticsearch HTTP service on dynamically allocated loopback ports, writes concept data only to a temporary SQLite path, and does not use the default Elasticsearch endpoint, provider services, user documents, or ports 8765/8766.

The suite includes these cases:

1. Saved index/field scope, fixed `size`/`from`/`track_total_hits`, and rejection of caller index/fields/DSL/size overrides; saved filters and evaluation text are absent from the locator request.
2. A legacy-shaped saved concept whose configured `title_field` is absent from its `text_fields` still searches that mapped title field exactly once and reports it in the effective fields. The fixture is first saved through the current validator, then its temporary SQLite row is edited to represent the historical profile shape; this does not relax normal save validation. The candidate locator request sends only connection, concept ID, and locator text.
3. Mapping-derived nested grouping and root-document identity where the fixture's nested object ID differs from the hit's root ID.
4. Selected-source-only display and bounded title/excerpt values.
5. A completed clean zero-hit response.
6. HTTP error, transport timeout, Elasticsearch `timed_out`, failed-shard responses, and synthetic malformed/partial 2xx responses (missing/non-false `timed_out`, missing/invalid `_shards.failed`, missing/non-list `hits.hits`, or hits missing `_index`/`_id`) are API errors with no candidates array.
7. Locator length validation before any search request.
8. Saved query immutability and no judgment row after lookup.
9. Nested-only candidate display does not claim an excerpt from the root source.
10. Static checks that all candidate values pass through `escapeHtml`, selection does not call the judge endpoint or alter the saved-query selector, concept population/example-fill and other scope changes clear candidates and selected exact target, the known-ID route reads the current selected index, and CSS provides one-column rules below 600px.

The static UI assertions are source checks. A separate real-browser run with synthetic API responses and HTML-like strings verified XSS-safe rendering, candidate selection, saved-query and judgment boundaries, scope invalidation, current-index fallback for a known ID, and mobile overflow behavior; details are recorded below.

## Run and evidence rules

- Focused command executed: `python3 -m unittest discover -s tests -p 'test_document_lookup_acceptance.py' -v`.
- Confirm the suite uses its temporary DB and both dynamically allocated loopback ports. Do not set or contact a live Elasticsearch URL.
- Report API/mock tests separately from browser evidence. A mock does not prove Elasticsearch DSL compatibility, live-corpus results, absence, or quality.
- Report every gate as `PASS`, `FAIL`, or `NOT RUN`; do not treat an unexecuted artifact as acceptance evidence.
- Requested implementation/QA model override: `gpt-6-luna`. This worker's actual runtime model identifier is not independently observable in the available session metadata/tools, so identity is **unverified**.

## Execution evidence

All executable work was authorized by the coordinator. Synthetic tests used temporary SQLite and fake Elasticsearch HTTP services on dynamically allocated loopback ports. The browser used the installed wheel and intercepted API calls with synthetic responses. The default Elasticsearch endpoint, user database/documents, providers, and ports 8765/8766 were not used.

The table below records the original 0.9.0 package/browser run. The later version-only bump was checked separately in the final 0.10.0 rerun below.

| Gate | Status | Exact command / evidence |
|---|---|---|
| Focused synthetic acceptance | **PASS** | `python3 -m unittest discover -s tests -p 'test_document_lookup_acceptance.py' -v` — Python 3.12.3; 14 tests passed. Covered saved scope/overrides, title-only legacy profile, nested/root identity, bounds/source display, clean zero hits, HTTP/transport/partial errors including malformed hit identity, no judgment/query mutation, XSS source checks, and scope reset checks. |
| Offline regression suite | **PASS** | `env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=offline://disabled python3 -m unittest discover -s tests -v` — Python 3.12.3; 59 tests passed, 2 skipped. `LiveConceptAcceptance` skipped because the configured URL used the `offline` scheme; pinned tokenizer parity skipped because its opt-in fixture variable was unset. No live Elasticsearch/provider call occurred. |
| Wheel build | **PASS after environment correction** | `PIP_NO_INDEX=1 /usr/bin/python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/cycle9-acceptance.wC7nsQ/wheelhouse .` — system Python 3.12.3, setuptools 68.1.2. Wheel: `es_rag_tuning_workbench-0.9.0-py3-none-any.whl`, 173,822 bytes, SHA-256 `ffe4b3d0617562a623f6718af2fc4feec7b3da9234d4f12aeac58731c27bdb78`. Initial attempt with `.venv/bin/python` failed because that environment lacks `setuptools.build_meta`; no wheel was produced by that attempt. Retrying with system Python passed without downloading packages. |
| Isolated wheel install and CLI | **PASS** | `python3 -m venv /tmp/cycle9-acceptance.wC7nsQ/installed-venv`; `PIP_NO_INDEX=1 /tmp/cycle9-acceptance.wC7nsQ/installed-venv/bin/python -m pip install --no-deps /tmp/cycle9-acceptance.wC7nsQ/wheelhouse/es_rag_tuning_workbench-0.9.0-py3-none-any.whl`; `/tmp/cycle9-acceptance.wC7nsQ/installed-venv/bin/es-rag-workbench --help` succeeded. |
| Installed health/static assets | **PASS** | Started the installed CLI on an ephemeral loopback port with `HOME=/tmp/cycle9-acceptance.wC7nsQ/home` and `ES_RAG_CONCEPT_DB=/tmp/cycle9-acceptance.wC7nsQ/concepts.sqlite3`. `GET /api/health` returned HTTP 200 and `{"ok": true, "version": "0.9.0"}`; `/`, `/app.js`, and `/style.css` each returned HTTP 200 and contained locator markers. The smoke script chose its port by binding `127.0.0.1:0`. |
| Real browser XSS and mobile workflow | **PASS** | Playwright CLI 0.1.22 wrapper `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`; `npx` 10.9.8; installed app at `http://127.0.0.1:46875`, with `HOME=/tmp/cycle9-acceptance.wC7nsQ/browser-home` and `ES_RAG_CONCEPT_DB=/tmp/cycle9-acceptance.wC7nsQ/browser.sqlite3`; HeadlessChrome 154.0.0.0, viewport 390×844. Commands included `open http://127.0.0.1:46875`, `resize 390 844`, fresh `snapshot`s, `fill` on the locator text, and `click` on the locator/candidate/example buttons; browser `eval` installed synthetic fetch responses and dispatched index/URL input changes. Candidate title `<img id=locator-xss ...>` and excerpt `<svg id=excerpt-xss ...>` remained literal text; neither element existed and `window.__xssFired` stayed false. Clicking the candidate set its root ID/index, preserved `saved-query-id`, and recorded zero `/api/concepts/judge` calls. Changing index cleared candidate/results/locator identity; entering a known ID and fetching sent `index: current-index-after-change`. Changing Elasticsearch URL cleared a subsequently selected candidate; clicking “예시 보기” then cleared the selected target and candidates. At 390px, `documentElement.scrollWidth` and `body.scrollWidth` were both 390px; locator and candidate grids rendered as single columns (306px candidate/button width). Browser console also showed a local `/favicon.ico` 404 and verbose password-field diagnostics; these did not involve external services or affect the measured flow. |
| Diff check | **PASS** | `git diff --check -- tests/test_document_lookup_acceptance.py docs/document-lookup-acceptance.md` — clean after the final artifact update. |
| Live Elasticsearch / real corpus | **NOT RUN** | The test and browser fixtures were synthetic; no live-corpus compatibility or retrieval-quality claim follows. |
| Requested/runtime model identity | **UNVERIFIED** | Requested override is `gpt-6-luna`; this worker's runtime model identifier is not exposed in session metadata/tools. |

### Final 0.10.0 rerun

After the package version bump, the focused acceptance file, full offline suite, wheel/install, CLI help, health/assets, and a 390px browser smoke were rerun against the installed 0.10.0 wheel. The synthetic browser workflow above is the pre-bump full UI run; this final browser check verifies the installed version badge and narrow viewport layout. It did not repeat candidate-selection and scope-reset interactions because the coordinator reported the package version string as the only source change since the full UI PASS.

| Gate | Status | Exact command / evidence |
|---|---|---|
| Focused synthetic acceptance | **PASS** | `python3 -m unittest discover -s tests -p 'test_document_lookup_acceptance.py' -v` — Python 3.12.3; 14 passed. |
| Offline regression suite | **PASS** | `env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=offline://disabled python3 -m unittest discover -s tests -v` — Python 3.12.3; 59 passed, 2 expected skips: live Elasticsearch skipped for the offline scheme, and tokenizer parity skipped because its pinned fixture was not enabled. |
| 0.10.0 wheel build/install and CLI | **PASS** | `PIP_NO_INDEX=1 /usr/bin/python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/cycle9-final.S9u6iy/wheelhouse .`; installed with `python3 -m venv /tmp/cycle9-final.S9u6iy/installed-venv` and `PIP_NO_INDEX=1 /tmp/cycle9-final.S9u6iy/installed-venv/bin/python -m pip install --no-deps /tmp/cycle9-final.S9u6iy/wheelhouse/es_rag_tuning_workbench-0.10.0-py3-none-any.whl`; `/tmp/cycle9-final.S9u6iy/installed-venv/bin/es-rag-workbench --help` passed. Wheel size 173,837 bytes, SHA-256 `d7e5116c7337a9110636ba7a4509076dea821919dfc3d623be521f6a72c51ccd`. |
| Installed health and static assets | **PASS** | Installed CLI launched with `--host 127.0.0.1 --port <ephemeral-loopback-port>`, `HOME=/tmp/cycle9-final.S9u6iy/health-home`, and `ES_RAG_CONCEPT_DB=/tmp/cycle9-final.S9u6iy/health.sqlite3`. `GET /api/health` returned `200 {"ok":true,"version":"0.10.0"}`; `GET /` contained `id="server-version">v0.10.0</span>`; `/app.js` and `/style.css` returned 200 with locator markers. The port came from binding `127.0.0.1:0`. |
| Installed 0.10.0 browser smoke | **PASS** | Playwright CLI wrapper `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh` (0.1.22), `npx` 10.9.8; opened `http://127.0.0.1:48041`, resized to 390×844, and evaluated `({badge:document.querySelector('#server-version')?.textContent, viewport:innerWidth, documentWidth:document.documentElement.scrollWidth, bodyWidth:document.body.scrollWidth})`. Result: `badge="v0.10.0"`, viewport/document/body width all 390. Only the local app was opened; no Elasticsearch/provider API was called. The page also emitted the known local missing-favicon 404. |
| Live Elasticsearch / provider calls | **NOT RUN** | All API acceptance fixtures were synthetic/offline. |
| Final diff check | **PASS** | `git diff --check` plus whitespace check of the two untracked owned artifacts; no whitespace errors. |

### Installed health/assets and browser reproduction

The installed-wheel smoke used the following launch pattern. The socket bind selects an unused loopback port; the child receives only the temporary home and database paths. The four requests are made directly to that selected local port.

```bash
python3 - <<'PY'
import json, os, socket, subprocess, time, urllib.request
from pathlib import Path

root = Path('/tmp/cycle9-acceptance.wC7nsQ')
binary = root / 'installed-venv/bin/es-rag-workbench'
with socket.socket() as probe:
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
env = os.environ | {
    'HOME': str(root / 'home'),
    'ES_RAG_CONCEPT_DB': str(root / 'concepts.sqlite3'),
}
Path(env['HOME']).mkdir(parents=True, exist_ok=True)
child = subprocess.Popen(
    [str(binary), '--host', '127.0.0.1', '--port', str(port)], env=env,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f'http://127.0.0.1:{port}'
try:
    for _ in range(100):
        try:
            with urllib.request.urlopen(base + '/api/health', timeout=1) as r:
                print('GET /api/health', r.status, r.read().decode())
            break
        except Exception:
            if child.poll() is not None:
                raise RuntimeError('installed CLI exited before health probe')
            time.sleep(0.1)
    for path, marker in [('/', b'locate-document-text'),
                         ('/app.js', b'/api/concepts/locate-document'),
                         ('/style.css', b'locator-candidate')]:
        with urllib.request.urlopen(base + path, timeout=2) as r:
            payload = r.read()
            assert r.status == 200 and marker in payload
            print(f'GET {path}', r.status, 'marker present')
finally:
    child.terminate()
    child.wait(timeout=5)
PY
```

Browser reproduction used the installed app at `http://127.0.0.1:46875`, with the recorded temporary `HOME` and `ES_RAG_CONCEPT_DB` paths above. Start it with the same CLI arguments shown above at port `46875`, then run these Playwright CLI steps (refresh `snapshot` before using each element reference):

```bash
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh open http://127.0.0.1:46875
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh resize 390 844
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval '<install synthetic fetch and initialize fixture state below>'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e142  # locate-document-button
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e191  # first candidate action
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval '<DOM assertions below>'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "document.querySelector('#index-name').value='current-index-after-change'; document.querySelector('#index-name').dispatchEvent(new Event('input',{bubbles:true})); ({id:document.querySelector('#manual-document-id').value, index:state.manualDocumentIndex, candidates:document.querySelectorAll('#locate-document-results [data-document-id]').length})"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill e149 'known-id-without-lookup'  # refresh snapshot for the manual ID input ref
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e150  # known-ID fetch
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "window.__fixtureCalls.filter(x=>x.path.includes('/api/concepts/document')).slice(-1)"
# Run another lookup and select it, then change the connection URL:
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill e141 'remembered locator phrase again'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e142
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot '#locate-document-results'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e221  # candidate action after refreshed snapshot
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "document.querySelector('#es-url').value='http://new-synthetic-es.invalid:9200'; document.querySelector('#es-url').dispatchEvent(new Event('input',{bubbles:true})); ({id:document.querySelector('#manual-document-id').value, index:state.manualDocumentIndex, results:document.querySelector('#locate-document-results').innerText})"
# Run/select once more, then exercise the example-concept reset:
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill e141 'lookup for concept reset'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e142
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot '#locate-document-results'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e229  # candidate action after refreshed snapshot
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot '#fill-concept-example'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e94  # “예시 보기”
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "({conceptId:state.conceptId, id:document.querySelector('#manual-document-id').value, index:state.manualDocumentIndex, candidates:document.querySelectorAll('#locate-document-results [data-document-id]').length})"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "({viewport:innerWidth, documentWidth:document.documentElement.scrollWidth, bodyWidth:document.body.scrollWidth, locatorColumns:getComputedStyle(document.querySelector('#locate-document-results')).gridTemplateColumns, candidateColumns:getComputedStyle(document.querySelector('#locate-document-results [data-document-id]')?.parentElement).gridTemplateColumns})"
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh console
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh close
```

The browser's `window.fetch` replacement recorded calls and returned only literal synthetic responses. The hostile strings are intentional test values; they never go to a real service.

```javascript
window.__fixtureCalls = [];
window.__xssFired = false;
window.fetch = async (input, init = {}) => {
  const path = String(input);
  let body = {};
  try { body = JSON.parse(init.body || '{}'); } catch {}
  window.__fixtureCalls.push({path, body});
  const reply = value => new Response(JSON.stringify(value), {
    status: 200, headers: {'Content-Type': 'application/json'}
  });
  if (path.includes('/api/concepts/locate-document')) return reply({
    index: 'saved-index', fields: ['title', 'body'], candidates: [{
      document_index: 'candidate-old-index', document_id: 'candidate-doc-1',
      score: 1, title: '<img id="locator-xss" src=x onerror="window.__xssFired=true">',
      excerpt: '<svg id="excerpt-xss" onload="window.__xssFired=true">body</svg>',
      excerpt_field: 'body', excerpt_is_nested: false
    }]
  });
  if (path.includes('/api/concepts/document')) return reply({
    document_index: body.index, document_id: body.document_id,
    source: {title: 'Fetched synthetic title', body: 'Synthetic body'}
  });
  if (path.includes('/api/concepts/diagnose')) return reply({
    document_index: body.document_index, document_id: body.document_id,
    classification: 'not_retrieved', probes: [], selected_field_presence: [], next_steps: []
  });
  return reply({});
};
state.connected = true;
state.schema = [
  {name:'title', type:'text', searchable:true, nested:false},
  {name:'body', type:'text', searchable:true, nested:false}
];
state.schemaIndex = 'saved-index';
document.querySelector('#es-url').value = 'http://synthetic-es.invalid:9200';
document.querySelector('#index-name').value = 'current-index';
populateConcept({
  id:'synthetic-concept-a', name:'Synthetic concept', description:'', aliases:[],
  related:[], excluded_terms:[],
  corpus:{index:'saved-index', title_field:'title', text_fields:['title','body'], filter_fields:[]},
  filters:[], settings:{size:10,candidate_size:10,field_boosts:{}},
  queries:[{id:'saved-query-id',query:'saved evaluation query',split:'train'}]
});
document.querySelector('#manual-query-id').value = 'saved-query-id';
document.querySelector('#locate-document-text').value = 'remembered locator phrase';
updateManualDocumentActions();
```

After selecting the first candidate, this Playwright `eval` assertion was used:

```javascript
({
  literalTitle: document.querySelector('#locate-document-results').innerText.includes('<img id="locator-xss"'),
  literalExcerpt: document.querySelector('#locate-document-results').innerText.includes('<svg id="excerpt-xss"'),
  imageNode: !!document.querySelector('#locator-xss'),
  svgNode: !!document.querySelector('#excerpt-xss'),
  xssFired: window.__xssFired,
  selectedId: document.querySelector('#manual-document-id').value,
  selectedIndex: state.manualDocumentIndex,
  savedQuery: document.querySelector('#manual-query-id').value,
  judgeCalls: window.__fixtureCalls.filter(x => x.path.includes('/api/concepts/judge')).length,
  pageWidth: document.documentElement.scrollWidth,
  viewport: innerWidth
})
```

Observed after selection: both hostile values appeared literally; `imageNode`, `svgNode`, and `xssFired` were false; selected identity was `candidate-doc-1` / `candidate-old-index`; saved query remained `saved-query-id`; `judgeCalls` was zero; page width and viewport were both 390px. Subsequent CLI `eval` steps dispatched `input` on `#index-name` and `#es-url` after changing their values, asserting candidate count/results empty, `#manual-document-id` empty when locator-selected, and `state.manualDocumentIndex === null`. A manually entered `known-id-without-lookup` then fetched with `index: 'current-index-after-change'`. A fresh selection followed by clicking the “예시 보기” button asserted `conceptId === null`, empty ID, null manual index, and no candidates. Final mobile inspection observed 390px document/body widths and single-column locator/candidate grids. These runs used fixture fetch only; no Elasticsearch or provider endpoint was contacted.

The first focused run failed all 14 cases during setup because the fixture used `settings.size=99`, outside the saved-concept validator's 1–50 range. The fixture was corrected to `size=10`; the hostile caller `size=500` override remains tested. The corrected focused run and the full offline suite passed as recorded above.
