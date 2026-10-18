# Cycle 11 research: candidate pools vs information-need query groups

**Checked:** 2026-10-18

**Requested model override:** `gpt-6-luna`; runtime identity is not exposed in a verifiable way here, so application of the override cannot be confirmed.
**Scope:** Bounded comparison of the two supplied directions using official/primary IR guidance and project source contracts. No application code changed; no tests were run; no user database, corpus, or credentials were accessed.

## Recommendation: GO for query groups, in a small first slice

Choose **B: human-authored query variants grouped by one information need**, but initially implement only group identity, split integrity, and group-aware coverage display. Keep exact query-level judgments and metrics unchanged. Do not add group-level averaged metrics in this first slice; their weighting policy is a separate decision.

This is the smaller and safer next cycle for a RAG novice. The project already stores query identity, split, exact query-specific judgments, and per-query metrics. An optional need-group association can be stored within the existing concept JSON body; it does not require a new retrieval mode or another Elasticsearch search per query. The main implementation burden is validating group-to-split integrity and representing the group in snapshots/exports. This is still a medium-sized change and needs explicit migration/backward-compatibility acceptance, but it avoids coupling the feature to Jira-specific field assumptions and vector readiness.

Candidate pooling remains a valid later direction, but it should wait for a retrieval adapter that uses the concept's mapped fields and filters consistently across BM25, vector, and hybrid modes, plus explicit partial-mode failure semantics and pool provenance.

## Official and primary-source findings

