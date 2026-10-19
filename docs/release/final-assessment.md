# Final assessment: OSS readiness v1.6.0–v1.16.0

**Final disposition: NO-GO for v1.16.0 stable release and public distribution.**
**Plan status: fixed scope R01–R12; final post-fix CI check follows the authorized push.**
Date: 2026-10-19
Branch: codex/oss-readiness-v1-16
Decision evidence: docs/acceptance/v1.16.0.md and docs/acceptance/v1.16.0-independent-qa.md

## Scope and outcome

The fixed objective was a local-first Elasticsearch/RAG retrieval workbench that developers can install, use with a local or existing Elasticsearch service, evaluate, and contribute to. The scope excludes public SaaS exposure, production multi-tenant security guarantees, enterprise account features, arbitrary vector databases, unrestricted crawling, and automatic modification of arbitrary shared indexes.

R01–R11 implemented and documented the planned work through the v1.16.0-rc.1 distribution-readiness checkpoint. R12 froze product features. Its first final-head CI run exposed workflow/test issues; bounded fix/retest round 1 corrected them, and independent local retests passed. The final branch push triggers the last hosted-CI check. The checkout has evidence for local installation, BM25 and retrieval workflows, evaluation/tuning features, browser mocks, package installation, and synthetic Elasticsearch/Compose paths. Those operation checks do not establish representative retrieval quality or production readiness.

The final public-release decision is NO-GO because sample-data redistribution rights and representative judged-corpus quality evaluation are required but remain NOT RUN. Apache-2.0 was selected by the user for project code. The user offered to provide separate sample permission evidence, but no permission evidence was received or verified before closure.

## Version commits and tags

Every listed v1.6.0–v1.15.0 tag is an existing annotated task release tag. The tag target may be an acceptance commit after the implementation commit. R11 and R12 have no release tag because their mandatory gates are unresolved.

| Stage | Version | Implementation / checkpoint commit | Annotated tag target | Final status |
| --- | --- | --- | --- | --- |
| R01 | v1.6.0 | 4c541f647c595bb14a2488f7033c89d95716ea0a | 4c541f647c595bb14a2488f7033c89d95716ea0a | Historical stage complete; preserve recorded blockers |
| R02 | v1.7.0 | 4c6b60ba6fe51ef30df8d14421e7d281d479ef14 | 4c6b60ba6fe51ef30df8d14421e7d281d479ef14 | Complete |
| R03 | v1.8.0 | 2dbe59482ddb3835697f7475bc524cc74b0deb08 | 2dbe59482ddb3835697f7475bc524cc74b0deb08 | Complete |
| R04 | v1.9.0 | 3eb09bf692de8a0338279f6e7f9c9df4de554419 | 3eb09bf692de8a0338279f6e7f9c9df4de554419 | Complete; representative quality remained NOT RUN |
| R05 | v1.10.0 | ee9bd14b131bae4654083255784db7f78233d960 | ee9bd14b131bae4654083255784db7f78233d960 | Complete; representative quality remained NOT RUN |
| R06 | v1.11.0 | 217a3b0a86ab4414a2d5a3fa17e354a5a45d2cb2 | 217a3b0a86ab4414a2d5a3fa17e354a5a45d2cb2 | Complete |
| R07 | v1.12.0 | a4d68c8882e80bedb7328b75e4af53748517641a | b79fb5fb4c70efc7400424f324a4aba4ddc84d7c | Complete |
| R08 | v1.13.0 | 8b50be380f0c790c549a12a5181aa68d807e189d | a377db43456b26057d7b66b029c2ceb0c441867a | Complete; permission and quality blockers carried forward |
| R09 | v1.14.0 | 1b88c1792bd9c4212373b29b9fd7bc1b76cc8506 | 5ffb1b3559f01ecded86eff49a4f57aaf047026f | Complete |
| R10 | v1.15.0 | 9fb2ce615c4ea5ea7ec168c8faf64cf381160927 | 3ad25c13bb0cf6334a1bf36a6b54c841ce2c8c58 | Complete |
| R11 | v1.16.0-rc.1 | 6b27b6f8eaa37bfe8fdd8fe5151799f0f78c678d | None | Technical/documentation checks passed within limits; overall NO-GO |
| R11 acceptance | v1.16.0-rc.1 | 3a19dd8ed45189f0868227cb974b2c158b5eda06 | None | Independent evidence and blocking disposition committed |
| R12 | v1.16.0 | Initial NO-GO acceptance: 198b74ccf7fdd62d91bc77160214d978a9b20e52; post-CI fix/retest closure is the final pushed branch head | None | NO-GO; no stable or RC tag |

