# Cycle 34 mode comparison acceptance

## Scope and baseline

- Baseline supplied by coordinator: commit `4e127407`, tag `v0.21.0`.
- Candidate under test: `v0.22.0`, a read-only comparison of one saved query's concept-applied BM25 and local E5 vector candidates.
- QA-owned artifacts: [`tests/test_concept_mode_comparison_acceptance.py`](../tests/test_concept_mode_comparison_acceptance.py) and [`tests/cycle34_mode_comparison_browser.js`](../tests/cycle34_mode_comparison_browser.js). QA did not edit implementation files. No commit or tag was created.
- Requested QA model: `gpt-6-luna`; runtime identity: **UNVERIFIED**.
- The codebase-memory graph tools were unavailable in this context. Source checks were bounded; no graph coverage claim is made.
- The two pre-existing untracked review documents were preserved.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Saved concept/query are authoritative; caller query/index/filter/size/model/field/DSL cannot override them | **PASS** | Synthetic API test confirmed saved query, alias, size 3 and saved `status=Open` filter were used in both search bodies despite hostile caller fields. |
| Same filters and size drive both ranked lists; alias results use concrete identity | **PASS** | Captured BM25 and kNN bodies both used size 3 and the same term filter. Synthetic alias mapping included concrete `idx-a`/`idx-b` targets. |
| Delimiter-collision pairs remain distinct | **PASS** | `("idx-a", "idx-b|x")` and `("idx-a|idx-b", "x")`, which collide under a naive pipe-joined key, produced distinct metrics. |
| Per-query nDCG, judged coverage, relevant recall, grade zero, explicit null, stale exclusion, and pin semantics | **PASS** | API checks matched hand-computed nDCG for both rankings, judged coverage and recall; grade 0 remained judged, null was counted separately, stale judgments were excluded, and a pinned positive counted only when organically retrieved. A validation query with no grades returned `no_judgments` and null nDCG/recall rather than false zero. |
| Split, filter fingerprint, candidate limits and scope caveats | **PASS** | API returns one selected query and split only; filter fingerprint matched canonical current filters. Browser displayed filter scope/fingerprint, approximation, candidate bound, non-exhaustive and corpus-wide quality caveats. |
| No writes to concept, version, judgment or run tables | **PASS** | Temporary SQLite snapshots before/after success and tested failures matched exactly. |
| Missing vector mapping, uncached local model, timeouts, shard errors and malformed BM25/vector responses fail atomically | **PASS** | Synthetic error matrix returned errors without metrics or DB changes. BM25 malformed totals were rejected after correction. Vector `hits.total` relation `gte` specifically returned HTTP **503**, with an error and no metrics. |
| Browser action, keyboard use, safe rendering and responsive layout | **PASS** | Enter activated the comparison once; request carried only saved concept/query IDs and connection. Untrusted query markup rendered as text. At 390px, body width stayed 390px and metric cards stacked in one column. |
| Existing BM25 concept preview and vector-candidate flow | **PASS** | Browser fixture ran both flows before repeating mode comparison; each existing endpoint was called once and the vector-rank guidance remained visible. |
| Existing tune/generic benchmark and broader regression suite | **PASS WITH LIMIT** | Existing full offline suite passed. Interactive browser coverage for tune and generic benchmark was not separately performed; no live Elasticsearch validation was performed. |
| JavaScript/Python syntax and whitespace checks | **PASS** | `node --check` passed for app and browser fixture; `py_compile` passed for test and affected Python modules; `git diff --check` passed. |
| Full offline suite | **PASS** | 108 tests passed, 2 expected skips. Live Elasticsearch acceptance skipped because loopback port 1 refused connection; optional tokenizer parity skipped because its pinned asset fixture was absent. Existing suite emitted two `ResourceWarning`s for open HTTP fixture handles; no test failed. |
| Isolated `0.22.0` wheel/module/page/health/CLI smoke | **PASS** | Wheel built/installed in a temporary staging copy; module/page/health versions and panel matched `0.22.0`; installed module contained the corrected BM25 total validation; CLI help worked. Wheel SHA256: `d6abd514807f2599ab98a5678cca0518ba12f8f191fcf59f59a958c58127ce94`. |
| Live Elasticsearch, user corpus, actual model download, user study | **NOT RUN** | All search and browser API responses were synthetic. No user data or credentials were accessed. |

