# Cycle 10 research: honest match evidence for remembered-word candidates

Checked: 2026-10-18. Scope: official Elastic documentation, project source/configuration, and product feasibility. No application code was changed; no tests were run; no Elasticsearch endpoint, corpus, database, or credentials were accessed.

## Runtime and evidence boundary

The requested model override was `gpt-6-luna`. My runtime does not expose a verifiable model-identity field, so I cannot confirm that override was applied. The assigned codebase-memory graph prerequisite was unavailable: the parent reported that the exact exposed graph-tools list was empty. Bounded source inspection below supplied the implementation evidence instead.

The current project is version 0.10.0 (`pyproject.toml`); its dependency metadata does not declare an Elasticsearch server-version range. The milestone history records an Elasticsearch 7.10.2 OSS compatibility finding for dense vectors, but does not establish that 7.10.2 is the supported target for every API. Therefore compatibility of any proposed highlighting/inner-hits request must be accepted against the actual server versions the project chooses to support. Current Elastic docs and the versioned 8.19 docs agree on the relevant features; that does not prove compatibility with every older target.

## Findings

### Scalar fields

The Cycle 9 implementation builds one `multi_match` per mapping-derived nested-path group, puts those clauses under `bool.should` with `minimum_should_match: 1`, requests at most ten hits, and then selects the first configured non-nested non-title field for its excerpt (`es_rag_tuner/concepts.py`, `locate_document`). Thus the displayed excerpt field can differ from the field that matched.

Elastic documents `highlight` as returning a `highlight` object on each hit, keyed by requested field with fragment arrays. The unified highlighter supports `text` and `keyword`; the documented default `require_field_match` is true, meaning only fields containing a query match are highlighted. A bounded request can set `number_of_fragments: 1` and a modest `fragment_size`; setting fragments to zero returns the entire field and ignores fragment size, so it is unsuitable here. If a field has no match, no highlight is returned by default; `no_match_size` can deliberately return an unhighlighted leading snippet, which should not be presented as matched evidence.

Because `require_field_match` defaults true and the request already names configured text fields, per-field highlights can supply an honest configured-field attribution signal for scalar `multi_match` clauses. For this query's disjunction, a highlight may be absent for a candidate field; the UI should not substitute a different configured field and imply that it matched. A candidate can still have multiple matching fields; choosing the first returned field is a UI policy, not an assertion that it was the sole or strongest cause.

### Nested fields

Elastic says a nested query returns the root parent hit; `inner_hits` exposes the matching nested objects, and inner hits support both highlighting and source filtering. This makes an exact nested excerpt feasible by adding a named, size-one `inner_hits` definition to each mapping-derived nested clause and requesting the configured nested text fields' highlight there.

Nested results must be read from the named `inner_hits` bucket on the root hit, not from root `_source` flattened or searched heuristically. Root `_source` extraction for inner hits parses the root source to isolate nested data and adds search cost. If the expected inner-hit bucket, nested hit, or highlight is absent, show no nested excerpt and say that a configured nested field was searched without an excerpt; do not fall back to a root scalar field.

### Costs and correctness limits

Elastic states highlighting requires actual field content. If the field is not stored, Elasticsearch loads `_source` and extracts that field. Source filtering limits returned fields but does not avoid loading/parsing `_source`. `inner_hits` source extraction has additional cost. The highlight guide warns that highlighters do not fully reflect Boolean logic for complex queries (including nested bool and `minimum_should_match`), so a highlighted lexical fragment is useful context, not proof of overall relevance or a complete explanation of why the candidate ranked. Keep this feature wording to “candidate because these configured words appear in this excerpt/field,” and preserve the product's candidate-only framing.

The UI currently renders excerpt text and field name. Elasticsearch's default highlight tags are HTML-like tags. If these are returned to the browser, render them as text or safely parse/escape only the known marker pair; never inject raw highlight markup or corpus text as HTML. A simpler initial version can show a plain bounded fragment and matched field name without visual term markup.

## Recommendation: GO, narrowly gated

Proceed with a bounded acceptance spike for scalar highlighting, with nested excerpts disabled until a dedicated nested fixture proves the `inner_hits` response path on the supported server matrix. This is feasible without arbitrary query DSL or changes to retrieval semantics. The source code already groups fields by mapping-derived nested path, so highlights and inner-hit definitions can be limited to those configured fields and paths.

