# Aggregate tune-readiness: research note

**Cycle:** 5
**Checked:** 2026-10-18
**Model used:** GPT-6 Luna

## Research question

How can the workbench show a novice whether saved labels are sufficient to start tuning, while keeping the indicator faithful to actual tuner eligibility and avoiding claims about Elasticsearch execution or search quality?

## External source facts

### Elasticsearch ranking evaluation

- **Page title:** Ranking evaluation
- **Direct URL:** https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval
- **Checked:** 2026-10-18
- **Source fact:** Elasticsearch describes ranking evaluation over a set of typical search queries and document ratings representing relevance to each query's information need. Its metrics, including precision, recall, MRR, and DCG, provide an estimate based on that query and judgment set. The documentation recommends representative query coverage so optimizing one query does not harm other query types.
- **Application:** This supports treating human relevance labels as query-specific evidence and describing tuning readiness as a property of the available eligible labels, rather than as a general search-quality result.
- **Does not establish:** The documentation does not describe this workbench's UI, its training/validation split rules, or the cause of the current readiness mismatch. It does not prove broad quality from a small or selective label set.

## Repository observations

The following baseline facts were supplied for this research:

- `es_rag_tuner/web/app.js`, `updateTuneReadiness()` (around line 1066), currently counts positive judgments only on the current preview.
- `es_rag_tuner/concepts.py`, `tune()` (around line 986), filters stale judgments and requires at least one positive, graded training-split judgment across saved queries. Validation labels do not qualify for this minimum.

Therefore, the existing UI count and backend eligibility check describe different scopes: the current preview versus all saved queries with eligible training judgments. These are repository facts supplied for this note, not claims established by the Elasticsearch documentation above.

## Product inference and selected change

Expose an aggregate saved-label readiness summary using the same scope and eligibility rules as `concepts.tune()`. At minimum, indicate whether at least one non-stale positive graded training label exists across saved queries, and show aggregate counts that help explain the state. Keep validation labels visibly separate because they do not satisfy the training eligibility requirement. The indicator should avoid implying that current-preview positives alone determine eligibility.

The selected change exposes aggregate label counts/readiness only. It does not display document IDs, judgment reasons, or connection data. Suggested language: “Ready to tune: at least one eligible positive training label is saved across your queries” or “Not ready: add a positive training label to a saved query.” The UI should state that readiness does not verify Elasticsearch execution or search quality.

## Limitations and interpretation

Readiness means only that the backend's minimum label prerequisite is met. It does not establish that judgments are representative, that a tuned result is relevant, that validation performance is good, or that the current Elasticsearch index/query will execute successfully. The Elasticsearch ranking-evaluation source supports the need for query-specific relevance judgments and representative query coverage; it is not direct evidence for this UI mismatch and does not validate this product's readiness logic.