- Elastic's [ranking evaluation guide](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval) says ratings are needed per test query and should reflect the information need of the user who entered that query. The API treats queries and their ratings as distinct request entries. This supports preserving exact query-level identities even when a product groups variants under a shared need.
- Bailey et al.'s SIGIR 2015 [paper page and abstract](https://www.microsoft.com/en-us/research/publication/user-variability-and-ir-system-evaluation/) reports that different formulations of the same described information need can materially affect retrieval effectiveness; it recommends multiple query variations per topic. This supports inspecting multiple variants, but does not prescribe this workbench's group metric or sample size.
- NIST's [TREC relevance-judgment guidance](https://trec.nist.gov/data/reljudge_eng.html) says relevance is defined with respect to a topic and that pools must match the document collection and qrels when runs are evaluated. The [TREC 2024 overview](https://trec.nist.gov/pubs/trec33/papers/overview_33.pdf) explains that pooling combines top documents from multiple runs, but is a sample: shallow pools can miss relevant documents and bias evaluation against systems retrieving less common document types. TREC's conventional treatment of unpooled documents as nonrelevant is a protocol choice and must not replace this project's explicit-unjudged behavior.
- The official [NIST `trec_eval` source](https://github.com/usnistgov/trec_eval/blob/main/trec_eval.c) documents `-q` output for each query/topic, and warns that standard measures often treat unjudged records like nonrelevant unless configured otherwise. It supports retaining per-query evidence; it does not establish that a mean across variants is a valid estimate of a novice's real use.

These findings support grouping query phrasings as related human evidence while retaining per-query results. They do not establish representativeness, query-group adequacy, or a universally correct group-average metric.

## Current project fit and constraints

Repository evidence, bounded to the supplied parent inspection plus source lines reviewed for this note:

- `retrieval.search()` supports `bm25`, `vector`, and `hybrid`, but defaults to a Jira-shaped `source_fields` list. Hybrid executes lexical and vector retrieval, then fuses results with reciprocal-rank fusion. Those modes exist in general search; concept validation currently rejects every mode except BM25.
- Concept query records are flat `{id, query, split}` values, with up to 100 query cases. Judgments are keyed by exact `(concept_id, query_id, document_index, document_id)` and include a query fingerprint. Evaluation and tuning consume rankings per exact query ID; train/validation partitioning currently reads the query's own split.
- Concept and run bodies are JSON in SQLite, and run exports preserve query records, judgment snapshots, result IDs/order, metrics, and reproducibility fingerprints. A group field could avoid a new relational table, but changing the concept/query representation affects validation, fingerprints, saved profile snapshots, comparisons, exports, and old clients. Old records without a group field need defined semantics (for example, each ungrouped query is its own implicit group); this is a design inference, not an existing contract.
- The concept corpus already scopes an index, mapped text fields, filters, and BM25 boosts. Reusing general-search modes for candidate pooling would need to guarantee the same index and filter set, use mapping-derived fields rather than Jira defaults, identify whether required vector data/model readiness is satisfied, and keep per-mode result ranks and failures. Current concept mode rejection means candidate-pool provenance cannot be added by simply flipping the saved mode.

### Direction A: multi-mode candidate pool

**Potential value:** Human reviewers see candidates surfaced by distinct retrieval approaches, including a document only one mode found. Deduplicating exact `(index, id)` and retaining `(mode, rank)` can collect broader judgment coverage.

**Feasibility and failure semantics:** High coupling. At least three bounded searches per query may be needed, and vector/hybrid may fail or be unavailable while BM25 works. A partial pool must be labeled incomplete or rejected, never silently treated as the requested complete pool. A pool should record query text/ID, corpus/index identity, filters, candidate size, mode and rank, fusion settings if applicable, and per-mode status. Deduplication must not collapse equal IDs from different indices. Pool membership must not enter organic ranking metrics as if the pooled union were a system ranking; source-mode rank provenance is separate evidence.

**Privacy/confidence:** Human-written queries, filters, index names, result identifiers, and any reasons may be sensitive. Export review remains required. A shallow pool is non-exhaustive; it cannot imply recall of all relevant documents. Preserve `null` unjudged separately from grade 0 and don't use candidate-pool membership as a relevance label.

**Assessment:** NO-GO as the next small cycle. Proceed later after a mapping-aware concept retrieval adapter and a declared all-or-partial mode contract.

### Direction B: group variants by information need

**Potential value:** Helps novices separate “what I need” from “how I searched for it”; makes it visible whether a need has one or several phrasings and whether a split contains multiple needs. The cited research supports query formulation variability; current exact query-level grades already capture that variability.

**Feasibility and failure semantics:** Moderate. Add an optional stable group identifier and short user-authored information-need statement; preserve each query ID and its judgment key. Validate that all variants in a group share one split. When a user moves a query between groups or changes group split, do not silently move grades, copy grades, or alter query fingerprints. Reject an invalid cross-split group update with a clear error, or require an explicit edit that updates all members atomically. Keep train-only tune input and validation exclusion unchanged. For compatibility, old queries without a group can be shown as single-query groups until explicitly grouped.

**Metrics and corpus identity:** Keep per-query metrics, labels, index identity, filters, and ranking inputs exactly as today. In the first slice, report group count and query count per split, plus which groups have graded/positive evidence; do not average query metrics into a new group score. The group statement provides context, not a replacement for query text or a new judgment key. A later group metric would need a declared weighting rule (for example equal need vs equal query) and safeguards against groups with many variants dominating.

**Privacy/confidence:** Group descriptions and query variants are user-authored free text and should be treated like existing query/reason text in exports. Keep the current export warning/review expectation. Show counts and observed query-level results only; do not label a set “representative,” “adequate,” or statistically generalizable based on number of groups.

**Assessment:** GO, limited to metadata, integrity, and coverage. It better reuses existing query/judgment contracts and does not call alternate retrieval modes.

## Bounded acceptance criteria for the recommended slice

1. A concept can contain two human-written variants under one information-need group and another independent group; each query retains its existing unique ID and exact `(query_id, index, document_id)` judgment identity.
2. A group cannot span train and validation. Reassigning a group or one of its members is atomic or rejected; no grade is copied to a different query ID, and no validation judgment is used in tuning.
3. Older profiles with no group metadata still load and behave as independent single-query groups without a migration that rewrites user data on read.
4. Query-level ranking, metrics, saved-run comparisons, filters, corpus/index identity, candidate order, and explicit-unjudged handling remain unchanged. Initial group display reports counts/coverage only; it adds no group-average metric.
5. Run/profile snapshots and exports preserve group metadata and exact query membership. Export text makes clear that the artifact contains user-authored query/group/grade evidence and needs review before sharing.
6. UI distinguishes need-group text from the actual query string and keeps per-query outcomes visible. No adequacy, representativeness, significance, or RAG-answer-quality claim is added.
7. Acceptance covers a legacy ungrouped profile, valid multi-variant group, attempted cross-split group, group edit with existing grades, export round-trip, and train/validation isolation.

If this still exceeds one cycle, first deliver only stable group metadata plus same-split validation and group/query coverage counts; defer the information-need statement editor and any group-level metric.

## Source boundary

Checked official Elastic docs, NIST/TREC material, NIST's `trec_eval` repository, and the primary SIGIR paper record on 2026-10-18. The project details above are source inspection, not a runtime or test claim. Recommendation, acceptance criteria, and the choice to defer candidate pooling are product inferences.