The existing baseline tag baseline-oss-readiness-v1-16 records the original starting HEAD and remains unchanged. No tag is created or moved by R12.

## Acceptance evidence

| Area | Evidence status | Interpretation |
| --- | --- | --- |
| Offline regression | PASS WITH LIMIT | Independent fresh Python 3.10.14 and 3.12.0 runs each reported 301 passed and 1 documented tokenizer-preview skip. The skipped test requires a fixture containing four pinned tokenizer/config assets; tokenizer parity remains NOT RUN. |
| Browser | PASS, MOCK ONLY | The browser suite passed with the configured Python interpreter, including Cycle 44 and R03–R09 fixtures. These mocks do not contact Elasticsearch. |
| Package install/repeatability | PASS, SAME INPUT/HOST | Four retained wheels built from identical committed inputs had identical SHA-256 bf55a2719b558c15e9d9ff72ec9ddfa3336e36bbadb52983d63befa3eb9d7d29, size 344,324 bytes, and identical 36-entry manifests. The fix-round-1 package smoke also passed with two identical wheels. The wheel includes the unresolved Jira sample files. |
| Live Elasticsearch / Compose | PASS IN R11 AND R12 ROUND 1, SYNTHETIC ONLY | Independent QA exercised a task-owned Elasticsearch 9.5.5 and loopback Compose path with synthetic input: bootstrap, authenticated BM25 search, persistence across down/up, and 19 R12 live concept-acceptance cases passed. No sourced-corpus quality is established. |
| SQLite migration/backup/restore | PASS IN R11, SYNTHETIC ONLY | Legacy synthetic SQLite fixtures were migrated and per-file backup/restore passed integrity and permissions checks. No user database or corpus was used; this is not an atomic Elasticsearch-plus-database restore claim. |
| Dependency and artifact inspection | PASS WITH LIMIT | Locked development dependencies installed and package contents were inspected. Dependency license metadata exists, but complete optional-extra notice delivery and model/tokenizer rights review remain incomplete. Both sample files are in the wheel and Docker image. |
| Support matrix | PASS WITH LIMIT | Independently exercised: Linux x86_64 WSL2, Python 3.12.3, Node 22.23.2/npm 10.9.8 with Chromium, Docker 29.7.2/Compose 5.5.0, Elasticsearch 9.5.5. Python 3.10 full suite, native Windows/macOS, alternate browser/ES versions, Docker Desktop/Podman, optional model/provider combinations, and production use are unverified. See docs/support-matrix.md. |
| Sourced retrieval quality | NOT RUN | No permission-cleared representative dataset with at least 100 human judgments across at least three scenarios was provided. No final nDCG, Recall, MRR, judged coverage, uncertainty, p50/p95 latency, or improvement claim is available. The existing 25-document Jira sample is a regression fixture only. |
| Public redistribution rights | NOT RUN — BLOCKING | Apache-2.0 is confirmed for project code. Separate redistribution permission for both included sample files was not received or verified. Optional dependency notices and full model/tokenizer artifact rights review are incomplete. |
| GitHub-hosted CI | INITIAL FAILURE; FIX-ROUND-1 LOCAL RETEST PASS; FINAL RUN PENDING | [Run 39179221117](https://github.com/lsh235/RT/actions/runs/39179221117) failed on the first pushed closure head. The workflow/lock/test fixes passed independent local retests, including 19 live cases against disposable Elasticsearch. The final pushed head receives a separate hosted-CI run; the exact tested SHA and result are included in the task completion report. |

## Code and product changes across the fixed plan

R01–R02 repaired the development/test foundation and progressively separated backend, frontend, storage, and evaluation responsibilities while documenting API and migration contracts. R03–R05 added the onboarding and account-scoped private document/index lifecycle, including ingestion, chunking, recovery, and compatibility boundaries. R06–R07 made vector profiles and BM25/vector/hybrid retrieval behavior more configurable and inspectable, with optional local reranking kept behind its feature boundary. R08–R09 added judged-dataset workflows, leakage-aware splits, independent metric checks, bounded tuning, and miss diagnostics. R10 added reproducibility/context export and recovery guidance. R11 added the Apache-2.0 project license, dependency/sample inventories, support and installation documentation, loopback Compose, and independent distribution QA.

R12 made no product implementation changes. It corrected CI dependency/setup and test assumptions, recorded independent retest evidence, and retained the unresolved release blockers. The feature history does not imply that every optional model, provider, platform, or user scenario was exercised.

## Retrieval-quality baseline versus final

The user-provided historical baseline describes a 25-document / 10-query Jira sample with BM25 Recall@5 and MRR@5 of 1.0. This is small fixture evidence only and was not treated as current, independent, or representative quality evidence in R12.

A final held-out test comparison was NOT RUN because no permission-cleared representative dataset with sufficient human judgments was supplied. Therefore there is no measured baseline-to-final quality delta and no claim that R01–R12 improved general retrieval quality. Mock tests, synthetic Elasticsearch documents, and the bundled Jira fixture cannot substitute for the required sourced evaluation.

## Support, security, and preservation limits

- The documented Docker/Compose configuration binds the development services to loopback and disables Elasticsearch security only for that local development path.
- The evidence does not establish production hardening, public-network suitability, enterprise SSO, or cross-tenant security guarantees.
- The independent live run used unique task-owned ports and indices. User services on ports 9200 and 8765 were not contacted or modified.
- No user database, source corpus, account state, or Elasticsearch index was used for QA.
- These three pre-existing untracked user files remain uncommitted and unchanged:
  - docs/agent-sdk-upstream-review-2026-10-18.md — SHA-256 25be595cd4eb5adc132aabf2d3762c78d45ba8533b63e66b44c3287692f710ad
  - docs/novice-retrieval-improvements-2026-10-18.md — SHA-256 38ac8c1573c007b9266c4b931d6e7b50d6f00c1e5d9abe0dc4e6f541864d08c7
  - tests/cycle37_positive_target_misses_browser.js — SHA-256 0e81b03a575df377219e45fcb65f3683bd5f053535abdefbb2432f3cb5a6a54f

## License and resumption requirements

Project code license: Apache-2.0, selected by the user and recorded in LICENSE and package metadata.

The bundled NDJSON issue sample and mapping/settings JSON have separate recorded hashes in docs/acceptance/v1.16.0-independent-qa.md. Code licensing does not establish rights for those records. The user said separate permission evidence can be provided, but no evidence has been received or verified. Do not redistribute the current wheel or container until that evidence is reviewed or the assets are removed from all distribution paths and the artifacts are rebuilt and rechecked. Complete the optional dependency notice and model/tokenizer provenance, rights, and notice inventory as well.

To reopen the final quality gate, provide permission-cleared human judgments for at least 100 queries over at least three information-need scenarios, document corpus provenance and extraction, preserve unjudged/hard-negative documents, and use leakage-aware train/validation/test splits. Run the final test set once against identical baseline and final corpus/split/cutoff settings; report nDCG, Recall, MRR, judged coverage, p50/p95 latency, uncertainty, and cost. If any required gate remains unavailable, retain NO-GO.

## Agent and remote evidence

- Requested subagent model: gpt-6-luna.
- Observable runtime model identity: UNVERIFIED.
- Coordinator-owned final disposition: NO-GO.
- The final pushed commit includes this assessment, the R12 acceptance report, and fix-round-1 CI corrections. The authorized branch and previously created task tags are pushed; local versus remote branch SHA equality and hosted CI are checked after push. Exact final SHA and GitHub Actions status are reported in the task completion message.
- No v1.16.0-rc.1 or v1.16.0 release tag is created. No PR, merge, GitHub Release, or force push is performed.

정해진 반복 한도에서 필수 게이트를 충족하지 못해 NO-GO로 종료했다. 미충족 항목과 재개 조건을 기록했으며 추가 반복은 실행하지 않았다.
