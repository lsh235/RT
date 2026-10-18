# Cycle 33 sample onboarding acceptance

## Scope and baseline

- Baseline: `v0.20.0`, commit `c5e79932b7a38f498824e49e561351a317eaea17`.
- Release candidate: `v0.21.0` (package/runtime/page versions were updated before the final test run).
- Feature under test: after a successful connection to a missing selected index, show a beginner-facing sample-data entry point that only opens the existing sample disclosure and focuses its existing import button. Import remains behind its existing confirmation.
- QA-owned artifacts: this report and [`tests/cycle33_sample_onboarding_browser.js`](../tests/cycle33_sample_onboarding_browser.js). Product implementation files were not edited by QA.
- Requested QA model: `gpt-6-luna`; actual runtime model identity: **UNVERIFIED**.
- Requested implementation model: `gpt-6-luna`; actual runtime model identity: **UNVERIFIED**.
- Codebase-memory graph tools were unavailable in this QA context. Source checks were bounded; no graph coverage claim is made.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Connected missing selected index shows a CTA with the index name and sample count | **PASS** | Synthetic `/api/connect` returned `cycle33-missing`, absent, with 25 expected sample records. The visible CTA named that index and count. |
| CTA opens the existing details and focuses its existing sample button, without API or storage side effects | **PASS** | Enter activated the CTA; the existing `details.sample-maintenance` opened and `#load-sample-button` received focus. API-call count and local/session storage snapshots remained unchanged across CTA activation. |
| Existing import confirmation is retained; cancel sends zero sample-import requests and accept sends exactly one | **PASS** | The fixture recorded the exact existing prompt, including “기존 인덱스는 덮어쓰지 않습니다.” Cancel sent zero `/api/sample-import` calls; accept sent exactly one. The endpoint was intercepted and returned a synthetic response. |
| Existing empty and populated indices hide the CTA | **PASS** | Synthetic existing index states with 0 and 4 documents each hid the CTA. After synthetic import success, the follow-up connection reported 25 documents and also hid it. |
| Failed/disconnected state hides the CTA | **PASS** | A synthetic HTTP 503 connection failure transitioned to the existing “연결 실패” state and hid the CTA. |
| Import backend and no-overwrite protection remain unchanged | **PASS WITH LIMIT** | `git diff --quiet -- es_rag_tuner/server.py` passed. Bounded source inspection confirmed `_sample_import` returns without writing when `index_exists(connection, index)` is true, with the existing message that the index was not overwritten. The real endpoint was not exercised against Elasticsearch. |
| Keyboard interaction and 390px viewport usability | **PASS** | Enter activated the CTA and moved focus to the sample import button. At 390px, document width remained 390px; the CTA was visible, 326px wide, and its button was 300×36px. |
| JavaScript syntax and whitespace checks | **PASS** | `node --check` passed for the app and fixture; `git diff --check` passed. |
| Offline suite | **PASS** | 101 tests passed, with 2 expected skips. See commands and limitations below. |
| Isolated `v0.21.0` wheel/module/page/health/CLI smoke | **PASS** | Isolated wheel build/install passed; version, packaged HTML/JS/CSS, CLI help, page response, and health version matched `0.21.0`. Wheel SHA256: `aea4379ff4fd78f870c8b27e93620ee6d21d15ddcd6777f1a7b46e3a5f16611c`. |
| Live Elasticsearch, actual sample import, user corpus, accessibility study | **NOT RUN** | All browser API responses were synthetic. No Elasticsearch, user database/corpus, real sample ingestion, screen reader, or user study was used. |

## Commands and environment

Browser server: `.venv/bin/python -m es_rag_tuner --host 127.0.0.1 --port 18779`, with `ES_RAG_CONCEPT_DB` pointed at a fresh temporary SQLite path. The browser fixture intercepted every `/api/**` request; no user data or credentials were read.

```bash
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle33qa open http://127.0.0.1:18779/
/home/sra235/.codex/skills/playwright/scripts/playwright_cli.sh --session cycle33qa --raw run-code --filename tests/cycle33_sample_onboarding_browser.js
node --check es_rag_tuner/web/app.js
node --check tests/cycle33_sample_onboarding_browser.js
git diff --check
env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 .venv/bin/python -m unittest discover -s tests -v
```

