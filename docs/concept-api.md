# Concept retrieval API contract

This contract adds a local, read-only concept retrieval and evaluation workflow to the existing workbench. It does not change the source Elasticsearch index. All routes accept and return JSON. Existing `/api/search`, `/api/evaluate`, and `/api/tune` contracts remain available.

## Shared concept object

```json
{
  "id": "optional-stable-id",
  "name": "Timeout recovery",
  "description": "Cases where a client recovers after a timeout",
  "aliases": ["timeout retry"],
  "related": [{"term": "backoff", "relation": "related", "weight": 1.4}],
  "excluded_terms": ["connect timeout"],
  "corpus": {
    "index": "existing-index",
    "title_field": "summary",
    "text_fields": ["summary", "description", "resolution"],
    "filter_fields": ["project", "status"]
  },
  "filters": [{"field": "status", "value": "Open"}],
  "settings": {
    "size": 10,
    "candidate_size": 50,
    "mode": "bm25",
    "concept_weight": 1.0,
    "related_weight": 1.0,
    "field_boosts": {"summary": 2.0, "description": 1.0}
  },
  "queries": [{"id": "q1", "query": "retry after request timeout", "split": "train"}]
}
```

`description` is indexed as a definition signal alongside the name and aliases. Excluded terms use phrase matching so a multiword exclusion does not remove documents that contain only one of its words. `related[].relation` is a user-defined label. Weights are bounded positive retrieval multipliers. `corpus.text_fields` is required; field names must exist in the selected index mapping. Text fields may be nested; the query builder uses their mapped nested path. `filters` are exact typed field/value pairs, stored with the concept and reused for tuning. `settings.mode` and tuning currently support `bm25`; unsupported modes are rejected instead of silently falling back. The optional vector-candidate route below is a separate discovery aid and does not change BM25 preview or tuning. `candidate_size` is the organic candidate pool inspected by the workbench; preview displays up to `size` organic hits plus explicit pins. A query split is `train` or `validation`. IDs are stable opaque strings.

## Routes

### `POST /api/corpus/schema`

Request: `{ "connection": { ...existing connection fields... }, "index": "existing-index" }`.

Returns `{ "index": string, "fields": [{"name": string, "type": string, "searchable": boolean, "filterable": boolean, "nested": boolean, "nested_path": string|null, "source_field": string}], "warnings": [], "warning_codes": [] }`. `source_field` maps a multi-field back to the original `_source` field. `searchable` respects mapping `index:false`; BM25 text choices include `text`, `match_only_text`, `search_as_you_type`, `keyword`, and `wildcard`. Exact metadata filters support keyword, integral and floating numeric, boolean, date, and IP mappings. Unsupported specialized mappings and alias type conflicts are reported through warnings/codes. This reads the existing `_mapping`; it never creates or modifies an index.

### `POST /api/concepts/list`

Request: `{}`. Returns `{ "concepts": [concept], "storage": "sqlite", "database": "local database path" }`. Database paths and credentials are not written into concept records or responses beyond this local status field.

### `POST /api/concepts/save`

Request: `{ "concept": concept }`. Returns `{ "concept": savedConcept }`; a missing `id` is assigned by the service. Saving the same ID updates that concept.

### `POST /api/concepts/preview`

Request: `{ "connection": {...}, "concept": concept, "query": "optional ad-hoc query", "query_id": "optional saved query ID", "filters": [{"field":"status","value":"Open"}] }`. If `filters` is omitted, saved `concept.filters` apply. If the property is present, it overrides saved filters; `[]` clears them for that preview. Tuning always uses saved concept filters.

At least `query` or `query_id` is required. A supplied `query_id` must resolve to a saved query; if both are supplied, their text must match. Returns `{ "run_id": string, "query": string, "effective_filters": [...], "baseline": resultSet, "candidate": resultSet, "comparison": [...], "warnings": [...], "warning_codes": [...] }`. A result set contains `hits`, `total`, `pool_count`, and the executed query description. Each hit includes `_index`, `_id`, `_score`, organic `rank`, `source`, `source_sha256`, `snippet`, `evidence`, and saved `judgment` (`rating`, `pinned`, `reason`) when it belongs to the selected saved query. Evidence entries have `field`, `source_field`, `source_path`, `term`, `kind`, `basis`, `status`, and their own source-literal `snippet`; `source_path` identifies the individual scalar source value (including array positions), so evidence never joins separate array elements to manufacture a phrase match. `basis: lexical` is a surface-text match and `status: candidate` does not claim a confirmed semantic relationship. Hit snippets are excerpts copied from original source fields; baseline snippets show original selected content even though they have no concept-match evidence. `comparison` reports organic baseline and candidate ranks per document. Explicit pins appear in candidate hits with `pinned: true` and `organic_rank: null` when outside the candidate pool; pins do not change organic rank metrics. Scores are Elasticsearch relevance scores, not probabilities. `warning_codes` are stable UI localization keys.

