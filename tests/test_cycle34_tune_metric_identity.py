"""Synthetic regression coverage for graded tune ranking identity.

Run with: python -m unittest discover -s tests -p 'test_cycle34_tune_metric_identity.py' -v
The test replaces Elasticsearch and persistence boundaries; it never opens a
user database or sends a request to a real Elasticsearch instance.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from es_rag_tuner import concepts


class TuneMetricIdentityRegression(unittest.TestCase):
    def run_synthetic_tune(self, judgments: list[dict[str, object]], hits: list[dict[str, object]]):
        concept = {
            "id": "cycle34-metric-identity",
            "name": "Synthetic tune metric identity",
            "corpus": {"index": "synthetic-index", "text_fields": ["body"]},
            "queries": [{"id": "train-q", "query": "synthetic query", "split": "train"}],
            "settings": {"size": len(hits), "candidate_size": len(hits)},
        }

        with (
            patch.object(concepts, "_validate_search_fields", return_value={"fields": []}),
            patch.object(concepts, "_judgments", return_value=judgments),
            patch.object(concepts, "_hits", return_value={"hits": hits, "total": len(hits)}),
            patch.object(concepts, "_index_identity", return_value=({"available": True}, None)),
            patch.object(concepts, "_store_run", return_value="synthetic-run"),
        ):
            return concepts.tune(connection=None, concept_value=concept, passes=1)

    def make_judgment(self, document_index: str, document_id: str, rating: int) -> dict[str, object]:
        return {
            "concept_id": "cycle34-metric-identity",
            "query_id": "train-q",
            "document_index": document_index,
            "document_id": document_id,
            "rating": rating,
            "pinned": False,
            "reason": "synthetic fixture",
            "stale": False,
        }

    def make_hit(self, document_index: str, document_id: str) -> dict[str, object]:
        return {"_index": document_index, "_id": document_id, "rank": 1, "source_sha256": "synthetic"}

    def assert_ranked_judgments_are_counted(self, document_pairs: list[tuple[str, str]]) -> None:
        judgments = [
            self.make_judgment(*document_pairs[0], 3),
            self.make_judgment(*document_pairs[1], 0),
        ]
        hits = [self.make_hit(*pair) for pair in document_pairs]

        result = self.run_synthetic_tune(judgments, hits)
        baseline = result["train"]["baseline"]

        self.assertEqual(baseline["retrieved_judged_count"], 2)
        self.assertEqual(baseline["judged_coverage_at_k"], 1.0)
        self.assertEqual(baseline["relevant_found_at_k"], 1)
        self.assertEqual(baseline["recall_of_judged_relevant_at_k"], 1.0)
        self.assertEqual(baseline["ndcg_at_k"], 1.0)

    def test_bm25_ranked_graded_documents_contribute_to_metrics(self):
        self.assert_ranked_judgments_are_counted([
            ("synthetic-index", "relevant-doc"),
            ("synthetic-index", "zero-grade-doc"),
        ])

    def test_concrete_index_and_document_id_delimiter_collision_stays_distinct(self):
        # Both pairs collapse to the same value under index + U+001F + ID.
        self.assert_ranked_judgments_are_counted([
            ("synthetic-index\x1fpart", "doc"),
            ("synthetic-index", "part\x1fdoc"),
        ])


if __name__ == "__main__":
    unittest.main()
