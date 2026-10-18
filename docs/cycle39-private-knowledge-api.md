# Cycle 39: private knowledge concept preview and judgments

Cycle 39 adds a local lexical preview for one saved concept query and local human ratings for private knowledge documents. These routes use the authenticated account's private SQLite state database. They do not call Elasticsearch, create vectors, or use the Elasticsearch concept judgment/tuning tables.

## Authentication and account scope

Both routes are authenticated POST JSON requests. The existing session, same-origin, CSRF, loopback, and `concepts.owner_scope` checks apply. The server resolves the concept from the caller's saved concept store and the knowledge corpus from that same account's state database. Request bodies cannot select an owner, corpus, index, filters, query text, documents, DSL, or credentials. Unknown and foreign concept/document identifiers are not resolved from another account's database.

## `POST /api/knowledge/concept-preview`

Request contains exactly:

```json
{"concept_id":"saved-concept-id","query_id":"saved-query-id"}
```

The server loads the authoritative saved concept and exact saved query. The baseline search tokenizes that saved query into literal Unicode word terms and matches those terms as quoted FTS5 terms with OR semantics. The expanded search adds literal terms from the saved concept name, description, and aliases when `settings.concept_weight` is greater than zero, and saved related terms when `settings.related_weight` and the related-term weight are greater than zero. Tokens that appear in saved excluded terms are omitted from the expansion. In addition, the expanded result set excludes any document containing a saved excluded term as a contiguous, case-insensitive Unicode token sequence in its content, title, or source label. This filtering is applied before document deduplication, totals, and the 20-hit cap. Exclusion does not rewrite the baseline saved query. FTS operators are never accepted from these strings; exclusions are matched as token sequences in application code.

The local FTS5 BM25 ranking uses content/title/source-label column weights 1.0/3.0/1.5. Each baseline or expanded FTS search is limited to 200 unique literal terms. If either search exceeds the cap, the request returns an error rather than silently omitting terms. Related and concept weights only decide whether their terms enter the expansion; local search does not reproduce Elasticsearch's numeric weighting, field boosts, filters, or scoring. Results are deduplicated to one row per document using the best chunk score, ordered by ascending BM25 score and then stable document and chunk IDs. Each result set is capped at 20 documents; `total` is the number of matching documents before that cap.

Response shape:

```json
{
  "concept_id":"saved-concept-id",
  "query_id":"saved-query-id",
  "query":"saved query text",
  "split":"train",
  "corpus_fingerprint":"sha256-hex",
  "baseline":{"total":0,"hits":[{"document_id":"...","title":"...","source_label":"...","chunk_id":"...","excerpt":"...","score":-1.0,"rank":1,"matched_groups":["saved_query"],"judgment":{"rating":null,"stale":false}}]},
  "expanded":{"total":0,"hits":[]},
  "metrics":{"baseline":{"k":20,"ndcg_at_k":0.0,"judged_coverage":0.0,"known_positive_recall":0.0,"judged_count":0,"positive_count":0,"unjudged_count":0,"stale_count":0,"source_counts":{}},"expanded":{}},
  "weight_behavior":{"concept_weight":1.0,"concept_expression_count":3,"concept_expressions_included":true,"related_weight":1.0,"related_terms_total":0,"related_terms_included":0,"numeric_values_affect_ranking":false},
  "limits":["..."]
}
```

`weight_behavior` is additive and backward-compatible. Its values are computed from the same authoritative saved concept used for the preview. Expression count is the saved name, non-empty description, and aliases; related inclusion counts saved related entries eligible under both the global and per-entry positive-weight gates. Weights only govern local expansion eligibility: their numeric magnitude does not affect local scores or ranks. This local SQLite workflow remains separate from Elasticsearch-backed numeric boosts.

Cycle 41 adds `matched_groups` to every hit. Its values are fixed IDs: `saved_query`, `concept_expressions`, and `related_terms`. Baseline hits use `saved_query`. Expanded hits list each eligible literal group with at least one token matching that hit’s exact representative FTS chunk row (indexed content, title, or source label); excluded-term tokens are removed from expansion groups. These cues do not indicate which term caused rank, do not alter retrieval, and do not establish semantic relevance. The UI maps only known IDs to localized labels. See the [Cycle 41 match evidence research note](cycle41-local-match-evidence-research-2026-10-18.md).

Each hit's `judgment` is either the current local rating or a stale rating marker for the same document. Rating `0` is a current explicit judgment and differs from `null` (unjudged). `source_counts` maps source labels to `judged`, `positive`, `unjudged`, and `stale` judgment counts. Metrics use current, non-null human ratings only. nDCG uses the condensed judged-only ranking: unjudged hits are omitted, then judged hits are ranked consecutively from position one. Judged coverage and known-positive recall use the full returned top-k ranking; known-positive recall is the fraction of all current positive judgments for this query present there. Unjudged results are not assigned grade zero.

The corpus fingerprint is a SHA-256 digest over sorted stable document IDs and document fingerprints plus the local retrieval recipe (FTS tokenizer, chunking/version, and BM25 column weights). It does not expose content. `split` is returned only as saved-query context: each preview evaluates one selected query and does not demonstrate split-level generalization or optimize weights. BM25 scores are lower-is-better, are not probabilities, and are not comparable with Elasticsearch scores.

## `POST /api/knowledge/judge`

Request contains exactly:

```json
{"concept_id":"saved-concept-id","query_id":"saved-query-id","document_id":"local-document-id","rating":2}
```

`rating` must be an integer from 0 through 3, or explicit `null` to preserve an unjudged entry. The saved concept and query must exist, and `document_id` must currently belong to the caller's private knowledge database. The route returns only judgment identifiers, rating, stale state, and update time; it does not return document content.

Judgments are kept in a dedicated local `knowledge_judgments` table, keyed by concept, query, and stable local document ID. Each saved rating binds to the saved-query fingerprint and a fingerprint of document content plus title/source metadata. A changed saved query or edited document makes its prior rating stale; a deleted document remains as a stale rating with its source-label snapshot. Stale ratings remain inspectable in preview hits when applicable but are excluded from metrics. Rejudging saves a fresh fingerprint. The table is account-scoped because it resides in the owner-resolved state database.

## Relationship to Elasticsearch preview/tuning

These routes are a private local-knowledge workflow. Existing `/api/concepts/preview` and `/api/concepts/tune` retain their Elasticsearch behavior and data model. Local FTS5 results and ratings must not be interpreted as Elasticsearch index results, ES grades, automated weight tuning, or evidence of retrieval quality beyond the selected local query and current local judgments.
