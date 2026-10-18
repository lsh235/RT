# Cycle 13 vector candidate discovery acceptance

## Scope and evidence boundary

This report verifies a separate, read-only vector candidate discovery route and its workbench UI using synthetic fixtures. No configured database, real document corpus, credentials, or live Elasticsearch cluster is used. Live Elasticsearch verification is outside this report unless a dedicated safe fixture is explicitly available.

Acceptance contract: `POST /api/concepts/vector-candidates` takes a connection plus a saved concept and query identity. The route derives the index, query text, mapping-validated filters, safe fields, and candidate count from the saved concept. Caller-supplied index, query/DSL, mode, model, vector field, filters, source fields, and size do not override that saved state. It uses the fixed `rag_embedding` vector field and the existing E5 query embedding. Results retain `_index`, `_id`, vector rank/score, safe source/snippet, and only an exact current judgment for concept/query/index/document identity.

Discovery must not save a grade, change BM25 preview/baseline/candidate or tuning settings, change query fingerprints, create a run, or write an Elasticsearch document. Incomplete, malformed, failed, or timed-out vector searches must fail closed with no visible candidate list; they must not be reported as a clean empty list. The UI must keep vector candidates separate from BM25 preview, identify vector provenance/rank, state that candidate discovery can miss relevant documents, and require explicit human grading.

## Results

| Gate | Result | Evidence |
|---|---|---|
| Synthetic endpoint scope, saved query/index, mapping-validated filters, bounded K, vector-only target | PASS | 8 focused tests; hostile caller index/query/DSL/mode/model/vector-field/filter/source/size values did not override saved concept. Search used saved query, `rag_embedding`, typed filters, `size=K=3`, allowlisted source fields, and URL query `allow_partial_search_results=false`. Synthetic vector target was outside the displayed BM25 result. |
| Exact judgment identity and null-versus-zero handling | PASS | Exact train/query/index/document judgment returned rating `0`; validation-query and different-index rows did not affect the candidate. Unjudged candidate remained `null`. UI started at “미평가”; explicitly saved grade `3` reappeared after reload. |
| Read-only database and Elasticsearch behavior | PASS | SQLite table snapshots and database/sidecar SHA-256s were unchanged by candidate discovery. Synthetic Elasticsearch observed only mapping/count/search reads; no write route was called. The new API request accepted only connection, concept ID, and query ID in the UI. |
| Fail-closed dimensions, no-vectors, embedding, timeout, malformed, shard-failure cases | PASS | 8 focused tests included wrong mapping/vector dimensions, no vectors, no local model, embedding exception, timeout, failed shards, `failed: false`, missing `hits.total`, malformed hits, and over-bound responses. Errors returned no `candidates`; complete exact empty response returned `candidates: []`. |
| UI loading/error/empty, explicit grading, save/reload, XSS | PASS | Playwright CLI against loopback synthetic ES showed loading status with no cards and disabled action; shard error showed a clear message and 0 cards; clean empty showed “일치하는 문서가 없습니다.” and 0 cards. Candidate displayed vector rank separately, was manually graded, and reloaded at rating 3. Hostile `<img onerror>` input created 0 image elements and did not execute; private sentinel was absent. |
| Keyboard and responsive widths 320/390/760/1280 | PASS | Keyboard focus + Enter activated vector discovery. Headless Chrome reported no document horizontal overflow at all four widths; 320 px candidate/result bounds stayed inside the viewport. Browser snapshot and keyboard interaction were exercised. No screen reader or other assistive technology was tested. |
| Relevant offline regressions and full offline suite | PASS | Targeted regression command ran 25 tests, all passed. Full suite ran 82 tests, `OK (skipped=2)`; skip reasons are listed below. |
| Wheel/build/install/CLI and loopback smoke | PASS with environment note | Wheel built with system Python/setuptools, installed in a clean temporary venv, CLI help passed, and installed app returned health, HTML, and JS successfully on loopback. The repository `.venv` lacks setuptools; its no-build-isolation wheel attempt failed as recorded below, then the same build passed under system Python. |
| Live Elasticsearch | NOT RUN | No dedicated safe live fixture was provided |

## Environment and exact evidence

