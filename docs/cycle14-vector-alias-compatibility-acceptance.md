# Cycle 14 vector alias compatibility acceptance

## Scope and decision rules

This acceptance checks vector candidate discovery when a saved corpus target is an Elasticsearch index alias. Focused tests use a disposable SQLite database, loopback workbench server, and synthetic Elasticsearch endpoint. The browser smoke also uses only loopback services and a disposable database. No configured user database, corpus, credentials, or live Elasticsearch cluster was used.

**PASS** requires the command and observed result to be recorded with every assertion in that gate satisfied. **FAIL** means an assertion, build/package step, installed-app smoke, or required browser action failed. **NOT RUN** means the gate was not executed or a prerequisite was unavailable; it is not a pass. A skipped test is reported separately with its reason. Live Elasticsearch is **NOT RUN** without an explicitly safe fixture.

## Results

| Gate | Result | Evidence |
|---|---|---|
| Single-target alias | **PASS** | Mapping response was keyed by concrete `docs-000001`. Mapping, vector count, and search requests used saved alias `docs-current`; the hit's concrete `_index` was returned. A saved judgment was found by `("docs-000001", "same-id")`. |
| Compatible multi-target alias | **PASS** | Both concrete mappings were accepted. Two hits with the same `_id` from `docs-000001` and `docs-000002` remained distinct; only the exact concrete-index judgment was attached. |
| `max_inner_product` alias metric | **PASS** | A synthetic single-target alias with float `rag_embedding` using `max_inner_product` returned a candidate; mapping, count, and search stayed on saved alias `docs-current`, with the hit retained as concrete `docs-000001`. The search used the saved query and local-only embedding. |
| Incompatible alias targets and target membership | **PASS** | Eight synthetic incompatibilities (missing field, wrong field type, wrong model dimensions, unequal target dimensions, disabled indexing, non-float elements, conflicting similarity, and conflicting `index_options`) each returned a clear error before embedding or candidate search. A hit with `_index=not-a-resolved-target` failed closed with no candidate response. |
| Concrete index regression and API/connect status | **PASS** | Concrete-index candidate discovery still succeeded. `/api/corpus/schema`, `/api/mapping`, and `/api/connect` reported alias data consistently; connect exposed mapping availability and dimensions. `/api/health` returned `ok: true`. |
| Cycle 13 safety contract | **PASS** | Cycle 13 vector candidate regression tests verified saved-query/index bounds, hostile caller override resistance, local-only embedding, exact judgment semantics, source projection, read-only DB/ES behavior, partial-result URL, and strict complete responses. |
| Focused and targeted regression suites | **PASS** | Cycle 14 acceptance: 6 tests. Targeted vector/BM25/concept regressions: 33 tests. Both commands exited 0. |
| Full offline suite | **PASS with skips** | 88 tests, `OK (skipped=2)`. Live Elasticsearch setup skipped because the configured offline URL had unsupported scheme `offline`; tokenizer parity skipped because `ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE` was unset. These remain skips, not passes. |
| Wheel, isolated install, CLI, and loopback health/assets | **PASS with interpreter note** | Repository venv wheel build failed because `setuptools.build_meta` is unavailable. System Python built the wheel; isolated install, installed CLI help, health, HTML, JS, and CSS smoke passed. |
| Playwright saved-alias flow | **PASS, synthetic** | Playwright CLI exercised saved concept → preview → alias-backed vector candidate → manual rating `2` → page reload → reconnect/reload concept/preview/vector candidates. The `max_inner_product` candidate showed concrete `docs-000001/ui-alias-doc`, and the saved rating `2` reappeared. The fixture patched embedding to deterministic zeros while asserting local-only mode; this does not validate the installed FastEmbed runtime. |
| Live Elasticsearch | **NOT RUN** | No explicitly safe live fixture was provided. |

## Source review note

The official [Elasticsearch dense vector field type documentation](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector), accessed 2026-10-18, lists four supported similarity measures for float vectors, including `max_inner_product`. This source review prompted the added regression because earlier alias compatibility coverage exercised `cosine` but did not prove acceptance of this other documented float-vector metric. This is documentation evidence only; it does not validate behavior against a live Elasticsearch cluster.

## Commands and environment

- Requested model: `gpt-6-luna`.
- Runtime model identity: **UNVERIFIED**; this session exposed no metadata proving it.
- Baseline commit/tag: `b6e33a537c29881c97c8d86b1f9eb8873742a0fa` / `v0.13.0`.
- Tested package version: `0.13.1`.
- System and repository Python: Python `3.12.3`. System pip `24.0`, repository venv pip `26.2.1`, system setuptools `68.1.2`.
- Playwright CLI: `0.1.22`; npx was available. Browser smoke used Chromium headless through `/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh`.

Focused acceptance:

```text
python3 -m unittest tests.test_vector_alias_compatibility_acceptance -v
```

