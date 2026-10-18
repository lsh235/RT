# Saved query label coverage: research note

**Cycle:** 6
**Checked:** 2026-10-18
**Model used:** GPT-6 Luna

## Research question

How might the workbench help a beginner see how saved relevance labels are distributed across distinct training and validation queries, without implying that a particular number of labels makes evaluation adequate?

## External source findings

### Per-query reporting in `trec_eval`

- **Source:** NIST, `trec_eval` README, https://github.com/usnistgov/trec_eval/blob/main/README
- **Checked:** 2026-10-18
- **Finding:** The README describes `-q` as the option to report evaluation measures for individual queries as well as averages over all queries.
- **Limit:** This is a reporting option in an evaluation tool. It does not prescribe this application's UI or show that per-query reporting alone makes an evaluation reliable.

### Query variation and system evaluation

- **Source:** Peter Bailey, “User Variability and IR System Evaluation,” SIGIR 2015, Microsoft Research, https://www.microsoft.com/en-us/research/publication/user-variability-and-ir-system-evaluation/
- **Checked:** 2026-10-18
- **Finding:** In experiments using selected topics from three TREC collections, different queries expressing the same information need substantially affected effectiveness. The score range for one system across query variations was comparable to, or greater than, the range across systems using one query per topic. The paper recommends using multiple query variations in test collection design.
- **Limit:** The study's collections, selected topics, and task categories do not define a required query count for this workbench or prove that a particular saved set is representative.

### Query variation and judgment pools

- **Source:** Alistair Moffat, Falk Scholer, Paul Thomas, and Peter Bailey, “Pooled Evaluation Over Query Variations: Users are as Diverse as Systems,” CIKM 2015, https://doi.org/10.1145/2806416.2806606
- **Checked:** 2026-10-18
- **Finding:** The authors report that user query variation affects the size of relevance-judgment pools comparably to retrieval-system variation, and argue that query variation should be considered when test collections are constructed.
- **Limit:** This research concerns query variation in pooling and collection construction. It does not define a UI, an adequacy threshold, or a guarantee that counting queries yields representative coverage.

## Product inference for this repository

Show the current saved **training** and **validation** query totals separately. For each split, show aggregate counts of distinct queries with at least one graded judgment and distinct queries with at least one positive judgment. Keep the counts descriptive: do not declare the set adequate, impose a minimum query or label threshold, or combine the two splits into one coverage number. Distinct-query coverage helps reveal when labels are concentrated on only a subset of saved queries; the sources support the usefulness of query-level visibility, but do not prove that the repository's query set represents actual use.

## Interpretation limits

These sources motivate inspecting per-query coverage and variation. They do not prove that saved queries are representative, that ratings are correct or complete, or that an aggregate relevance metric will generalize. A coverage display describes where labels exist; it is not a search-quality verdict or a substitute for reviewing individual query results.
