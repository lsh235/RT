# Changelog

User-visible changes are recorded here. Historical notes below distinguish the release baseline from work in progress.

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
