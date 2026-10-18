# Cycle 13 candidate-pool research

**Checked:** 2026-10-18  
**Model:** Runtime identity unverified; the available tool output did not expose it.  
**Scope:** Research-only review of the supplied Cycle 13 context, project documentation (`README.md`, `docs/concept-api.md`, and the pre-existing `docs/novice-retrieval-improvements-2026-10-18.md`), and current official Elastic and NIST/TREC sources. No application code, tests, SQLite/database, credentials, user corpus, or live Elasticsearch instance was accessed. No tests were run.

This note separates upstream facts from product-design inferences. The existing baseline is `v0.12.1` at commit `7ead654`. It does not repeat Cycle 11 information-need grouping or Cycle 12 same-split label suggestions.

## Question and recommendation

**Recommendation (design inference):** Multi-retriever candidate discovery is a valuable next direction because the concept evaluation workflow currently discovers its judgment candidates through BM25, while the general search workflow already exposes BM25, vector, and hybrid modes. A relevant document absent from the BM25 list cannot be judged there unless the user finds it elsewhere. This directly addresses the novice problem of knowing a topic but not knowing which omitted document to fetch. Existing title/passage lookup and exact-ID diagnosis address a different, already-supported case and should not be repeated.

Keep Cycle 13 bounded as a **candidate-discovery pool for one selected saved query**, separate from evaluation and tuning:

1. Collect a bounded top-K list from each of the already-supported BM25, dense-vector, and hybrid modes, with the same saved query, target index, and applicable filters.
2. Union by exact `(index, id)`. Show a single document row with each contributing mode and that mode's original rank. Keep exact saved query/document judgment identity; source rank is provenance, not an organic rank for the union.
3. Let the user judge this candidate set with existing judgment semantics. Do not automatically call pool membership relevant, treat unjudged as grade 0, alter the BM25 evaluation baseline, or feed these discovery results into tuning implicitly.
4. Treat any failed, timed-out, partial-shard, or unsupported mode as an incomplete pool. For the first slice, fail closed for judging: show which mode failed and do not present a partial union as a complete three-mode pool. A later design could deliberately support partial pools, but only with a persistent, unmistakable completeness state.

This is a **small-to-medium, single-query workflow slice**, not an evaluation redesign. Its usefulness can be shown by whether it surfaces documents the user can judge that were missing from the BM25 candidates; this does not establish a retrieval-quality gain. If the current UI/API cannot cleanly keep candidate discovery distinct from saved runs, a smaller first release is a BM25-plus-vector drawer for one query, with hybrid deferred until index/model readiness and completion handling are proven. That staging option is an inference, not an upstream requirement.

## Upstream facts