- Requested model: `gpt-6-luna`.
- Runtime model identity: **UNVERIFIED**; no runtime model metadata was exposed.
- Repository baseline: `7ead654` / `v0.12.1`; tested worktree package version `0.13.0`.
- Versions: system and repository Python `3.12.3`; Node `v22.23.2`; npm and npx `10.9.8`; Playwright CLI `0.1.22`; browser user agent `HeadlessChrome/154.0.0.0` on Linux x86_64. `command -v npx` succeeded.
- Browser coverage: Chromium only, headless, through `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`. Keyboard Enter activation and accessible snapshot labels were checked. No screen reader, Firefox, WebKit, or other assistive technology was tested. Browser automation does not establish universal accessibility.
- Playwright CLI flow used temporary loopback app instances (`127.0.0.1:44307`, `:45899`, and a loading-state instance at `:45507`) backed by synthetic Elasticsearch ports (`:41885`, `:44205`, `:38863`) and disposable SQLite. `@playwright/test` was not used. Relevant exact commands included:

  ```text
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --version
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh open http://127.0.0.1:45899 --browser chrome
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh snapshot
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill <snapshot-ref> http://127.0.0.1:44205
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click <snapshot-ref>  # Connect
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh select <snapshot-ref> cycle13-ui-synthetic
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click <snapshot-ref>  # Load saved concept
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill <snapshot-ref> 'synthetic vector target query'
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click <snapshot-ref>  # Run BM25 preview
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "document.querySelector('#concept-vector-candidates').focus()"
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh press Enter
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "(async () => { document.querySelector('#concept-vector-candidates').click(); await new Promise(r => setTimeout(r, 150)); return {status:document.querySelector('#concept-vector-status').textContent, cards:document.querySelectorAll('#concept-vector-results article').length, disabled:document.querySelector('#concept-vector-candidates').disabled}; })()"
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh select <snapshot-ref> 3
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click <snapshot-ref>  # Explicit grade save
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh reload
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh resize 320 900
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh resize 390 900
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh resize 760 1000
  /home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh resize 1280 1000
  ```

- Focused command: `python3 -m unittest tests.test_vector_candidate_discovery_acceptance -v` — exit 0, 8 tests passed.
- Targeted regression command: `python3 -m unittest tests.test_match_evidence_acceptance tests.test_information_need_groups_acceptance tests.test_concept_tune_readiness -v` — exit 0, 25 tests passed.
- Full offline command: `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 ./.venv/bin/python -m unittest discover -s tests -v` — exit 0, 82 tests, 2 skipped. `LiveConceptAcceptance.setUpClass` skipped because the explicitly unreachable loopback endpoint refused the connection; tokenizer parity skipped because `ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE` was unset. No live Elasticsearch was contacted.
- Packaging: `./.venv/bin/python -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/cycle13-wheel` exited 2 because the repository venv has no `setuptools.build_meta`. `python3 -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/cycle13-wheel` passed using system setuptools `68.1.2`; wheel SHA-256: `173e95fba4a05f3a3744c3df7e8917fff4b8d95679ae6a07feaf2f01bea32eb2`.
- Install and CLI: `python3 -m venv /tmp/cycle13-install-venv`, `/tmp/cycle13-install-venv/bin/python -m pip install --no-deps /tmp/cycle13-wheel/es_rag_tuning_workbench-0.13.0-py3-none-any.whl`, and `/tmp/cycle13-install-venv/bin/es-rag-workbench --help` all passed. An installed CLI process started with temporary `ES_RAG_CONCEPT_DB` and loopback host; `/api/health` returned `{"ok":true,"version":"0.13.0"}`, `/` and `/app.js` returned HTTP 200, and the JS contained the vector-candidates UI route.
- Static checks: `python3 -m py_compile tests/test_vector_candidate_discovery_acceptance.py`, `node --check es_rag_tuner/web/app.js`, and `git diff --check` passed.
- Test source SHA-256: `3469578ac2c2b375ec0d794f46ead1cb3f71c8fb6e05abf783c8d3feea01aea3`.
- Temporary synthetic servers, SQLite files, mode file, wheel, and install venv were removed after evidence collection. No screenshot was captured or checked in. The browser console's 503 entries were generated by the intentional shard-failure scenario; favicon 404 was an unrelated static browser request.

## Issues found and resolved during acceptance

- Initial focused run (`python3 -m unittest tests.test_vector_candidate_discovery_acceptance -v`) failed because the candidate response included an unconfigured `secret` source field. The QA agent reported the exact payload to the coordinator without editing production; implementation added a mapping-resolved source allowlist and projection. The final endpoint test asserts only `title` and `body` are requested and returned.
- After the response contract began requiring `hits.total.relation == "eq"`, the synthetic happy-path fixture was updated to model that exact-complete Elasticsearch response. Missing totals and `_shards.failed: false` remain malformed-response cases and pass only when rejected.
- The repository venv wheel build failed because `setuptools` is absent there. Building with the system Python, which has setuptools `68.1.2`, succeeded; the wheel was installed into a clean temporary venv and the installed CLI smoke passed.

## Disposition

**GO for the synthetic/offline Cycle 13 acceptance scope.** The required endpoint, UI, regression, package/install, and local loopback gates passed after implementation fixes. Live Elasticsearch remains NOT RUN; the result does not establish live-cluster behavior. The two offline skips remain skips, not passes.
