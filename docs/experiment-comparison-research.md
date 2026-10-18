# Saved experiment comparison research

**Checked:** 2026-10-18

This note provides research context for a novice-friendly detail view of one saved historical preview or tune run, with train and validation evidence kept separate and per-query evidence visible. It does not validate this workbench's run schema or stored metrics.

## Primary-source facts

- [PyTerrier experiment guide](https://github.com/terrier-org/pyterrier/blob/master/docs/experiments.rst) describes IR experiments as running systems over a query set and evaluating results against relevance assessments (qrels). Its `perquery=True` output gives a metric for each system, query, and measure. The guide also reports per-query improvements and degradations against a baseline, and supports paired significance tests and multiple-testing correction.
- [MLflow evaluation datasets](https://mlflow.org/docs/latest/genai/datasets) describes reusing the same evaluation data to compare app versions and using a golden set to prevent regressions.
- [MLflow retriever metrics](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.metrics.html) describes retrieval evaluation inputs as queries, retrieved document IDs, and ground-truth document IDs. Its retrieval metrics use a configurable cutoff `k`.
- [NIST `trec_eval`](https://github.com/usnistgov/trec_eval/blob/main/trec_eval.c) supports per-query results and documents choices that affect evaluation, including query coverage, relevance thresholds, and unjudged documents. Its notes state that many measures treat unjudged documents like nonrelevant unless a different evaluation policy is selected.

## Product inferences

- A historical detail view for one selected run should show that run's saved inputs and outputs, including query/split identity, judgments, ranked document IDs, and reproducibility fingerprints. Keep train and validation evidence separate.
- For a tune run, show the baseline-versus-tuned metrics and per-query deltas already recorded within that run, alongside document IDs that entered, left, or moved in its rankings. These are descriptive comparisons over that run's recorded inputs and judgments, not a verdict about relevance beyond those judgments. For a preview run, show the stored baseline/candidate evidence without implying that it is a tune evaluation.
- Prefer validation evidence when reviewing a tuning change. If validation is missing, label the evidence training-only. Preserve the distinction between explicit irrelevant grades and unjudged documents.

### Future extension: comparing separate runs

If a later feature compares two separate runs, label metric deltas directly comparable only when they use the same split, query identities/text, judgment set, cutoff, and metric policy. Available index and mapping fingerprints are additional context, but do not prove that indexed document contents were unchanged. Otherwise show the stored evidence side by side and mark metric deltas as not directly comparable.

## Limits

These sources describe established evaluation patterns; they do not validate this workbench's persistence schema, fingerprints, or metrics. A matching index identity or mapping fingerprint does not prove that all indexed document contents were unchanged between runs. Small or sparse human judgment sets do not support broad claims or statistical-significance claims from a simple side-by-side view. Retrieval metrics measure retrieval under the recorded queries and judgments; they do not establish that generated RAG answers improved.
