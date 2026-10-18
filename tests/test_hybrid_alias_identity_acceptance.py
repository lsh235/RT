"""Synthetic acceptance tests for hybrid search identity across aliases.

These tests stub both Elasticsearch lanes and the vector count request. They
exercise the public retrieval.search(mode="hybrid") orchestration and RRF
merge without requiring a live cluster or embedding provider.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from es_rag_tuner import retrieval
from es_rag_tuner.es_client import Connection


class HybridAliasIdentityAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = Connection.from_payload({"url": "http://127.0.0.1:9200"})
        self.alias = "docs-alias"
        self.lexical_info = {"query": {"match": {"body": "needle"}}}
        self.vector_info = {"field": "rag_embedding", "dimensions": 3}

    @staticmethod
    def response(*hits: dict) -> dict:
        return {"took": 2, "hits": {"total": {"value": len(hits)}, "hits": list(hits)}}

    def run_hybrid(self, lexical_hits: list[dict], vector_hits: list[dict]) -> dict:
        def lexical(connection, index, query_text, size, boosts, filters, source_fields):
            self.assertEqual(index, self.alias)
            return self.response(*lexical_hits), self.lexical_info

        def vector(connection, index, query_text, size, filters, source_fields):
            self.assertEqual(index, self.alias)
            return self.response(*vector_hits), self.vector_info

        with (
            patch.object(retrieval, "_lexical_search", side_effect=lexical),
            patch.object(retrieval, "_vector_search", side_effect=vector),
            patch.object(retrieval, "count_vectors", return_value=17) as count_vectors,
        ):
            result = retrieval.search(
                self.connection,
                self.alias,
                "needle",
                size=10,
                boosts={"body": 1.0},
                mode="hybrid",
                rank_constant=60,
                source_fields=["body"],
            )
            count_vectors.assert_called_once_with(self.connection, self.alias)
        return result

    def test_same_id_from_distinct_concrete_indices_survives_rrf(self) -> None:
        result = self.run_hybrid(
            [{"_index": "docs-000001", "_id": "same", "_score": 4.0, "_source": {"body": "first"}}],
            [{"_index": "docs-000002", "_id": "same", "_score": 0.8, "_source": {"body": "second"}}],
        )

        self.assertEqual(result["total"], 2)
        self.assertEqual(
            {(hit["_index"], hit["_id"]) for hit in result["hits"]},
            {("docs-000001", "same"), ("docs-000002", "same")},
        )
        self.assertEqual(
            {hit["_index"]: hit["retrieval_scores"] for hit in result["hits"]},
            {
                "docs-000001": {"bm25": 4.0, "vector": None},
                "docs-000002": {"bm25": None, "vector": 0.8},
            },
        )

    def test_same_concrete_identity_fuses_once_with_both_lane_scores_and_rrf_rank(self) -> None:
        result = self.run_hybrid(
            [
                {"_index": "docs-000001", "_id": "shared", "_score": 9.0, "_source": {"body": "lexical"}},
                {"_index": "docs-000001", "_id": "lexical-only", "_score": 4.0, "_source": {"body": "lexical 2"}},
            ],
            [
                {"_index": "docs-000001", "_id": "shared", "_score": 0.9, "_source": {"body": "vector"}},
                {"_index": "docs-000001", "_id": "vector-only", "_score": 0.4, "_source": {"body": "vector 2"}},
            ],
        )

        self.assertEqual(result["total"], 3)
        self.assertEqual([hit["_id"] for hit in result["hits"]], ["shared", "lexical-only", "vector-only"])
        self.assertEqual(result["hits"][0]["retrieval_scores"], {"bm25": 9.0, "vector": 0.9})
        self.assertAlmostEqual(result["hits"][0]["_score"], 2 / 61)
        self.assertAlmostEqual(result["hits"][1]["_score"], 1 / 62)
        self.assertAlmostEqual(result["hits"][2]["_score"], 1 / 62)

    def test_missing_index_uses_the_existing_empty_index_fallback_consistently(self) -> None:
        result = self.run_hybrid(
            [{"_id": "legacy-hit", "_score": 3.0, "_source": {"body": "lexical"}}],
            [{"_id": "legacy-hit", "_score": 0.7, "_source": {"body": "vector"}}],
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["hits"][0]["_id"], "legacy-hit")
        self.assertNotIn("_index", result["hits"][0])
        self.assertEqual(result["hits"][0]["retrieval_scores"], {"bm25": 3.0, "vector": 0.7})
        self.assertAlmostEqual(result["hits"][0]["_score"], 2 / 61)


if __name__ == "__main__":
    unittest.main()