## Prior failure and correction

The first focused run found a fail-safe defect: BM25 `hits.total` was only checked for presence. With three hits, each malformed/inexact total below returned HTTP 200 and metrics:

- `"many"`
- `{"value":"many","relation":"eq"}`
- `{"value":99,"relation":"gte"}`
- `{"value":1,"relation":"eq"}`

The implementation was corrected between the first and resumed QA runs. The current helper rejects non-exact relation, non-integer/boolean/negative totals, totals smaller than the returned hit list, and hit counts inconsistent with requested size and total. The original four cases now return HTTP 503 with no metrics. A dedicated vector response test also verifies that `{"value":12,"relation":"gte"}` returns HTTP 503 with no metrics; vector total relation validation was present and passed on rerun.

## Commands and environment

API acceptance, run after correction; final result `Ran 7 tests in 0.641s; OK`:

```bash
./.venv/bin/python -m unittest tests/test_concept_mode_comparison_acceptance.py -v
```

The fixture binds a local HTTP server to an ephemeral port and sets `ES_RAG_CONCEPT_DB` to a fresh temporary SQLite database. Elasticsearch searches, mappings, vector count and embedding generation are mocked. The synthetic connection is `http://127.0.0.1:1` and was never contacted.

Browser acceptance, against the local workbench on `127.0.0.1:18782` with `ES_RAG_CONCEPT_DB` at a fresh temporary path; all `/api/**` browser responses were intercepted:

```bash
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle34qa open http://127.0.0.1:18782/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle34qa --raw run-code --filename tests/cycle34_mode_comparison_browser.js
```

The initial extended browser fixture attempt checked the metric grid after the test had navigated away from the comparison panel; the fixture was corrected to rerender comparison before measuring mobile layout. The final browser run passed with zero captured console/page errors; no product change resulted from this harness correction.

Full offline suite; final result `Ran 108 tests in 7.441s; OK (skipped=2)`:

```bash
env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 ES_RAG_CONCEPT_DB=/tmp/cycle34-qa.CY7THW/full-suite.sqlite3 .venv/bin/python -m unittest discover -s tests -v
```

Syntax/compile/diff checks:

```bash
node --check es_rag_tuner/web/app.js
node --check tests/cycle34_mode_comparison_browser.js
./.venv/bin/python -m py_compile tests/test_concept_mode_comparison_acceptance.py es_rag_tuner/concepts.py es_rag_tuner/server.py
git diff --check
```

Isolated package smoke used a temporary stage containing only `pyproject.toml`, `README.md`, and `es_rag_tuner/`:

```bash
/usr/bin/python3 -m pip wheel --no-deps --no-build-isolation -w wheelhouse .
/usr/bin/python3 -m pip install --no-deps --target install wheelhouse/es_rag_tuning_workbench-0.22.0-py3-none-any.whl
PYTHONPATH=install /usr/bin/python3 -m es_rag_tuner --help
```

The installed package was launched with a fresh temporary DB on `127.0.0.1:18783`; `GET /` and `GET /api/health` both returned 200, the page contained `v0.22.0` and the comparison panel, and health reported `0.22.0`. The wheel bytes were the ones installed for this smoke.

## External background supplied by coordinator

The coordinator supplied these official Elastic references, marked checked `2026-10-18`; QA did not independently browse them:

- [Ranking evaluation API](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval) describes per-query rated documents and query details.
- [Query and filter context](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-filter-context) distinguishes scoring queries from binary filters.
- [Explain API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-explain) explains one document's score.

These references describe Elasticsearch behavior; they do not establish product retrieval quality. No quality-improvement claim was tested.

## Limits and repository state

- API and browser assertions establish synthetic request/response behavior only. They do not establish live Elasticsearch compatibility or search quality on a user's corpus.
- Browser responses were intercepted; no actual local embedding model was loaded or downloaded.
- No user study, screen-reader study, live provider, or external AI session was used.
- No commit, tag, push or PR was created by QA. QA-owned files are limited to the two test fixtures and this report; unrelated untracked review documents remain untouched.
