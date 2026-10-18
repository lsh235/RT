# OSS readiness plan: v1.6.0–v1.16.0

## Objective and fixed boundary

Turn this repository into a usable local Elasticsearch search and RAG retrieval quality workbench that an external developer can install, validate, and contribute to. The product remains local-first and loopback-bound: users can search an existing Elasticsearch index or a small private document corpus, inspect evidence, compare BM25/vector/hybrid and optional reranking, evaluate relevance, run bounded reproducible tuning, and export settings/results for another program.

This is a fixed 12-stage plan. It does not add public SaaS, enterprise SSO/billing/organization management, production multi-tenant security guarantees, arbitrary vector databases, a general RAG answer-generation platform, unlimited crawling, or automatic writes to arbitrary shared indexes. Do not add phases or extend the stopping point beyond v1.16.0.

The existing [Cycle 45–48 roadmap](../cycle45-48-roadmap.md) remains authoritative for its private-knowledge acceptance gates. This plan maps those requirements into the version sequence; it does not mark old gates complete or silently weaken them.

## Baseline and preservation record

Recorded before implementation on 2026-10-18:

- Existing stable tag `v1.5.0` remains at `f8e9fc51dce4663d74b2c4c16ec80fa8a0704dd1` (tagged commit `82f73359ae67141fe4e6201a91edac2633d9c239`). It is not moved.
- Starting HEAD was `868b875cf69c12d52c119b2e1ae3455b4918cd2e` (`docs: record cycle execution gates`), equal to `origin/main`; it descends from the `v1.5.0` tagged commit.
- Starting branch was `codex/cycle-44-positive-target-misses`. The requested `codex/oss-readiness-v1-16` branch did not exist locally or remotely. Work continues on a new branch from the starting HEAD, preserving its ancestry.
- Annotated tag `baseline-oss-readiness-v1-16` records the starting HEAD. It records the committed baseline only; it does not contain the untracked files below.
- The initial tracked worktree was clean. These pre-existing untracked files are user work and must remain outside this task's staging and commits unless the user later directs otherwise: `docs/agent-sdk-upstream-review-2026-10-18.md`, `docs/novice-retrieval-improvements-2026-10-18.md`, and `tests/cycle37_positive_target_misses_browser.js`.
- Initial metadata inspection found `pyproject.toml` at 1.5.0 while `es_rag_tuner/__init__.py` reported 1.3.0. The repository had no root LICENSE, CI workflow, browser package manifest/lockfile, or contributor guide. R01 must reconcile application/package version metadata.
- The user selected Apache-2.0 for project code. This does not resolve redistribution rights for bundled third-party sample data or dependencies; investigate those independently and do not infer permission.

The baseline facts above are repository observations, not a claim that the project passed the release gates. The status at each stage is tracked in [progress.json](progress.json).

## Existing architecture snapshot and exploration limits

The installed `codebase-memory` skill was read. Its graph tools were not available in this session, so graph generation/freshness and graph coverage are **NOT RUN**. Structural findings use source and repository file inspection as a fallback; no complete call-graph or exhaustive impact claim is made. Relevant paths and fallback evidence are listed in [architecture overview](../architecture/overview.md).

## Version plan and acceptance mapping

