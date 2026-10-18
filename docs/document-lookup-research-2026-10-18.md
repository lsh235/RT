# Document lookup without a known ID

**Checked:** 2026-10-18
**Decision scope:** `es_rag_tuner/server.py`, `es_rag_tuner/concepts.py`, and the manual-document UI in `es_rag_tuner/web/index.html` and `es_rag_tuner/web/app.js`.

## Recommendation

Add a small text locator to the existing manual-document workflow. A user enters words remembered from the document title or body, sees at most ten candidate documents, selects one, and then uses the existing explicit judgment/diagnosis flow with that document's `_index` and `_id`. Keep the locator phrase separate from the saved relevance query; locating a document must not silently change the query being judged.

Build the request on the server as `POST /{configured-concept-index}/_search`. Use a `multi_match` query with an explicit `fields` array derived only from the saved concept's validated `corpus.text_fields` (which already includes `title_field` when present). Do not accept raw Query DSL, caller-supplied field names, an arbitrary index pattern, or query-string syntax from the UI. For a locator, omit the concept's evaluation filters by default and say so in the UI; otherwise a document excluded by those filters could remain impossible to locate and diagnose. Applying optional locator filters can be a later explicit choice.

Proposed first-release bounds: reuse the existing 4,000-character query limit; fix `size` at 10 and `from` at 0 in server code; do not expose a caller-controlled size or pagination; set `track_total_hits: false`; and do not set `terminate_after`. The ten-hit cap bounds returned candidates, not the work Elasticsearch may perform. A timeout is an incomplete lookup, never a no-hit result.

## Current project gap

- The route table has `/api/concepts/document`, but no text-locator route. `server.py:204-215`.
- `_concept_document` requires an exact `document_id`, calls `GET /{index}/_doc/{id}`, and returns the entire `_source`. `server.py:580-592`.
- Concept validation limits `corpus.text_fields` to 20 and requires a configured `title_field` to also be in `text_fields`. `concepts.py:134-145`; the existing query-length limit is `MAX_TEXT = 4000` (`concepts.py:23`, with validation at `concepts.py:479-480`).
- The mapping reader records searchable fields, `nested_path`, and `source_field`; multi-fields map to their parent source field. `concepts.py:335-365`. `_validate_search_fields` checks the selected fields against the current mapping, and `_make_query` already groups fields by nested path and wraps each nested group. `concepts.py:567-583, 596-621`.
- The manual-document card asks for a document ID and a saved query. `web/index.html:119`; button readiness requires both values (`web/app.js:185-189`). Fetch and diagnosis both start from that ID (`web/app.js:1550-1565, 1570-1593`). The fetch renderer currently builds a snippet from the first three string values in the full source (`web/app.js:1561-1564`).

## Verified Elastic facts

These are current official Elasticsearch documentation facts checked on 2026-10-18:

1. The Search API is an index-scoped search operation and requires index `read` privileges. Its default page size is 10 and default `from` is 0. Large/deep `from` + `size` pages increase memory and CPU; the default `index.max_result_window` is 10,000. [Search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search) · [Paginate search results](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/paginate-search-results)
2. `multi_match` supports multiple named fields. If `fields` is omitted, it uses `index.query.default_field`, which defaults to `*`; an explicit field list is therefore needed to keep this lookup inside the user's configured fields. [Multi-match query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-multi-match-query)
3. A `nested` query requires its mapped `path` and returns the root parent document when a nested object matches. Nested `inner_hits` can identify matching nested objects; the default inner-hit size is three, and extracting nested source adds search cost. [Nested query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-nested-query) · [Retrieve inner hits](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrieve-inner-hits)
4. Search `_source` filtering can include selected source paths, but Elasticsearch still loads and parses the whole `_source` to return a subset. It limits response fields, not source-loading work. [Retrieve selected fields](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrieve-selected-fields)
5. `track_total_hits: false` omits the exact total. `allow_partial_search_results` defaults to `true`; setting it to `false` turns shard failures or shard request timeouts into an error with no partial results. A response with `timed_out: true` may have partial or empty hits. `terminate_after` deliberately ends collection early and is documented with a caution. [Search API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search)
6. Search highlighting can return fragments for requested fields. `fragment_size` controls the fragment size in characters and `number_of_fragments` caps fragments; setting the latter to zero returns the whole field. Highlighting still needs field content and may load it from `_source`. [Highlighting](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting) · [Search API highlighting options](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-search)

## Product inferences and implementation shape

### `concepts.py`

