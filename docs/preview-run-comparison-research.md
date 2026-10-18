# Elasticsearch preview and run comparison research

**Checked:** 2026-10-18

This note is research context for a novice workflow that compares two saved historical preview runs. It is not validation of this workbench's stored-run schema, fingerprints, or comparison implementation.

## Primary-source facts

- [Elasticsearch ranking evaluation](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval) accepts a set of search requests, per-query document ratings, and a metric definition. Metric parameters include the cutoff `k`, relevance threshold, and (for precision) whether unlabeled retrieved documents are ignored or counted as irrelevant. The response contains an overall score, per-request details, evaluated hits with ratings, unrated document IDs, metric details, and possible request failures. Each query needs its own ratings because relevance is specific to the query's information need.
- [Elasticsearch point-in-time API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-open-point-in-time) describes PIT as a lightweight view of index data at the time it is opened. Reusing a PIT across requests avoids refreshes making pages or repeated searches inconsistent. PIT IDs can change between searches; the latest ID should be reused. Keeping old segments for open PITs consumes disk and file handles, and a PIT does not prevent its index from being deleted.
- [Elasticsearch search pagination guidance](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/paginate-search-results) says a refresh between `search_after` requests can change result ordering and recommends a PIT to preserve the index state for that multi-request search. It also recommends a unique tie-breaker when PIT is unavailable to avoid missed or duplicated hits during pagination.

## Implementation context and product inference

The comparison is restricted to two saved preview runs. It enables a descriptive comparison only when query, effective filters, mapping fingerprint, index UUID, search definition, cutoff, and saved baseline/source-hash evidence match. Concept settings may intentionally differ between runs. If required comparison evidence is missing or mismatched, the UI suppresses deltas rather than treating the runs as directly comparable. Any shown rank movement or delta describes the stored results; it is not a statistical-significance claim or a relevance verdict beyond saved judgments.

This design reflects Elasticsearch's need for query-specific ratings, explicit metric/cutoff policy, and a consistent index view. It does not rerun a historical preview or use a newly evaluated `_rank_eval` response as proof that two saved runs used the same data.

## Limits

PIT offers a temporary consistent view for searches, not a durable historical dataset identity; it expires and has resource costs. A saved top-k result list, query text, ratings, mapping fingerprint, index UUID, and source hashes can explain what was observed, but without a complete corpus snapshot or retained evaluation-time view they cannot prove the whole index was immutable between two runs. `_rank_eval` scores depend on its selected metric, cutoff, threshold, and treatment of unlabeled documents. Small or sparse human judgments do not establish broad relevance or statistical significance, and retrieval metrics do not establish downstream RAG answer quality.