| Stage | Fixed version | Scope | Existing private-knowledge roadmap mapping |
|---|---|---|---|
| R01 | v1.6.0 | Repair authenticated live ES tests; separate offline/live/browser/provider checks; pin repeatable Python/browser dev setup; wheel install smoke; offline and disposable-ES CI; read-only ES doctor; contributor/changelog foundation. | Test and contributor foundation for C45–C48. |
| R02 | v1.7.0 | Incrementally separate routes/services/storage/evaluation and frontend modules; standardize errors/config validation; version DB migrations; backup/restore behavior; document API contracts. | C45 migration and lifecycle implementation support. |
| R03 | v1.8.0 | Beginner connection → field selection → first search → judgment → comparison path; distinguish sample/live modes; avoid storing secrets by default; Korean/English, accessibility, and recovery guidance. | C45 onboarding and C46 initial workflow. |
| R04 | v1.9.0 | TXT/Markdown/CSV/JSONL import, field selection, partial failure, provenance/versioning, duplicate policy, edit/delete/export/restore, quotas and input limits. | C45 account-owned document lifecycle. |
| R05 | v1.10.0 | Real configurable chunking, source offsets/token counts, progress/cancel/retry/recovery, generation validation and alias swap, stale chunk cleanup. Never reindex an externally shared corpus automatically. | C45 sync recovery and C46 private indexing. |
| R06 | v1.11.0 | Configurable vector/model profiles and revisions/prefixes; retain E5 compatibility; at least two actual local embedding profiles; reject incompatible spaces; report cache/setup failures. | C46 private vector readiness; actual models required. |
| R07 | v1.12.0 | Consistent BM25/vector/RRF comparison; field boosts/candidate pool/top-K/RRF; path/rank/score evidence; optional real local reranker; filters and identity across modes. | C46 full search workflow and lane identity. |
| R08 | v1.13.0 | Versioned query/qrels import/export and provenance; leakage-aware splits; judged-only versus unjudged semantics; metrics/coverage; query regressions; independent reference metrics. | C47 account-scoped evaluation and split integrity. |
| R09 | v1.14.0 | Bounded deterministic tuning (30 candidates/10 minutes by default); train search and validation selection; no test leakage; miss diagnostics with bounded claims; baseline retained if candidates worsen. | C47 reproducible tuning and C48 diagnosis evidence. |
| R10 | v1.15.0 | Experiment bundles/fingerprints; external runtime examples and context export; token budget/dedup; secret-free diagnostics; backup/restore; scale measurements and bounded concurrency. | C48 reproducibility, data preservation, external handoff. |
| R11 | v1.16.0-rc.1 | License/dependency/sample-data audit; Korean/English user docs and contribution/security/changelog; support matrix; loopback Docker/Compose; install/upgrade/migration/restore docs; independent comprehensive QA. | C48 regression, boundary, recovery, docs and version closure. |
| R12 | v1.16.0 | Freeze features; final regression, package install and test-set evaluation; final GO/NO-GO report; last commit and push; prove local/remote SHA and only this task's tags. | Closes the fixed C45–C48 mapping if and only if its inherited required gates pass. |

Every stage has a dedicated `docs/acceptance/<version>.md` record. Do not advance to a later feature stage while the current stage has an unresolved required FAIL. Failed or unavailable gates remain explicit; the final release is NO-GO if any required gate is FAIL or NOT RUN.

## Search-quality evidence rules

- Keep the existing 25-document Jira sample as a regression fixture, not proof of general relevance or tuning benefit.
- Add at least three evaluation scenarios with distinct information needs and aim for at least 100 queries with sourced relevance judgments. Prefer redistributable public qrels or authorized materials. Record subset extraction rules and omitted relevant documents.
- Keep AI suggestions separate from human-verified ground truth. Do not simplify the corpus by dropping hard negatives or unjudged documents.
- Split related queries/document families to limit leakage. Use train for search, validation for selection, and the final test set once for the final decision.
- Compare identical corpus/split/cutoff baselines with nDCG, Recall, MRR, judged coverage, and p50/p95 latency. Report uncertainty and costs; small changes are not guaranteed improvements.
- Keep the stable baseline when evidence is insufficient. “No additional improvement observed” is a valid result. Mock/synthetic evidence cannot close a real corpus or retrieval-quality gate.

## Version procedure and limits

For each version: record state; fix scope and acceptance; use at most six bounded work packages; assign implementation/test writing/execution to GPT-6-Luna subagents with named file ownership; have an independent worker perform acceptance checks; coordinator reviews evidence and assigns PASS/FAIL/NOT RUN; update documentation and changelog; explicitly stage only this task's files; commit only a version whose required gates pass. The coordinator owns integration, acceptance judgment, commit/tag/push, and preservation of the user's unrelated work.

The requested agent model is recorded as `gpt-6-luna`; runtime model identity is **UNVERIFIED** unless the execution environment exposes independent evidence. Workers must not create child agents or commit/push.

Allow one initial implementation round and at most three cumulative fix-and-retest rounds per version (48 maximum across the fixed 12 stages). Stage renaming, a new agent, or a resumed session does not reset the count. Stop the current version when its fix budget is exhausted, preserve the checkpoint, write a NO-GO assessment, and do not proceed to later feature work.

Do not kill/replace user services or containers. Use temporary DBs, unique ports, and task-owned Elasticsearch indexes. Do not push intermediate versions, force-push, delete remote branches, bulk-push tags, merge to the default branch, or create a GitHub Release/PR. At the end, push only `codex/oss-readiness-v1-16` and tags created by this work, then compare local and remote object IDs.

## Decisions and unresolved external evidence

- Project code license: **Apache-2.0 selected by the user**.
- Third-party sample-data redistribution rights: **not yet established**; investigate exact sources and terms before public release. If rights remain unclear, exclude those materials from redistributed artifacts or leave the release gate NOT RUN; do not guess.
- Public qrels/corpus rights and any support matrix: must be sourced and recorded before making public support/quality claims.
- Branch protection, remote CI status, and GitHub write access are checked at their corresponding stage; no remote success is assumed.
