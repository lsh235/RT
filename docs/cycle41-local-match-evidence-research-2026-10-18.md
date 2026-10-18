# Cycle 41: local match evidence research (2026-10-18)

## Question

How can the private local knowledge preview show which saved literal expression group matched a returned result without implying that the group caused its rank or is semantically relevant?

## Source facts

The [official SQLite FTS5 documentation](https://www.sqlite.org/fts5.html), checked 2026-10-18, describes the `MATCH` query syntax and tokenization, including quoted phrases and OR expressions. It documents `highlight()` and `snippet()` output as ways to mark matching text, with limits on the returned fragments. Those functions show matched text in a row; they do not identify which of several independently defined saved term categories supplied the match.

The preview already constructs quoted literal OR expressions with `_literal_match`, uses the `unicode61` tokenizer, and selects a representative chunk row for each returned document. The FTS table indexes each chunk's content plus its document title and source label.

## Product inference and implementation choice

Run one category `MATCH` query for each eligible fixed group, constrained by the returned lane's representative `chunk_id` values. This directly answers whether that expression group matches the same FTS row used by that hit. The expanded lane has at most 20 hits and uses no more than three group queries (`saved_query`, `concept_expressions`, `related_terms`); it does not add a per-document query or corpus-wide rerank. Baseline already contains only saved-query matches, so it receives the fixed `saved_query` cue without another query.

The groups preserve saved eligibility: concept name, non-empty description, and aliases only when `concept_weight > 0`; related terms only when global `related_weight > 0` and that entry's weight is positive. Tokens in excluded terms are removed from expansion groups. Match checks reuse `_literal_match`, so each token is quoted and FTS5 interprets its indexed token semantics.

The API emits only fixed enum IDs, never saved expression text. The UI recognizes only those IDs and renders labels through `textContent`. It displays cues separately for baseline and expanded rank rows.

## Limits

A group indicates that at least one eligible literal token in that group matched the representative FTS row, whose searchable fields are chunk content, title, or source label. It does not show which token matched, prove that a group caused rank or score, establish semantic relevance, or assess retrieval quality. Expanded document exclusion remains the existing document-level rule and is applied during ranking; match cues do not change it. The implementation makes no Elasticsearch, embedding, AI, or quality claim.