### `POST /api/concepts/information-need-preview`

Request: `{ "connection": {...}, "concept_id": "saved-concept-id", "query_id": "saved-query-id" }`. The server loads the authoritative saved concept from the configured local store, resolves `query_id` within that concept, and derives group membership from its saved `information_need` labels. Labels are canonicalized by collapsing/stripping whitespace and applying Python `casefold`; caller-supplied concept/query text, query arrays, settings, index, filters, and query DSL are not accepted. The selected query must have a nonblank label, and the resulting group must contain 2–10 saved queries; these bounds are checked before any Elasticsearch request.

Returns `{ "information_need": string, "split": "train" | "validation", "count": number, "status": "complete" | "partial", "results": [...], "failures": [...] }`. Each result is `{ "query_id": string, "query": string, "split": string, "preview": previewResponse }`, where `preview` has the ordinary `/api/concepts/preview` payload. Each saved query is executed independently with its exact saved ID/text, the saved concept settings/filters, and that query ID's judgments. Each successful result creates its own ordinary preview run record. A failure entry identifies the exact query ID/text/split and has an `error` message; failed queries are absent from `results` and are never represented as zero hits. `status` is `partial` when one or more members fail, otherwise `complete` (including a complete response whose individual previews returned zero hits). The route does not combine result sets, fuse or compare ranks/scores across variants, aggregate quality metrics, or write/update grades. Users continue to save judgments explicitly through `/api/concepts/judge`.

### `POST /api/concepts/vector-candidates`

Request: `{ "connection": {...}, "concept_id": "saved-concept-id", "query_id": "saved-query-id" }`. The server loads the persisted concept and query. Index, exact concept filters, result bound (`settings.size`, 1–50), vector field (`rag_embedding`), and the built-in E5 query embedding are server-derived; caller-supplied concept bodies, index, filters, query DSL, model, field, source fields, size, and pagination are not accepted. The saved target may be a concrete index or an Elasticsearch alias. For an alias, the service checks every concrete backing mapping before counting vectors, loading the query embedding, or searching: each must have an indexed 1024-dimensional float `dense_vector`; effective similarity must agree (an omitted float-vector similarity is treated as `cosine`); and declared `index_options` must agree exactly. Omitted `index_options` are treated as the server default, so an omitted setting and an explicit setting are conservatively considered different because their effective equivalence depends on Elasticsearch version/defaults. Missing or conflicting mappings fail with an actionable error; the service never chooses one target mapping. Count and search still address the saved alias so alias filters and read context apply. Returned hit `_index` values must be concrete names in the mapping target set; those exact concrete names are retained for judgment lookup and saves. The local model must already be loaded or cached; this route does not download it. Elasticsearch `_source` and response source include only mapping-resolved configured text fields and title field, not filter fields or other document properties. It does not vectorize documents or write Elasticsearch data, judgment rows, or preview/run evidence.

Returns `{ "concept_id": string, "query_id": string, "query": string, "index": string, "mode": "vector", "model": string, "field": "rag_embedding", "dimensions": number, "approximate": true, "exhaustive": false, "total": number, "candidates": [...] }`. Each candidate has `_index`, `_id`, original vector `_score`, within-vector `rank`, sanitized `source`, `source_sha256`, `snippet`, and the saved exact-query judgment or `{ "rating": null, "pinned": false, "reason": "" }`. The response is separate from BM25 preview/run objects. Vector ranks are provenance; vector scores are not comparable with BM25 scores, and approximate top-K candidates do not establish exhaustive relevance or retrieval-quality gains. The user must explicitly save any grade through `/api/concepts/judge`; collection alone never changes a judgment. Missing or incompatible mapping, no vector documents, embedding/search errors, timeouts, malformed responses, and any failed shard are errors with no partial candidate list.

### `POST /api/concepts/mode-comparison`

Request: `{ "connection": {...}, "concept_id": "saved-concept-id", "query_id": "saved-query-id" }`. The server loads the saved concept and query read-only. Query text, split, index/alias, concept filters, displayed result bound (`settings.size`), text fields, concept boosts, vector field, and local E5 model are derived from that saved concept; caller-supplied query text, filters, index, model, field, query DSL, and size are not accepted. It runs only the concept-applied BM25 candidate query and the existing E5 vector query. It does not run baseline BM25, hybrid/RRF, optimize settings, change judgments, or write a run record. It returns one `{ "concept_id", "query_id", "query", "split", "index", "settings_size", "effective_filters", "filters_fingerprint", "judgments_applied_to_current_filters", "metrics", "vector", "bm25", "limits" }` object. Both result sets use the same saved query, current saved filters, and `settings.size`; concrete `(_index,_id)` pairs are used to match documents to judgments, including when the saved target is an alias. Stale query judgments are excluded. A pin never adds a result or rank; an independent non-null rating remains a grade. `rating: 0` counts as a judged irrelevant document; `rating: null` is separately counted as explicit unjudged.

