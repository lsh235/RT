# Cycle 14 research: vector compatibility for index aliases

**Date:** 2026-10-18
**Scope:** Elasticsearch index aliases used as the saved corpus target for vector search. This note is research only; no production code or tests were changed or run.

## Findings

### Facts from official Elasticsearch sources

- An index alias can point to one or more indices, and most Elasticsearch APIs accept an alias in place of an index. The Get mapping endpoint is `GET /{index}/_mapping`; its `index` path parameter explicitly accepts indices and aliases. For a mapping request through an alias, Elasticsearch returns the mapping for each index to which that alias applies. The response therefore uses concrete index names as keys, rather than guaranteeing the request alias as a key. [Aliases](https://www.elastic.co/guide/en/elasticsearch/reference/current/aliases.html), [Get mapping API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-indices-get-mapping), [alias mapping disclosure behavior](https://www.elastic.co/guide/en/elasticsearch/reference/current/security-limitations.html). Accessed 2026-10-18.
- The search API also accepts aliases. Each returned hit has an `_index` value, documented as the name of the index containing that document. For a search through a multi-index alias, this is the concrete index identity of the hit, not the alias used in the request. [Search API response](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html). Accessed 2026-10-18.
- Dense vector mappings expose compatibility-relevant properties including `dims`, `element_type`, `index`, and (when indexed) `similarity`; the `index_options` configure the vector search algorithm. The query vector must have the same number of dimensions as the vector field being searched. [Dense vector field type](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector), [Search API](https://www.elastic.co/guide/en/elasticsearch/reference/current/search-search.html). Accessed 2026-10-18.
- The field capabilities API can query aliases and reports indices where a field has a particular type family, along with conflict-related information. It is designed for field capabilities, not a full per-index dense-vector mapping comparison. [Field capabilities API](https://www.elastic.co/docs/api/doc/elasticsearch/v8/operation/operation-field-caps). Accessed 2026-10-18.

### Repository facts

At baseline `b6e33a537c29881c97c8d86b1f9eb8873742a0fa` (`v0.13.0`):

- `es_rag_tuner/retrieval.py::vector_mapping()` reads only `response[index]`, where `index` is the user-supplied target. That works when the response key matches a concrete index, but it assumes the mapping response key for an alias equals the alias name.
- `es_rag_tuner/concepts.py::corpus_schema()` already merges all mapping response values and explicitly accounts for aliases spanning indices.
- `vector_candidates()` uses the saved corpus target to retrieve mappings, then rejects every hit whose `_index` differs from that saved target. The response hit identity check therefore treats a valid concrete index returned for an alias as a mismatch.
- `_connect()` in `es_rag_tuner/server.py` also consumes `vector_mapping()` and may conclude that an alias has no usable vector mapping.
- Judgment identity is stored/read as `(document_index, document_id)`. For alias search, the concrete hit `_index` is the appropriate document index component and must remain attached to the candidate and judgment lookup/save path.

### Product inference and bounded recommendation

The current assumptions are incorrect for aliases: the alias may not be a key in the mapping response, and hit `_index` is expected to be a concrete backing index. Consequently, otherwise valid alias selection can fail before search or during hit validation. This conclusion combines the official response semantics above with the checked repository behavior.

Smallest bounded Cycle 14 patch:

1. Make `vector_mapping()` inspect all mapping objects returned by the mapping request, rather than indexing only `response[index]`.
2. Accept an alias only when every resolved target has a `rag_embedding` dense-vector field usable by the current kNN request and the targets agree on the effective compatibility settings. At minimum validate equal `dims` matching the configured model dimension, `index` enabled, and compatible `element_type` and `similarity`; conservatively require equal effective `index_options` as well. Treat a missing field, non-dense-vector field, disabled vector indexing, or disagreement as an explicit actionable error. Do not silently select one target's mapping.
3. In `vector_candidates()`, retain each hit's concrete `_index` and use `(concrete _index, _id)` for judgment identity. Do not require concrete `_index == saved alias`. Preserve the existing exact concrete-index check when the configured target is a concrete index; this can be implemented by resolving the requested target set from the mapping response (or by returning resolved target names internally with the mapping) and checking hits belong to that set.
4. Leave other alias semantics (such as alias filters/routing and candidate-pool policy) outside this compatibility patch.

The exact set of mapping attributes to compare is an implementation policy inferred from the present query and Elasticsearch vector-field semantics; Elastic documents the individual parameters but does not prescribe an application-specific “compatible alias” predicate. Comparing every mapping option byte-for-byte may be overly strict when omitted defaults vary by Elasticsearch version, so normalize known defaults or compare the parameters that affect query validity and score interpretation.

## Synthetic acceptance cases for Cycle 14

These are proposed test cases, not tests run in this research task:

1. **Single-target alias:** mapping response is keyed by the concrete index, with a compatible `rag_embedding`; alias selection succeeds, and vector mapping is recognized by both candidate search and connection health logic.
2. **Multi-target compatible alias:** two concrete response keys each have compatible `rag_embedding` mappings with the same effective dimensions, element type, indexed state, similarity, and relevant index options; selection proceeds.
3. **Inconsistent/missing vector mappings:** reject an alias if one target lacks `rag_embedding`, has another type, dimensions or effective query semantics disagree, or has vector indexing disabled. Assert a clear error and no arbitrary mapping selection.
4. **Concrete hit and judgment identity:** a search requested through alias `docs` returns a hit with `_index: docs-000002`; candidate output reports that concrete index, and judgment lookup/save identity uses `(docs-000002, _id)`. A hit outside the resolved target set is rejected. For a concrete target `docs-000002`, retain concrete-index validation.

## Evidence boundary

No live Elasticsearch cluster, user database, corpus, or credentials were inspected. No tests were run. Source review used the repository baseline noted above; official documentation was accessed on 2026-10-18. Runtime/model identity was not exposed to this research agent and is unverified. The codebase-memory MCP tools were unavailable in this session, so this note makes no graph or coverage claims.