Minimum later acceptance criteria:

1. A scalar fixture has two configured text fields, only the second matches, and the returned/displayed excerpt field is the second field; no first-field fallback is labeled as matched.
2. Request exactly one bounded fragment per field (for example, `number_of_fragments: 1`, a documented finite fragment size, `require_field_match: true`); enforce an application-side output cap as well. Do not use `no_match_size` as match evidence.
3. A hit with no configured-field highlight remains a candidate only if Elasticsearch matched it, but UI explicitly omits the matched excerpt/field claim.
4. Nested behavior is either (a) disabled for excerpts with explicit no-nested-excerpt wording, or (b) validated with a nested-only fixture where one matching nested child is surfaced through a named `inner_hits` result and its own highlight. Missing inner hits/highlights must not trigger scalar/root-source fallback.
5. Include a non-match decoy in the nested fixture and verify its text is not attributed to the matching nested child. Verify scalar and nested fields separately, including multiple matching fields/children.
6. Preserve current index scoping, saved-concept field allowlist, ten-hit cap, partial-result failure behavior, and HTML-safe rendering. Candidate evidence must not be described as proof of full relevance or answer quality.
7. Run the acceptance request against each declared supported Elasticsearch server version before release; record version and mapping details. Do not infer support merely from current Elastic docs or the historical 7.10.2 vector compatibility note.

## Official sources checked

- [Elastic: Highlighting](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting) — response shape, `_source` requirement when fields are not stored, complex Boolean caveat, highlighter types.
- [Elastic: Highlighting examples](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting-examples) — `require_field_match`, `fragment_size`, `number_of_fragments`, zero-fragment whole-field behavior, and `no_match_size`.
- [Elastic: Highlighting settings](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting-settings) — default `require_field_match: true` and analyzed-offset behavior.
- [Elastic: Nested query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-nested-query) — root-parent hit behavior and purpose of `inner_hits`.
- [Elastic: Retrieve inner hits](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrieve-inner-hits) — nested hit response structure, default size, highlighting/source-filter support, and nested source extraction cost.
- [Elastic 8.19: Highlighting](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/highlighting.html) and [Elastic 8.19: Retrieve inner hits](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/inner-hits.html) — versioned cross-check for the feature surface; not evidence for 7.x compatibility.

## Source-backed facts vs product inference

Elastic source-backed facts are stated in Findings and linked above. The GO recommendation, plain-language wording, scalar-first scope, no-fallback behavior, UI copy, and acceptance scenarios are product inferences intended to preserve honest candidate evidence and limit operational cost.

## Follow-up: empty highlight tags for escaped plain-text rendering

The current [Elastic highlighting examples](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting-examples) confirm that `pre_tags` and `post_tags` control the strings wrapped around highlighted terms, but they only show nonempty examples. The [Search API highlight settings](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting-settings) describe each as an array of strings; the documentation does not explicitly state that empty strings are supported or show the resulting response when both are empty. The official [ES|QL HIGHLIGHT options](https://www.elastic.co/docs/reference/query-languages/esql/commands/highlight) likewise accept string tag values, but this is a separate feature and is not proof of `_search` behavior.

**Confirmed:** callers can configure the highlight wrapper strings; search highlighting returns formatted fragment strings. **Not explicitly confirmed by the current official `_search` docs:** whether `pre_tags: [""]` and `post_tags: [""]` are accepted as valid and return an unmarked fragment. The expected output would be the same fragment text without inserted delimiters; that is a reasonable inference from the documented wrapper semantics, not a verified Elastic guarantee. Keep this as a compatibility acceptance check against each supported server version before relying on it.

For a UI that always HTML-escapes corpus text, empty tags would be a sensible way to reuse Elasticsearch's bounded fragment selection while presenting plain text. This UI recommendation is product inference. It preserves the earlier GO recommendation; it adds a small request/response acceptance point rather than changing scope. If empty tags are rejected or behave unexpectedly on the supported matrix, use the normal distinct marker pair and remove only those exact markers before the UI's escaping step, with tests covering corpus text that itself contains marker-like strings.
