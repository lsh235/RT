# Cycle 40: local weight semantics research (2026-10-18)

## Source

SQLite FTS5 documentation: https://www.sqlite.org/fts5.html (checked 2026-10-18). The `bm25()` function accepts weights for FTS table columns. Its documented scoring is corpus-dependent and returns lower values for better matches. It does not define per-query-term numeric boosts.

## Product decision and inference

The local private-knowledge preview keeps its existing FTS5 ranking unchanged. Saved concept and related weights remain eligibility gates for adding their term groups: a positive value includes eligible expressions and zero excludes them. The numeric magnitude does not alter local ranking. This is a product decision based on the distinction between FTS5's documented column weights and this application's local query construction; it is not evidence that the explanation improves retrieval quality.

Numeric boosts continue to have meaning in the separate Elasticsearch-backed workflow. Local results come from the account's private SQLite corpus, which may differ from the Elasticsearch corpus, so that workflow's results do not represent this private library.

## Limitations

The cited documentation describes SQLite FTS5 semantics, not the quality of this application's queries, its corpora, or a comparison with Elasticsearch. No user quality improvement or ranking-quality claim is made.
