# Changelog

User-visible changes are recorded here. Historical notes below distinguish the release baseline from work in progress.

## [1.14.0] - 2026-10-19

- Add deterministic concept-tuning candidates with a 30-candidate and 600-second ceiling, train-only candidate metrics, and validation-only selection that keeps the baseline on ties or incomplete validation.
- Save immutable owner-scoped run snapshots with candidate traces, fingerprints, query-level known-relevant misses, and explicit incomplete-qrels limits.
- Add Korean/English budget controls and diagnostics; applying a candidate remains a separate user action.
- No representative sourced-corpus quality claim is made; the final sourced-quality gate remains open pending permission-cleared evidence.

## [1.13.0] - 2026-10-19

- Add account-scoped, immutable evaluation dataset versions with CSV/JSONL query and qrel import/export, canonical fingerprints, and source/rights/judgment provenance.
- Add train/validation/test split checks for shared information needs, query duplicates and near-duplicates, exact documents, and declared document families.
- Report Precision, Recall, MRR, nDCG, judged coverage, unknown/unjudged counts, query-level missed relevant documents, and same-corpus run comparisons with explicit metric policies.
- Keep AI-suggested judgments separate from human-reviewed ground truth and require a frozen configuration for a one-time test run per dataset version/corpus.
- Preserve the existing 25-document Jira evaluation as a regression fixture; no permission-cleared representative qrels are bundled and no retrieval-quality improvement is claimed.

## [1.12.0] - 2026-10-19

- Give BM25, vector, and hybrid search one bounded candidate-pool and final top-K interface, while preserving filters, embedding profiles, and concrete alias document identity.
- Return per-lane original ranks and raw scores, plus separate RRF rank/score evidence; nested comment matches and lexical highlights remain attached.
- Add an optional CPU cross-encoder reranker with a pinned multilingual model, explicit download consent, local-only search loading, and before/after rank evidence.
- Label scores as uncalibrated diagnostics rather than relevance probabilities; normal search remains available without the optional reranker runtime.
- Add Korean/English controls and include the R07 mock-only browser fixture in the standard browser smoke command.

## [1.11.0] - 2026-10-19

- Add versioned local E5 and multilingual MiniLM embedding profiles with visible recipe details and cache readiness.
- Bind shared and account-private vectors to model/tokenizer revisions, runtime, dimensions, similarity, prefixes, context limits, and private passage-slicing recipe; reject incompatible profile reuse before vector search.
- Preserve the E5 default and legacy E5 vector behavior while recording profile metadata for newly vectorized indices and private generations.
- Keep BM25 usable without loading or downloading embedding models; add explicit profile selection and download-consent states.
- Validate local model execution for both profiles; retrieval-quality comparison remains outside this release's acceptance scope.

## [1.10.0] - 2026-10-19

- Add account-private character, paragraph, and pinned-token chunk policies with source offsets, source revisions, policy fingerprints, and inspectable chunk counts.
- Add persisted reindex jobs with progress, cancellation, restart recovery, retry, and per-document failure reporting.
- Stage and verify private Elasticsearch generations before switching an account-derived alias; failed or cancelled jobs retain the previous published generation.
- Document the chunk preview/policy and reindex job API, migration v3 state, and their retrieval-quality evidence limits.

## [1.9.0] - 2026-10-19

- Add account-local TXT, Markdown, CSV, and JSONL import with strict decoding, field mapping, row-level outcomes, duplicate actions, and source/content hashes.
- Track revisions for any changed document content or metadata, including import provenance, while preserving unchanged retries.
- Add versioned account knowledge export and conflict-aware restore for documents and private judgments, with account usage limits and private Elasticsearch stale-state updates.
- Migrate account-local document metadata repeatably and serialize first-open WAL setup with schema migration for each database file.

## [1.8.0] - 2026-10-19

- Add a guided first-use path for Elasticsearch connection, field inspection, first search, human relevance judgments, and retrieval-mode comparison.
- Distinguish explicitly imported sample data from existing indexes without inferring sample identity from document counts; sample import remains opt-in and targets a new index.
- Add browser-local named connection profiles for non-secret settings, localized Korean and English onboarding/result guidance, and connection recovery messages.
- Improve first-use keyboard focus and narrow-screen behavior, and add a synthetic browser regression flow to the default browser command.
- Keep sample-corpus identity and redistribution rights separate from user-index and project-code licensing claims.

## [1.7.0] - 2026-10-19

- Separate protected POST route dispatch, versioned local SQLite migrations, and per-file backup/restore helpers while retaining the loopback, authentication, CSRF, and owner-scope boundary.
- Add stable API error codes and safe user messages while preserving status codes and the `error` field; redact remote Elasticsearch failures, local paths, and partial bulk details.
- Extract a dependency-injected browser API client and Cycle 44 positive-target-miss module, loaded from an explicit same-origin static allowlist.
- Add synthetic legacy migration, failure-recovery, base/secondary backup, integrity, and restore validation coverage.
- Record migration, restore, API error, module, and ownership boundaries in the architecture and API contract guides.

## [1.6.0] - 2026-10-18

- Add a read-only Elasticsearch environment report with version-based dense vector and kNN compatibility estimates.
- Add reproducible Python and browser development dependencies, offline test entrypoint, isolated wheel-install smoke, and CI workflows.
- Add contributor setup and testing guidance.
- Declare the Apache-2.0 license selected by the project owner.
- Repair live acceptance setup for authentication, Origin, and CSRF; split opt-in live Elasticsearch checks from default offline tests.
- Align the initial UI version label, package metadata, and health response on 1.6.0.
- The code license does not establish redistribution rights for the bundled Jira issue sample corpus; those rights remain unresolved.

## [1.5.0] - Baseline

- Baseline documented in the repository README as Cycle 44 / v1.5.0. Refer to the existing feature and acceptance documents for baseline behavior; this entry is not a reconstruction of a complete historical release log.