`metrics.concept_bm25` and `metrics.e5_vector` each contain `status` (`available`, `no_judgments`, or `no_positive_judgments`), `k`, `ndcg_at_k`, `judged_coverage_at_k`, `recall_of_judged_relevant_at_k`, `judged_count`, `positive_judged_count`, `relevant_found_at_k`, `retrieved_judged_count`, `unjudged_retrieved_count`, `explicit_unjudged_count`, and `stale_judgment_count`. nDCG uses the existing condensed judged-only formula: unknown documents are omitted, not assigned grade 0. If there are no current graded judgments or no positive grades, nDCG/known-relevant recall are `null`; coverage and counts remain available. Recall is only against human-rated positive documents. The split is reported for context; this endpoint compares one query and does not combine queries, train, or validate. `filters_fingerprint` identifies the canonical current filter snapshot. The labels are applied to those current filters, but the endpoint does not claim that the judgments were originally made with that filter snapshot.

The vector mode is approximate, non-exhaustive, and limited to at most `settings.size` candidates; `vector.total` is Elasticsearch's reported total for the filtered vector search and does not make the returned ranking exhaustive. BM25 is likewise bounded to `settings.size`. Neither mode's top-k metric is a corpus-wide quality guarantee or evidence that generated RAG answers improve. Missing/incompatible vector mapping, absent vectors, unavailable cached local model, timeouts, malformed or partial responses, and shard failures fail the whole request; no one-sided comparison or synthetic zero-hit result is returned. Embeddings are local-files-only for this endpoint. Elasticsearch and local concept/judgment/run data are not modified.

### `POST /api/concepts/mode-comparison-group`

Request: `{ "connection": {...}, "concept_id": "saved-concept-id", "query_id": "anchor-saved-query-id" }`. Only the saved concept and anchor ID are used; query text, group, index, filters, size, fields, model, and retrieval settings are never taken from caller overrides. The server normalizes saved `information_need` labels by collapsing whitespace and applying Python `casefold`, derives the matching group and split from the saved concept, and rejects missing/blank labels, groups outside 2–10 queries, or mixed splits before Elasticsearch access.

Each member gets a paired concept-applied BM25 and local E5 vector search using the saved alias, normalized saved filters, and saved `settings.size`. A per-query row is emitted only when both searches complete and pass response checks. Failures include query ID/text/split and error; `selected_count`, `completed_count`, `failed_count`, and `status` distinguish a full run from a partial run. Any member failure makes `aggregate` null. Safe complete pairs remain in `queries`; a failed or one-sided pair is never represented as zero or retained as a completed row. Per-query `metrics` have the C34 fields and semantics described above, joined by exact concrete `(_index,_id)` identity. Only current judgments for that exact saved query apply; rating 0 remains graded, null remains explicitly unjudged, stale judgments are excluded, and a pin supplies no rank.

On a complete run, `aggregate` reports a `mean` and `query_count` for each metric and mode. nDCG and known-positive recall include only queries with at least one current positive judgment; judged coverage includes only queries with at least one current graded judgment. A zero denominator yields `mean: null` and `query_count: 0`. Each query has equal weight. The endpoint reads the local concept/judgment store and Elasticsearch only; it creates no preview/run records, changes no grades or settings, and makes no LLM/provider call. The local E5 query embedding uses the existing local-files-only model path. Since it performs two searches per member, a group can issue up to twenty search requests.

