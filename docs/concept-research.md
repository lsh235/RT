# Concept retrieval research

Research date: 2026-10-17. Documentation pages below were checked on this date. The project remains a local Elasticsearch workbench; this research does not authorize corpus export or source-index mutation.

## Elasticsearch query and evidence design

### Bool queries, named clauses, and evidence

Elastic's [bool query reference](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-bool-query) documents `must`, `filter`, `should`, and `must_not` as composable query clauses. `should` is optional by default when a bool has a `must` or `filter`, so an expansion intended to affect matching must explicitly set `minimum_should_match` or remain a score-only optional expansion. The [Search API reference](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html) supports query `_name` labels and `include_named_queries_score`; it also warns this reruns named queries against returned hits and can add substantial cost for expensive clauses.

- **Design implication:** represent the baseline separately from concept expansion; put exclusions in `must_not`, and make inclusion semantics explicit. Give bounded alias/related clauses deterministic names to provide lexical match evidence per hit.
- **Implementation use:** build an explainable query tree with stable names such as `concept_alias_0` and `related_backoff`; return matched clause names alongside original source-field excerpts. Do not use raw query text as a field name or query name.
- **Boundary:** named clause matches prove that a query clause matched; they do not establish a semantic relation, causation, or correctness. Avoid enabling expensive per-hit score recomputation beyond the returned result window.

### Nested fields and generic mappings

The [nested query reference](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-nested-query.html) states that nested objects are searched as separate documents and matching nested objects return the root parent. Dot notation alone does not traverse a nested boundary; `nested` queries require a path. Elastic specifically warns that an inner `must_not` can still allow a parent when another nested child matches; excluding parents requires an outer `must_not` around the nested query.

- **Design implication:** mapping discovery must preserve field type and nested ancestry. Generic field choices should be checked against mappings before building queries. A negative term targeting nested content needs the nested path and outer exclusion shape.
- **Implementation use:** use a fixture index with both ordinary text fields and a nested field, then exercise nested searches and exclusions. Surface mapping mismatch as a controlled error/warning rather than silently dropping a field.
- **Boundary:** mapping metadata indicates field capabilities, not that the values contain useful text or that a chosen field is semantically appropriate.

### Highlighted snippets

Elastic's [highlighting guide](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting) describes highlights as matching fragments extracted from fields, using `_source` when a field is not separately stored. It cautions that highlighters do not always reflect complex Boolean logic and can highlight terms that do not correspond to a complete matching path.

- **Design implication:** present snippets as source excerpts and match details as lexical evidence, not as proof that every displayed word independently satisfied the full query. Escape highlight markup before rendering user/document values.
- **Implementation use:** return snippets only from selected source fields and cap excerpt length/number; keep a plain-text excerpt available if parsing highlighter tags is unsafe.
- **Boundary:** a snippet is an explanation aid, not a faithful full Boolean explanation, nor a semantic interpretation.

### Search-time synonyms versus per-concept expansion

Elastic's [search-time synonym guide](https://www.elastic.co/docs/solutions/search/full-text/search-with-synonyms) recommends the `synonym_graph` filter for search analyzers and explains that synonym sets and analyzer configuration are index/search configuration. Its [search analyzer reference](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/search-analyzer) describes a separate analyzer as a field mapping option.

- **Design implication:** keep a user-editable concept's aliases and related terms request-local in the workbench query. This gives preview, tuning, and rollback without changing an existing index mapping or shared synonym set.
- **Implementation use:** explicit query expansion can be tested and attributed term-by-term without requiring index administration. Search-time synonyms remain an optional future integration when the user explicitly chooses centrally managed analyzer behavior.
- **Boundary:** custom synonym analyzers are not available on arbitrary existing indices, may alter searches for all users of a field, and need analyzer testing. Do not mutate mappings or synonym sets as a side effect of concept authoring.

### Ranking evaluation and RRF

Elastic's [ranking evaluation API](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval) evaluates supplied search requests against manually rated documents and supports integer ratings, including fine-grained scales and discounted cumulative gain. Its examples identify ratings by `_index` and `_id`. Elastic's [RRF reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) defines fusion using ranks, with a `rank_constant` (default 60) and a result window; it does not require raw score scales to match.

- **Design implication:** preserve exact index/document identity, evaluate each query separately, and report graded nDCG with judged coverage. A pin is a placement instruction only: it creates neither a grade nor an organic rank. If the user separately assigns a numeric grade, that grade may score the document at its original organic rank when it was retrieved organically.
- **Implementation use:** baseline/candidate comparison reports organic ranks and graded metric changes before any pin placement. Explicit pins are a separate result-placement signal and never create metric gains; independently entered numeric grades are evaluated at the document's organic rank only. Any future hybrid fusion can use RRF when component scores have incompatible scales.
- **Boundary:** Elasticsearch's rank-eval API requires the caller to define query and ratings; a metric does not supply ground truth or establish generalization. Do not assume unspecified/unjudged documents are irrelevant. The workbench's `null` unjudged state therefore stays outside the rated set and is counted separately. RRF availability/behavior can vary by Elasticsearch version; this concept workflow currently specifies BM25.

## Relevance judgments and graded metrics

NIST's [TREC relevance-judgment documentation](https://trec.nist.gov/data/reljudge_eng.html) defines relevance judgments as query-specific qrels tied to a collection and notes that its historical judgments were binary and collection-specific. Elastic's rank-evaluation API separately supports integer graded ratings. These sources support keeping judgments attached to an exact query and document identity; neither source supports treating an unjudged item as an observed negative.

- **Design implication:** record `0`, `1`, `2`, `3`, and `null` distinctly; key by concept, query, index, and exact document ID. Pins are independent of numeric grades; a pinned, unrated document contributes no grade. Report judged coverage because metrics over sparse labels only describe the judged subset.
- **Implementation use:** calculate nDCG@k over judged documents for each query and then aggregate, with explicit query-level counts; keep train and validation judgments disjoint for tuning/assessment.
- **Boundary:** user judgments are the workbench's observed labels, not objective truth. Small or selectively judged sets can be biased. A gain on training judgments is not evidence of held-out quality; absent held-out labels, state that generalization was not evaluated.

## Optional LangChain query expansion

LangChain's current API documents [`MultiQueryRetriever`](https://reference.langchain.com/python/langchain-classic/retrievers/multi_query/MultiQueryRetriever) as using an LLM to create multiple queries, retrieving for each, then returning a unique union. Its [retriever interface](https://reference.langchain.com/python/langchain-core/tools/retriever) is a general abstraction that can wrap different retrieval backends.

- **Design implication:** query rewriting is one possible expansion strategy, not a requirement for editable concepts or transparent lexical matches. Deterministic aliases and typed related terms are easier to inspect, persist, and test in this workbench.
- **Implementation use:** treat LLM-generated query variants as a future optional adapter behind the same preview/evaluation interface, with original query retained and generated variants visible.
- **Boundary:** an LLM adds provider credentials, external data-flow, nondeterminism, latency, and dependency/version surface. Do not add LangChain or transmit private Jira/corpus text as part of this release without separate explicit user opt-in.

## Source-version caveat

Elastic reference links target their current documentation as accessed 2026-10-17, not a pinned server version. The active endpoint's Elasticsearch version must be recorded during live acceptance. A live capability or DSL smoke is required before asserting compatibility. LangChain API links target current reference docs; no LangChain dependency is needed for the specified deterministic concept workflow.
