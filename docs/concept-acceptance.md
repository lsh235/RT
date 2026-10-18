# Concept workflow acceptance gates

Date: 2026-10-17

This checklist defines release acceptance independently of the implementation. A gate is `PASS` only when its described evidence is recorded. `NOT RUN` is not a pass. The report must separate mock/unit, live Elasticsearch, browser, and installed-package evidence.

## Mandatory gates

| ID | Gate | Acceptance evidence |
| --- | --- | --- |
| A | Generic corpus mapping | Read mapping metadata from an existing non-Jira index with mixed scalar fields and nested fields. Show searchable/filterable/nested attributes and validate selected fields. No source index mutation. |
| B | Persistence and restart | Save, list, load, and restart-roundtrip concepts (including active metadata filters), judgments, and runs in SQLite. Verify effective filters/settings and normalized concept/judgment/source hashes appear in run provenance, while request credentials are absent from persisted DB content and API records. |
| C | Concept retrieval evidence | Preview baseline and concept-expanded retrieval with aliases, typed related terms, weights, and exclusions. Each displayed match points to original field text and a document identifier; snippets are source excerpts. No unsupported semantic/probability claims. |
| D | Judgments | Preserve ratings 0, 1, 2, 3, and explicit `null` as distinct states. Identity includes concept/query/index/document. Repeated queries, indexes, and case-sensitive document IDs do not collide. |
| E | Rank comparison and pins | Compare baseline/candidate organic document ranks and graded metrics with judged coverage before pin placement. A pin creates no rating or metric gain; a separately entered numeric rating may count only at that document's organic rank. |
| F | Bounded deterministic tuning | Same data and options produce same settings/metrics with stable tie handling. Reject missing or negative-only train labels. Selection uses train judgments only; held-out validation is reported separately and cannot affect selection. Before/after results use the same split. With no validation split, say generalization was not evaluated. Report explicit-null unjudged labels separately from retrieved documents with no judgment; unjudged documents are not treated as zero. |
| G | Input/error safety | Bounded request sizes/passes/candidate counts; reject malformed fields, modes, non-finite or invalid weights/ratings; return controlled errors. Render user strings as text (no executable HTML/script). |
| H | Source data unchanged | Capture selected source index document count and stable sampled document hashes before and after workflow; they match. No create/update/delete/bulk call against the source index. |
| I | Existing retrieval regressions | Existing BM25, vector, hybrid, code, and Jira flows continue to work with their existing API contracts and result shapes. |
| J | Build and installed runtime | Build wheel; install into an isolated target/environment; invoke installed `es-rag-workbench --help`; start installed HTTP service; health and one complete concept flow succeed. |
| K | Real browser | Complete save, preview, grade, tune, and reload in a real desktop browser and narrow mobile viewport. No uncaught JS errors or horizontal overflow. Record screenshots or browser trace and browser/runtime versions. |

## Reporting rules

- Report each gate as `PASS`, `FAIL`, or `NOT RUN`, with the command/artifact and observed result.
- Identify whether Elasticsearch was live, the endpoint class (local test service), version, index, and before/after source-data fingerprints. Never include credentials.
- Keep fixture/mock results separate from live Elasticsearch results. A mock does not establish Elasticsearch DSL compatibility.
- Keep browser evidence separate from HTTP/API evidence. A browser page load alone does not prove the full workflow.
- Keep installed wheel behavior separate from running source-tree code.
- Do not claim a quality improvement from a tiny controlled fixture as a general retrieval improvement. Report query-level judged counts, coverage, nDCG@k, train/validation boundaries, and any tie behavior.
- For metadata filters, verify save/load preserves the selected values and that preview baseline, preview candidate, tune baseline/trials, and the run snapshot all use the same effective scope. A request-level preview override must be reported as such.
- State blocked gates as `NOT RUN` or `FAIL`; do not infer passing from a wrapper exit code if nested commands failed.

## Required report artifacts

1. `docs/concept-research.md`: dated primary-source research, design implications, implementation uses, and limitations.
2. This file: gate status, evidence locations, and limitations updated after the acceptance run.
3. Test/browser fixtures under `tests/` or `test/`, with safe isolated index naming and cleanup limited to fixtures created by the run.
4. A durable final run report under `build/` or `docs/`, including exact commands and independent evidence categories.

## Final acceptance status

Date: 2026-10-17. All mandatory gates A–K passed. The live HTTP/API suite passed 13/13 against Elasticsearch 9.5.5; the same suite passed 13/13 with the built wheel installed in an isolated environment. Full commands, hashes, browser results, metric boundaries, and artifact paths are in [`build/acceptance/QA-report.md`](../build/acceptance/QA-report.md). Screenshots are under `output/playwright/`.

The reference index `jira-grpc-issues-9-5-5` remained at 25 documents. The canonical all-document source fingerprint was `13c066665006ef9b0031afb468eaf1835461bdeed5644e836ed9dfba7722264c` both before and after the final source acceptance run. Only uniquely named test fixtures were created and removed.