- Elastic documents retrievers as part of `_search`, added in 8.14 and generally available in 8.16. Its retriever API includes standard query retrieval, kNN retrieval, and an RRF retriever that combines multiple first-stage lists. This makes one-request hybrid search possible on compatible deployments; it does not show which Elasticsearch versions or mappings this project currently targets. [Retrievers overview](https://www.elastic.co/docs/solutions/search/retrievers-overview)
- Elastic describes hybrid search as combining full-text and vector retrieval in one request and recommends RRF for merging those ranked lists. The RRF API docs say its component retrievers run independently and their rankings are combined. This is a way to produce a hybrid list; it does not imply every hybrid result is distinct from the separate BM25/vector lists. [Hybrid search](https://www.elastic.co/docs/solutions/search/hybrid-search), [RRF reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)
- Elasticsearch kNN is approximate. `k` bounds final results, `num_candidates` bounds candidate consideration per shard, and filters can constrain eligible documents. A vector query needs a compatible vector field and query vector (or a configured query-vector builder). Thus vector mode may be unavailable for an index or incur embedding work, and a successful kNN response is not proof of exact nearest-neighbor recall. [Search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search), [kNN query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-knn-query)
- `_msearch` accepts multiple independent search bodies in NDJSON and returns a `responses` array whose entries can be normal search responses or error responses. Its concurrency controls govern how much work can run simultaneously. This can reduce client round trips for three mode requests, but it does not eliminate the backend work or remove per-mode failure handling. [Multi-search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-msearch)
- The search API defaults `allow_partial_search_results` to true; shard timeouts/failures can therefore yield partial results unless configured otherwise. Search responses expose timeout/shard status. A pool workflow must inspect each mode's response status rather than infer success from an HTTP 200 or a nonempty hit list. [Search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search)
- NIST describes traditional retrieval test collections as pools: only a sample of the corpus is judged for a topic. Its study warns that pools of fixed size become a smaller fraction of larger collections and may produce biased judgments when assumed complete. [NIST, “Bias and the Limits of Pooling for Large Collections”](https://www.nist.gov/publications/bias-and-limits-pooling-large-collections)
- TREC's overview describes combining top-ranked outputs from multiple submitted runs for human assessment, while also noting the concern that systems not represented in the pool may have highly ranked unjudged documents. This supports candidate discovery as a workflow pattern, not an exhaustive-relevance guarantee. [TREC-9 overview](https://trec.nist.gov/pubs/trec9/papers/overview_9.pdf)

## Product-design inferences

### Novice value

The interface can turn “I know the information need but cannot find the document to grade” into a guided choice: review candidates contributed by each retrieval mode, inspect where each came from, then apply existing human grades. Showing each contributing mode/rank can teach that retrieval strategies surface different candidates without asking a novice to compare incomparable raw scores. A mode label is provenance only; the pool's display order must not suggest a new ranking or relevance verdict.

### Scope and cost

At K candidates per mode, the raw candidate volume is at most 3K before deduplication (for example, K=20 means at most 60 hit records for one query). This bounds candidate review and response volume. Backend work is still three retrieval branches. `_msearch` is a reasonable transport choice when the existing mode implementations can each be expressed as bounded `_search` bodies; otherwise preserve existing mode code and make sequential calls. In either case, cap concurrency, apply one timeout policy, and report each mode's status. No cost or latency numbers can be inferred without representative indexes and load measurements.

For a stable pool, keep the index/query/filter context identical across modes, store the exact `(index, id)` identity, dedupe only on that key, and retain all mode/rank provenance. If the mode implementations use different query transformations, vector models, or filters, surface that context or do not claim a controlled comparison. Avoid adding per-document metric aggregation, tuning, automatic judgment migration, or corpus-wide indexing/vectorization to this first slice.

## Risks and design controls

- **Incomplete coverage / pool bias:** The selected modes and K define the pool; relevant documents can remain undiscovered. Never call it exhaustive, compute recall against it as if it were complete, or imply adding modes guarantees unbiased judgments.
- **Mode failure hidden by partial output:** Missing vector mapping/model, unsupported Elasticsearch version, timeout, shard failure, or one failed `_msearch` item can silently omit a source. Require every requested mode to pass before enabling judgment in the initial design. If partial pools are later allowed, label them partial persistently and preserve the failed-mode reason.
- **Context drift:** Different target index, filters, query text, or corpus state can make source provenance misleading. Bind all mode requests to the saved query and shared target/filter inputs; record enough context to identify the pool snapshot.
- **Duplicate and identity mistakes:** The same ID can exist in different indices. Dedupe by `(index, id)`, while the saved judgment remains attached to the exact query and document tuple. Preserve explicit-unjudged separately from grade 0.
- **Candidate order misread as quality:** The union interleaves hits from unrelated score scales. Do not sort or label the union as a fused ranking unless a separately defined ranking algorithm is intentionally used. A display grouped by first source / source rank is easier to explain.
- **Unintended tuning leakage:** Candidate discovery is not a new label source for training unless the user explicitly grades documents and the existing split policy assigns them. Preserve train-only tuning and separate validation.
- **Read-only boundary:** Discovery should issue only bounded searches and must not index embeddings, update source documents, or mutate the source index.

## Proposed pass/fail gates

These are design gates for a future implementation, not evidence that it has been built or tested.

1. **Discovery:** A fixture has a relevant target returned only by dense-vector or hybrid search, outside BM25's top K. The candidate pool displays it with its exact source mode and within-mode rank.
2. **Deduplication and identity:** A document returned by two or three modes appears once, retaining every source/rank. Identical IDs in different indices remain distinct. A grade attaches only to the exact saved query and `(index, id)`.
3. **Comparable request context:** All requested modes use the same saved query, index, filters, and bounded K. Request parameters and resulting provenance are inspectable in the saved pool evidence.
4. **Fail-closed completeness:** Missing vector capability, any per-mode error, shard failure, or timeout leaves the pool unavailable for judging and names the affected mode. A successful HTTP envelope with a failed subresponse cannot pass.
5. **Bounded and read-only:** K and total candidates have hard limits; no embedding/index writes or source mutations occur. Search payloads return only fields needed for review.
6. **Judgment semantics:** Unjudged is distinct from grade 0. Candidate-pool collection alone does not create a judgment, count as relevant, alter a run's evaluation result, or influence tuning.
7. **Novice clarity:** UI copy says these are candidates found by selected methods and that more relevant documents may exist outside the pool. It explains source mode/rank without claiming that the modes' scores are comparable.
8. **Evidence limits:** No release note, chart, or UI claims retrieval quality, recall, answer quality, or exhaustive relevance gains from pool size or from finding one alternate-mode document. Any future comparative retrieval claim requires a real representative human-judged query/document set, an explicit metric and cutoff, and an evaluation protocol that retains unjudged semantics.

## Evidence limits and research actions

The project facts above rely on the bounded source findings supplied for this assignment and the named documentation, not a fresh full repository audit. External research checked official Elastic API/reference pages and NIST/TREC sources on 2026-10-18. No runtime model identifier was available, no live Elasticsearch deployment or mappings were inspected, and no representative judgment set was reviewed. Therefore this note cannot establish deployment compatibility, vector readiness, actual latency/cost, pool coverage, statistical representativeness, or retrieval-quality improvement. No tests or runtime checks were run.