The metric approach is guided by Elasticsearch's documented search-quality `rank_eval` API and its query/ratings relevance framing ([Rank Eval API](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval), [Rank Eval API operation](https://www.elastic.co/docs/api/doc/elasticsearch/v8/operation/operation-rank-eval), [relevance queries and ratings](https://www.elastic.co/search-labs/blog/elser-rag-search-for-relevance); references checked 2026-10-18). Generated-answer evaluation is a separate question, as illustrated by [Elastic's RAGAS evaluation discussion](https://www.elastic.co/search-labs/blog/elasticsearch-ragas-llm-app-evaluation). These sources describe evaluation concepts and do not demonstrate the quality of this feature or its results.

### `POST /api/concepts/document`

Request: `{ "connection": {...}, "index": "existing-index", "document_id": "id" }`. Fetches a document by exact index and ID for manual inspection. Returns `{ "document_index": string, "document_id": string, "source": object }`. This lets a user register a desired document missing from organic search and judge it using `/api/concepts/judge`. No document is written to Elasticsearch.

### `POST /api/concepts/locate-document`

Request: `{ "connection": {...}, "concept_id": string, "text": string }`. Looks for a document using words remembered from its title or body when the user does not know its ID. The server loads the saved concept and derives the index, title/text fields, nested paths, and displayed source fields from its validated configuration and current mapping. Caller-provided index, fields, query DSL, query-string syntax, size, and pagination are not accepted. The locator searches the deduplicated union of configured `corpus.text_fields` and the configured `title_field` when present, including older saved profiles where the title was stored separately. It deliberately omits the concept's evaluation filters and saved relevance query. It sends a fixed `size: 10`, `from: 0`, `track_total_hits: false` request; this caps returned candidates, not Elasticsearch's internal search work.

Returns `{ "index": string, "fields": string[], "candidates": [{ "document_index": string, "document_id": string, "score": number|null, "title": string, "excerpt": string|null, "excerpt_field": string|null, "matched_fields": string[], "excerpt_is_nested": boolean }] }` with at most ten candidates. `highlight.fields` is restricted to mapping-validated configured scalar fields, with one finite fragment per field; `matched_fields` follows configured field order and contains only fields for which Elasticsearch returned a non-empty highlight fragment. `excerpt` and `excerpt_field` come only from the first such fragment and are bounded for display. Elasticsearch highlight text is lexical context for the candidate, not proof of full relevance or answer quality. A candidate can have no scalar highlight, including when it matched through nested text or when the highlighter returned no fragment; absent highlight does not mean there is no candidate. Nested queries use mapping-derived paths and return the root document's exact `_index`/`_id`; nested text is not presented as a root excerpt or attributed to a particular nested child. Arbitrary source fields are not returned. A clean empty candidate list means only that this completed lookup returned no match in the configured fields. HTTP errors, missing/true `timed_out`, missing/failed shard status, or malformed hit lists are errors, never clean zero-hit results. Finding or selecting a candidate does not save a judgment; the user still explicitly loads and evaluates it against a saved query.

### `POST /api/concepts/judge`

Request: `{ "concept_id": string, "query_id": string, "document_index": string, "document_id": string, "rating": 0|1|2|3|null, "pinned": boolean, "reason": "optional text" }`. `query_id` must be a saved concept query. `null` rating means explicitly unjudged and is distinct from 0 (judged irrelevant). Returns `{ "judgment": ... }`. Identity is the exact concept/query/index/document tuple. A pin controls placement only; an independent non-null grade still counts at the document's organic rank.

### `POST /api/concepts/tune`

Request: `{ "connection": {...}, "concept": concept, "passes": 2 }`. Returns `{ "run_id": string, "effective_filters": [...], "baseline": trainMetrics, "tuned": trainMetrics, "settings": settings, "train": {"baseline": trainMetrics, "tuned": trainMetrics}, "validation": {"baseline": metrics, "tuned": metrics}|null, "judged_count": number, "explicit_unjudged_count": number, "unjudged_retrieved_count": number, "pinned_count": number, "warnings": [...], "warning_codes": [...] }`. Baseline and tuned top-level metrics are both training split metrics. Tuning is deterministic and bounded, uses only training judgments to choose settings, and requires at least one positive train grade. It evaluates validation judgments separately when present. If validation judgments are absent the response states that generalization has not been evaluated. nDCG uses the condensed judged-only organic ranking; unknown documents are omitted, not assigned grade 0. Judged coverage, known-relevant recall, explicit null-grade rows, and unjudged organic results are reported separately. A pin alone creates no relevance grade; a document with an independent grade retains its organic rank in metrics.

### `POST /api/concepts/runs`

Request: `{ "concept_id": "optional-id", "limit": 50 }`. Returns `{ "runs": [...] }` with run ID, concept ID, timestamp, kind, query, settings, metrics, safe input/output snapshots (concept and query/judgment inputs plus organic index/ID/ranks/source hashes), and reproducibility metadata (concept/query/judgment/filter fingerprints, concrete index UUIDs when readable, and mapping fingerprint). If index UUID read is denied or unsupported, a warning code states this limitation. Snapshots contain no source-document bodies or credentials. Judgments retain a fingerprint of their exact saved query text; changing or removing that query makes its old judgments stale and they are excluded from preview/tuning until rejudged.

## Grading and metric rules

Ratings use a 0–3 graded relevance scale; null means not yet judged. Metrics use only non-null ratings. A pin alone creates no relevance grade; an independently graded pinned document remains graded. Report nDCG@k, judged coverage, and known-relevant recall per query and aggregate. Tuning must not imply that unjudged documents are irrelevant. With no validation judgments, label results training-only and avoid claims of generalization.

The local SQLite database path is selected by `ES_RAG_CONCEPT_DB`; otherwise the service uses its documented user-local default. Connection credentials remain request-scoped and are never persisted.