Offline suite result: `Ran 101 tests in 6.817s; OK (skipped=2)`. The live Elasticsearch acceptance setup skipped because loopback port 1 refused the connection; the optional pinned tokenizer test also skipped because no tokenizer fixture was supplied. Existing suite output included two Python `ResourceWarning`s for unclosed HTTP fixture file handles; there were no failed tests.

The package smoke staged only `pyproject.toml`, `README.md`, and `es_rag_tuner/` in a temporary directory. It ran `/usr/bin/python3 -m pip wheel --no-deps --no-build-isolation`, installed the wheel with `pip install --no-deps --target`, checked `es_rag_tuner.__version__`, packaged HTML/JS/CSS and the CTA hook, ran `python -m es_rag_tuner --help`, launched the installed package on a free loopback port with a temporary SQLite path, then verified `GET /` and `GET /api/health` returned HTTP 200 and version `0.21.0`. All smoke steps exited successfully. The wheel was `es_rag_tuning_workbench-0.21.0-py3-none-any.whl`.

The digest above is the exact SHA256 printed by the wheel build that was installed for the passing package smoke. A later hash-only rebuild of the same staged inputs produced `4b7c496c39a4a06fe8443784df5797d28bbd12869c25d0b22c790b61aec642e2`; that later wheel was not used in the recorded smoke. The build output does not establish reproducible wheel bytes across separate builds.

## External research and product decision (coordinator synthesis)

Official Elastic sources checked `2026-10-18`:

- Elastic presents sample datasets and small examples as paths for exploration and learning in [Ingest sample data](https://www.elastic.co/docs/manage-data/ingest/sample-data) and [Get started](https://www.elastic.co/docs/solutions/search/get-started).
- Searchable content must be ingested; [Ingest data](https://www.elastic.co/docs/manage-data/ingest) describes ingestion paths. [Index basics](https://www.elastic.co/docs/solutions/search/get-started/index-basics) covers creating an index, adding documents, and searching. It also warns that deleting an index permanently removes its content and metadata.
- These Elastic docs discuss Elastic sample datasets and general ingestion/index concepts. The workbench's bundled gRPC Jira sample corpus is a separate dataset; the fixture and report do not treat it as an Elastic/Kibana sample.

**Product inference:** making the existing sample-data entry point visible when a connected selected index is missing may improve discoverability for a beginner. The cited sources do not prove a UX improvement or search-quality improvement. No user study was run.

| Priority | Candidate | Expected user impact | Cost |
|---|---|---|---|
| P1, selected for Cycle 33 | Show a missing-index CTA that opens existing sample controls; retain explicit import confirmation and no-overwrite guard | Gives a new user a discoverable way to start exploring the workbench | Low; small UI-only change |
| P2 | Add a non-mutating “prepare my own index” guide explaining create → ingest → search and linking to official setup documentation | Helps users move from the included example to their own content | Medium; documentation and state-aware guidance |
| P3 | Run novice task testing for “find a sample,” “connect my index,” and “find a desired document,” then adjust the onboarding from observed failures | Measures discoverability and retrieval-task completion rather than assuming benefit | Medium/high; participant recruitment and study time |

Implementation and QA model accounting: requested `gpt-6-luna` for both implementation and QA; runtime identities are **UNVERIFIED** for both.

## Limits and repository state

- Browser acceptance proves the UI request boundary and state transitions only. The sample-import request was intercepted; this does not prove Elasticsearch ingestion.
- The deliberate synthetic 503 generated a browser resource-error console entry; the fixture excluded that expected HTTP failure from unexpected console errors and separately required zero page-level JavaScript errors.
- The first fixture run exposed two test assumptions that were corrected: the app displays a generic connection-failure label, and Chromium logs the intentionally simulated 503. The final fixture run passed; no product change was made by QA.
- No external research was performed by QA; research claims belong to the coordinator's discovery record and are not part of these test results.
- No commit, tag, push, or PR was created. The QA fixture/report are the only QA-owned files. Pre-existing unrelated untracked review documents were left untouched.
