# Cycle 39 private knowledge evaluation research

**Checked:** 2026-10-18
**Scope:** semantic context for a local FTS5 preview and human document ratings. This note does not validate implementation quality or a live runtime.

## Source facts

- SQLite's FTS5 reference defines the built-in `bm25()` function as a lower-is-better ranking score: better matches have numerically smaller values. The score depends on the FTS table's corpus statistics, so values from distinct tables or corpus states should not be treated as a shared scale. See the [SQLite FTS5 reference](https://www.sqlite.org/fts5.html).
- Elasticsearch's Rank Eval API evaluates ranked search results against manually supplied ratings. Its request supports rated document IDs per query and ranking metrics including DCG/nDCG. It is an evaluation API, not proof that a particular evaluation set represents production use. See [Elasticsearch Rank Eval](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval) and the [Rank Eval API operation](https://www.elastic.co/docs/api/doc/elasticsearch/v8/operation/operation-rank-eval).

## Product design inference

The C39 local preview uses SQLite FTS5 rather than Elasticsearch. Showing its BM25 score as a lower-is-better local rank cue is consistent with SQLite's documented semantics, while comparing its numeric values with Elasticsearch scores would be misleading. Human ratings can support descriptive metrics for the selected saved query and current private corpus. They do not demonstrate corpus-wide quality, downstream answer quality, representativeness, or generalization to other queries.

For the expanded local result set, the saved excluded terms are applied as literal document exclusions; the baseline remains the exact saved-query result set. This is a C39 product rule and does not claim to reproduce Elasticsearch filters or exclusion-query behavior.

The feature therefore keeps baseline and expanded local rankings distinct, binds ratings to saved query and document fingerprints, and presents split only as context. Current non-null ratings are the metric inputs; unjudged documents are not silently converted to grade zero. This is a product-scope choice and not a claim that the chosen metrics are statistically sufficient.

## Evidence boundary

These sources describe SQLite and Elasticsearch APIs. They are not evidence that C39's code, UI, metrics, authentication boundary, or retrieval results are correct. Repository acceptance evidence is recorded separately in [Cycle 39 acceptance](cycle39-acceptance.md). Any browser run with intercepted/mock API responses is UI behavior evidence only, not backend API or provider evidence.

Runtime model identity: **UNVERIFIED** in this research run.
