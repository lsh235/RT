# Experiment export research

Checked against primary documentation on 2026-10-18. The observations below summarize documented behavior; the product direction is a project inference.

## Documented behavior

- **Elasticsearch `_rank_eval`:** Ranking evaluation requests associate a query/request with its own rated document IDs and integer relevance grades. The response provides an overall metric score, per-query details, unrated result IDs, and metric-specific details. The docs describe a query-time evaluation endpoint, not a portable historical run archive. [Elastic ranking evaluation](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval)
- **Ragas schemas and interchange:** `SingleTurnSample` includes retrieved/reference contexts and retrieved/reference context IDs. `EvaluationDataset` exposes `to_jsonl` and `from_jsonl` methods for line-oriented dataset round-trip. Ragas also documents ID-based context precision, which compares retrieved context IDs to reference context IDs without comparing context content. Its context precision metric evaluates whether relevant retrieved chunks rank higher. [Ragas evaluation schemas](https://docs.ragas.io/en/stable/references/evaluation_schema/), [Ragas context precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/)
- **LangSmith:** Offline evaluation uses curated datasets to compare application versions before deployment. Benchmarking guidance calls for representative inputs, metrics, and curated gold-standard reference outputs; the page describes comparison of versions on those datasets. [LangSmith evaluation types](https://docs.langchain.com/langsmith/evaluation-types)

## Project inference and sequencing

These sources establish useful downstream shapes, not a requirement to adopt any one framework. The project’s first export step should preserve the saved run as measured: saved query and split, judgment state, result IDs/order, metrics, and provenance. That creates a portable evidence boundary before a separate evaluation-pack importer maps records into a framework schema. It also avoids introducing framework dependencies or deciding metric/evaluator policy as part of saved-run export.

The export is a historical evidence artifact, not a fresh evaluation: it does not rerun Elasticsearch or prove that the index still has the same contents. An eventual evaluation pack needs explicit mapping for query IDs, corpus/index identity, document IDs, grades, splits, and metric context; framework-specific fields should be added by an adapter rather than implied by the run export. A run’s own judgment set does not automatically become a gold-standard reference dataset, and the system must preserve the distinction between an explicit grade of zero and an unjudged document.

## Judgment and privacy limits

Human judgments describe only the user’s assessed query/document pairs. They do not establish exhaustive relevance, answer correctness, or downstream RAG quality. Exported query and judgment-reason text is user-authored and may contain sensitive content. Common credential forms can be redacted, but arbitrary free text cannot be screened reliably; review before sharing or importing the artifact. Keep full source text out of the export, retain document identity/provenance needed for mapping, and make any future context-content export an explicit, separately reviewed choice.