- Add a locator builder beside the existing search helpers. Reuse `_validate_search_fields` for mapping refresh/validation, then derive query fields from `corpus.text_fields` and group them by `_field_metadata[field].nested_path`, following `_make_query`'s mapping-aware grouping. Use `multi_match` `best_fields` as the simple starting behavior already used by the workbench; it is a ranked text lookup, not proof of exact phrase or semantic equivalence.
- For `_source.includes`, deduplicate `_field_metadata[field].source_field` paths for selected title/text fields. This matters for multi-fields such as `title.keyword`, whose source value is at `title`. Do not use `*` patterns or include unselected fields.
- Prefer a short title plus one bounded excerpt per candidate. The route should cap strings it returns (for example, at 600 characters, matching existing snippet handling) and avoid returning arbitrary source fields. Source filtering alone does not cap the length of a large selected text value or bound Elasticsearch's internal source work. A highlight fragment is a possible response-size improvement, but it still needs source content and should be measured on the project's supported mappings before relying on it as a hard cost bound.
- For selected nested fields, wrap each nested-field group in a `nested` query with the mapping-derived path. The hit is still the root document. If the UI must show which nested entry matched, add one `inner_hits` result per nested path with `size: 1` and source filtering; do not flatten nested arrays into unrelated strings. This is a deliberate complexity choice because nested inner-hit source extraction has cost. A first slice may show the root title and state that the text matched a configured nested field, adding the nested excerpt only after a nested fixture proves it works.

### `server.py`

- Add a dedicated locator endpoint that accepts the selected concept and lookup text, and uses the concept's configured index. Validate text length and concept fields server-side; ignore any caller attempt to override the generated fields, index, `size`, or Query DSL.
- Send `POST /{configured-index}/_search` with `size: 10`, `from: 0`, `track_total_hits: false`, and source selection limited to the mapped title/text paths. Set `allow_partial_search_results=false` where the supported Elasticsearch versions accept it. Do not use `terminate_after` to bound this UI: it can end collection before a real match is found.
- Treat HTTP/API errors, `timed_out: true`, or `_shards.failed > 0` as “lookup could not be completed,” even if the response has no hits. Only a successful, completed response with an empty `hits.hits` is a zero-hit lookup. With `track_total_hits: false`, do not show a corpus-wide count.
- Return only candidate identity, score, configured title, and bounded configured-field excerpt(s). The locator does not store a relevance judgment. The chosen hit feeds its `_index`/`_id` into the existing diagnosis/judgment path while preserving the user's separately selected saved query.

### Manual-document UI

- Add a “find by title/body words” input and a search button to the existing manual-document card. Keep the known-ID route available as a direct fallback. Show that the locator searches the selected concept's configured title/text fields and does not apply the saved evaluation query or concept filters.
- Render up to ten candidates with title, a short excerpt, and an explicit “use this document” action. Selecting a candidate should make its identity available to the existing “load for judging” and “diagnose missing reason” actions. Preserve the saved query selection; never record a judgment just because a candidate was found.
- If a filtered source preview is used, state that it contains only the configured display fields. The existing exact-ID route currently returns full `_source`; the locator itself should not call that route just to re-render a candidate, or the lookup's response minimization would be lost.

### Zero-hit wording

Suggested copy after a clean completed zero-hit response:

> No matching document was returned for these words in the selected index's configured title/text fields. This does not establish that the document is absent from the index. Try other words or use its ID if you know it.

If the search errors, times out, has a failed shard, or returns partial results, show “Could not complete this lookup” with a retry/connection hint; do not show the zero-hit copy. A match is also not a relevance judgment: the user still decides whether the document is relevant to the saved evaluation query.

## Risks and acceptance gates for a follow-up implementation

| Risk | Acceptance gate |
|---|---|
| Lookup accidentally searches fields outside the configured concept | Captured request uses only the saved `corpus.index` and explicit validated `corpus.text_fields`; no wildcard field list, raw DSL, or arbitrary index input is accepted. |
| Unbounded UI result list or expensive total count | Every lookup sends fixed `size: 10`, `from: 0`, `track_total_hits: false`; no pagination or total-count request is added. The API response to the browser is at most ten hits and contains only bounded display strings plus identities/scores. |
| A no-hit message masks incomplete search | Mocked error, timeout, `timed_out: true`, and `_shards.failed > 0` each render the incomplete/error state. Zero-hit copy appears only for HTTP success, `timed_out: false`, zero failed shards, and an empty hit array. |
| Nested match is lost or misrepresented | A nested fixture returns the root document through the mapping-derived nested path. If an excerpt is shown, it comes from the matching `inner_hits` entry with size 1; otherwise the UI does not claim to show the matching nested text. |
| Source filtering is mistaken for security or a byte/work guarantee | Request includes only deduplicated mapped `source_field` paths; tests confirm unrelated source keys are absent from browser JSON and each excerpt is clipped. Documentation/UI do not claim that this prevents Elasticsearch from loading `_source` internally. |
| Locator hit is treated as an evaluation label | Finding/selecting a candidate creates no judgment. A label is written only through the existing explicit human judgment action and remains attached to the chosen saved query ID. |

## Research provenance

- The `codebase-memory` skill was read as required by the repository instructions, but its graph MCP tools were not exposed in this session. For this implementation decision, repository source inspection was limited to the four paths named above.
- No project data or database was accessed, and no tests were run.
- Model identity was not exposed in this subagent session's metadata/tools; it is **unverified**.