The initial implementation run found one failure: `/api/mapping` returned `has_rag_embedding_mapping=false` for alias `docs-current`, despite the concrete-key dense-vector mapping. Implementation updated the endpoint to merge returned concrete mappings and use all-target vector compatibility; the follow-up run passed all 5 tests. After adding the `max_inner_product` regression, the focused suite passed all 6 tests.

Targeted regressions:

```text
python3 -m unittest tests.test_vector_candidate_discovery_acceptance tests.test_match_evidence_acceptance tests.test_information_need_groups_acceptance tests.test_concept_tune_readiness -v
```

Result: **33 tests passed** in 2.422 seconds.

Full offline suite:

```text
env ES_RAG_ACCEPTANCE_ES_URL=offline://disabled .venv/bin/python -m unittest discover -s tests -v
```

Result: **88 tests**, 2 skipped, 6.277 seconds. `LiveConceptAcceptance` skipped because `offline://disabled` produced `unknown url type: offline`. Tokenizer parity skipped because `ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE` was not set. The offline setting prevented a live ES attempt.

Static checks:

```text
python3 -m py_compile tests/test_vector_alias_compatibility_acceptance.py es_rag_tuner/retrieval.py es_rag_tuner/concepts.py es_rag_tuner/server.py
node --check es_rag_tuner/web/app.js
git diff --check
```

All passed.

Packaging attempted `.venv/bin/python -m pip wheel . --no-deps --no-build-isolation`; it exited 2 with `BackendUnavailable: Cannot import 'setuptools.build_meta'`. System Python fallback succeeded:

```text
python3 -m pip wheel . --no-deps --no-build-isolation --wheel-dir <temporary-wheelhouse>
python3 -m venv <temporary-install-venv>
<temporary-install-venv>/bin/python -m pip install --no-deps --no-index <temporary-wheelhouse>/es_rag_tuning_workbench-0.13.1-py3-none-any.whl
<temporary-install-venv>/bin/es-rag-workbench --help
```

Wheel: `es_rag_tuning_workbench-0.13.1-py3-none-any.whl`, 180,085 bytes, SHA-256 `d4e9b24018e01528f230d55a0b2c37856c4ca5582756716a4bc380b2bfcdde60`. It installed with `python3 -m pip install --no-deps --no-index <wheel>` into a fresh venv. Installed `es-rag-workbench --help` passed. The installed app returned `{"ok":true,"version":"0.13.1"}` at loopback port `47225`; `/`, `/app.js`, and `/style.css` returned HTTP 200 with non-empty content.

## Browser evidence and limits

The first browser attempt used the actual app runtime and stopped at the expected local-runtime error: FastEmbed was not installed in the active workbench environment. To still exercise the unchanged UI path, the final browser run used a temporary app process with a deterministic `embeddings.embed_texts` stub that asserted `local_files_only=True`; synthetic Elasticsearch returned a single hit from concrete index `docs-000001` for alias `docs-current`.

The refreshed successful flow used temporary app port `39509` and synthetic ES port `35217`; the synthetic mapping used `similarity=max_inner_product`. It connected, loaded `Cycle 14 alias candidate`, ran the saved query preview, loaded vector candidates, manually saved rating `2`, reloaded the page, reconnected, loaded the concept again, and confirmed the reloaded candidate's judgment selector remained at `2` with concrete identity `docs-000001/ui-alias-doc`. The CLI reported one browser console error, an expected missing `/favicon.ico` 404; no application JavaScript exception was observed. Playwright snapshots and temporary database/server files created during this run were removed afterward. No `@playwright/test` was used.

The exact CLI interaction sequence used the refs from the immediately preceding snapshot at each step:

```text
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh open http://127.0.0.1:39509 --browser chrome
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill e21 http://127.0.0.1:35217
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill e26 docs-current
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e28
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh select e83 cycle14-ui-alias
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e84
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill e98 'saved alias query'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e99
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e155
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh select e291 2
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click e294
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh reload
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click f1e28
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh select f1e83 cycle14-ui-alias
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click f1e84
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh fill f1e98 'saved alias query'
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click f1e99
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh click f1e155
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh eval "(() => { const controls = document.querySelector('#concept-vector-results .judge-controls'); return {index: controls?.dataset.index, id: controls?.dataset.id, rating: controls?.querySelector('.judge-rating')?.value}; })()"
```

This browser evidence covers UI wiring and persisted manual judgment with a mocked embedding. It does not prove that the real FastEmbed model is installed or runnable. The loopback API tests and browser smoke do not establish behavior against a live cluster.

## Cleanup and disposition

Wheel, install venv, health database, and browser database lived under `TemporaryDirectory` paths and were cleaned after their runs. Synthetic loopback processes were stopped. The 23 Playwright snapshots/logs created during this run were removed; existing snapshots were preserved.

**Disposition: PASS for the synthetic and offline Cycle 14 acceptance scope.** Live Elasticsearch and actual FastEmbed runtime validation remain NOT RUN. No staging, commit, or tag was performed by QA.
