# Cycle 44: Positive target misses research

**Checked:** 2026-10-18. URLs below were opened live on this date. The Elasticsearch pages are rolling documentation and do not expose a publication/update date in the page content; NIST SP 1348 is dated March 2026. **Model identity:** unverified; it was not exposed in the available tool metadata.

## Recommendation

Prioritize a small, read-only view after a saved-concept tuning run: show, separately for train and validation, the human-judged positive documents that are absent from each query's *stored tuned top-K*. Use the visible label **“Judged positive documents not in this saved top-K”**. For every row, preserve the identity `(query_id, index, document_id)` and show its positive grade. Give each split a per-query count and an expandable list; identify the saved snapshot and K so the user knows exactly what was compared.

This is a set comparison over existing evidence, not a new retrieval evaluation. For each query `q`, compare its stored positive judgments (project grades 1–3) with its stored top-K result identities and display the set difference. Do not combine train and validation. Do not re-run a live query to construct the comparison.

## Source facts

| Primary source, live check, and date | What it supports | What it does not establish |
| --- | --- | --- |
| [Elasticsearch Ranking evaluation guide](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval), checked live 2026-10-18; rolling page, no page date shown. | Elastic frames ratings as relevance to a search request and says a separate ratings set is needed per test query, based on the user's information need. The example and API use `_index`, `_id`, and `rating`; ratings may use a user-defined integer scale. The response is keyed by query ID. | It does not say a local workbench's judgments are complete, or that its set of positive judgments covers every relevant document in an index. It does not prescribe the proposed UI. |
| [Elasticsearch Rank Eval API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-rank-eval), checked live 2026-10-18; page states generally available, added in 6.2.0; no page date shown. | Defines ratings with `_index`, `_id`, and request-specific `rating`; `k` is the per-query result limit. Its `unrated_docs` response lists documents that *were returned* for a query but had no rating. For Precision@K, `ignore_unlabeled=false` counts unlabeled retrieved documents as irrelevant; `true` ignores them. | `unrated_docs` is not a list of judged-positive documents missing from results: it points in the opposite direction. API metric defaults do not define this product's null/unjudged semantics. |
| [NIST SP 1348, The 34th Text REtrieval Conference (TREC 2025)](https://doi.org/10.6028/NIST.SP.1348), March 2026; approved 2026-03-19; checked live 2026-10-18. | NIST distinguishes the user's information-need topic from the query given to a system; relevance judgments are topic-specific and may be graded. It explains that judgments are often sampled through pooling, that complete judgments over large collections are infeasible, and that traditional pooled evaluation often treats unjudged documents as nonrelevant under its own assumptions. It also notes pooling can miss relevant documents and become biased when shallow. | TREC's pooled-evaluation convention is not a product rule for this workbench. The report must not map absent/null judgments to grade 0, infer all relevant documents, or claim complete recall. |
| [TREC 2025 RAG Track overview](https://trec.nist.gov/pubs/trec34/papers/Overview_rag.pdf), dated 2026-03-10 in the paper header; checked live 2026-10-18. | The track separates retrieval, generation, RAG, and relevance-judgment tasks; its RAG evaluation also assesses answer completeness and whether citations support claims. | A retrieval-only comparison of judged documents and stored top-K results does not measure generated-answer correctness, citation support, or end-to-end RAG quality. |

## Product-design inference and label boundary

- The exact query-specific key follows Elastic's per-request rating model. Use the full `(query_id, index, document_id)` key on both sides of the comparison; do not deduplicate by document ID alone or transfer a judgment between queries.
- Based on the project's supplied data contract, treat grade `0` as an explicit human negative, grades `1–3` as human-positive, and `null`/unjudged as unknown. This is the project's distinction, not an Elastic or TREC requirement. Only grades `1–3` belong in this positive-target list. Keep grade `0` and null/unjudged out of that set, and never convert null/unjudged to `0` because TREC metrics sometimes make that assumption.
- Compare against the exact persisted tuned top-K snapshot for the run and split. Define “not in top-K” only as “this judged identity is absent from that saved result list.” It does not mean the document is absent from the index, unreachable by another query, or absent from the corpus.
- Show train and validation in separate sections, with per-query counts and exact identities. A split-level total can be a navigation aid, but should not be presented as statistical evidence or a generalization claim.
- Keep the comparison attached to its saved concept/tuning run, snapshot identifier, and K. If the judgment set or retrieval snapshot changes, make that a new comparison rather than silently recomputing the old one.

## Limitations and evidence boundary

The list can only expose positive judgments present in the saved judgment snapshot. It cannot reveal relevant documents that were never judged, establish corpus absence, or provide complete recall. A difference count is descriptive for this query set and snapshot; it does not establish statistical significance or production quality. It says nothing by itself about answer quality or evidence support in a generated RAG response.

No codebase-memory graph was used; the project context in this note is limited to the coordinator-provided summary. No code or tests were changed or run for this research.
