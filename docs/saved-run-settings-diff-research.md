# Saved preview setting differences: research note

**Cycle:** 4
**Base:** `v0.4.0` (`324febc0a299c2c9413a39e28b60e365eff79c39`)
**Checked:** 2026-10-18
**Model used:** GPT-6 Luna

## Question

Would a plain-language summary of differing saved concept settings help a RAG novice interpret the existing pairwise saved-preview comparison, and what can the summary safely claim?

## Official sources

### Boolean query

- **Page title:** Boolean query
- **Direct URL:** https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-bool-query
- **Checked:** 2026-10-18
- **Source fact:** Elasticsearch documents that matching `must` and `should` clauses contribute scores, with matching clause scores added together. `filter` clauses constrain matches without affecting score.
- **Application:** Saved concept settings such as concept/related-expression weights and field boosts can describe different score inputs in the candidate query. A user-facing difference summary can report those saved inputs in readable terms.
- **Does not establish:** This page does not establish that a particular setting difference changed a particular document's score or rank, that the compared corpus/index snapshots were identical, or that a resulting order is more relevant.

### Query and filter context

- **Page title:** Query and filter context
- **Direct URL:** https://www.elastic.co/docs/reference/query-languages/query-dsl/query-filter-context
- **Checked:** 2026-10-18
- **Source fact:** Elasticsearch describes query context as both deciding whether a document matches and calculating a relevance score; filter context answers a binary match question. Elasticsearch ordinarily sorts matching results by relevance score.
- **Application:** The comparison should identify setting changes as recorded configuration, and keep filter differences distinct from score-oriented settings if shown. A saved settings diff helps users see what configuration differs alongside the stored outcomes.
- **Does not establish:** The documentation does not identify which setting explains an observed movement in these saved runs or provide a causal attribution method for run-to-run ranking changes.

### Multi-match query and per-field boosting

- **Page title:** Multi-match query
- **Direct URL:** https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-multi-match-query
- **Checked:** 2026-10-18
- **Source fact:** The `multi_match` documentation shows per-field boosts with caret notation such as `subject^3`, explaining that the boosted field's score is multiplied while the unboosted field's score is unchanged. It also documents that `best_fields` uses the best matching field's score, with a `tie_breaker` contribution from other matching fields.
- **Application:** The workbench constructs `multi_match` clauses with `type: best_fields`, `fields` drawn from `corpus.text_fields` and each configured `field_boosts` value, plus `tie_breaker: 0.2` (`es_rag_tuner/concepts.py`, `_make_query()`). A saved-settings summary can report each field's saved boost as a configured per-field scoring weight, with its saved value in each run.
- **Does not establish:** The documented boost behavior does not establish that a higher value improves relevance, predict a particular rank movement, explain a specific run-to-run result, or make `_score` a probability. It does not establish causal attribution.

## Product decision (inference from the sources, separate from source facts)

Cycle 4 implements a compact “Saved concept settings that differ” summary in the saved-run comparison, derived from the two stored run snapshots. It reports changed settings and their saved values in neutral language so users can see which configuration inputs differ alongside the recorded outcomes. This is a comparison of saved inputs, not an explanation of why ranks moved.

The product wording stays observational: “These saved settings differ” and “The stored results also differ.” It avoids “caused,” “improved,” “better,” or “more relevant.” The pairwise comparison limits direct rank-movement display to comparable runs; the settings summary complements that guard and does not override it. Even where rank movement is eligible for display, the diff is not causal evidence: index contents, refresh/state, or other unrecorded conditions may also matter. A changed setting is a plausible explanation to investigate, not proof of why a result moved.

## Repository observations (baseline implementation facts)

At the accepted base, `es_rag_tuner/concepts.py` stores a `safe_concept` copy under `input_snapshot.concept` in the preview run snapshot (lines 871–877). `_terms()` (lines 586–592) creates expansion terms from the concept name, nonempty description, aliases, and related terms; related-term weights are multiplied by `settings.related_weight`. Preview calls `_hits()` for baseline with `expanded=False` and candidate with its default `expanded=True` (lines 819–820); `_make_query()` adds exclusion clauses under `must_not` only when expansion is enabled (lines 644–645). `_make_query()` builds its `multi_match` field list from `corpus.text_fields`, applying each `settings.field_boosts` value in the caret field syntax, and uses `type: best_fields` with `tie_breaker: 0.2` (lines 597–616). The pair renderer and saved-run comparison live in `es_rag_tuner/web/app.js` (around lines 1849–1853); the run stores the concept snapshot, so a diff can be computed from the two saved inputs rather than from current editor state.

These are repository implementation facts, not claims from Elasticsearch documentation. They establish which recorded concept inputs feed the query construction and that baseline/candidate intentionally differ in expansion behavior. They do not prove that any one setting caused a particular movement, nor that changed results are more relevant.

## Scope boundary

This note concerns a readable settings-difference summary for pairwise saved previews. It does not evaluate Elasticsearch rank quality, recommend an evaluation metric, or claim that an observed movement is an improvement. No user data, credentials, or local database were accessed.
