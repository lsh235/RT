from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from es_rag_tuner import retrieval, reranker, server
from es_rag_tuner.es_client import Connection, ElasticsearchError


class R07RetrievalAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = Connection.from_payload({"url": "http://127.0.0.1:9200"})

    @staticmethod
    def response(*hits: dict) -> dict:
        return {"took": 1, "hits": {"total": {"value": len(hits)}, "hits": list(hits)}}

    def test_hybrid_uses_candidate_pool_then_returns_top_k_with_lane_evidence(self) -> None:
        lexical_hits = [
            {"_index": "docs-a", "_id": str(i), "_score": 10 - i, "_source": {"summary": f"bm {i}"}}
            for i in range(1, 5)
        ]
        vector_hits = [
            {"_index": "docs-a", "_id": str(i), "_score": 1 / i, "_source": {"summary": f"vec {i}"}}
            for i in range(2, 6)
        ]
        def lexical(connection, index, query_text, size, boosts, filters, source_fields):
            self.assertEqual(size, 4)
            return self.response(*lexical_hits), {"query": {"match_all": {}}}
        def vector(connection, index, query_text, size, filters, source_fields, profile_id=None):
            self.assertEqual(size, 4)
            return self.response(*vector_hits), {"k": size, "profile_id": "profile-x", "model": "model-x",
                                                   "dimensions": 3, "recipe": {}}
        with (patch.object(retrieval, "_lexical_search", side_effect=lexical),
              patch.object(retrieval, "_vector_search", side_effect=vector),
              patch.object(retrieval, "count_vectors", return_value=5)):
            result = retrieval.search(self.connection, "docs-alias", "needle", 2, {"summary": 2.0},
                                      mode="hybrid", candidate_pool=4, rank_constant=30)
        self.assertEqual(len(result["hits"]), 2)
        self.assertEqual(result["query"]["candidate_pool"], 4)
        self.assertEqual(result["query"]["size"], 2)
        self.assertEqual(result["query"]["rank_constant"], 30)
        self.assertIn("retrieval_ranks", result["hits"][0])
        self.assertIn("retrieval_scores", result["hits"][0])
        self.assertEqual(result["hits"][0]["retrieval_ranks"]["rrf"], 1)

    def test_top_k_and_candidate_pool_reject_malformed_or_out_of_range_values(self) -> None:
        for size, pool in ((0, 1), (51, 51), (True, 1), (2, 1), (2, 201), (2, "10")):
            with self.subTest(size=size, pool=pool), self.assertRaises(ElasticsearchError):
                retrieval.search(self.connection, "docs", "q", size, {}, candidate_pool=pool)

    def test_empty_rerank_does_not_load_optional_runtime(self) -> None:
        with patch.object(reranker, "_load", side_effect=AssertionError("must not load")):
            hits, metadata = reranker.rerank("query", [], 10)
        self.assertEqual(hits, [])
        self.assertEqual(metadata["candidate_count"], 0)
        self.assertEqual(metadata["elapsed_ms"], 0)

    def test_bm25_returns_top_k_with_raw_score_and_rank(self) -> None:
        hits = [{"_index": "docs-a", "_id": str(i), "_score": float(5 - i)} for i in range(1, 5)]
        with patch.object(retrieval, "_lexical_search", return_value=(self.response(*hits), {"query": {}})):
            result = retrieval.search(self.connection, "docs", "q", 2, {}, candidate_pool=4)
        self.assertEqual(len(result["hits"]), 2)
        self.assertEqual(result["hits"][1]["retrieval_ranks"]["bm25"], 2)
        self.assertEqual(result["hits"][0]["retrieval_scores"]["bm25"], 4.0)

    def test_code_rag_forwards_and_validates_shared_search_settings(self) -> None:
        handler = SimpleNamespace(
            _connection=lambda payload: self.connection,
            _index=lambda payload: "docs",
            _boosts=lambda payload: {"summary": 2.0},
            _filters=lambda payload: [],
        )
        issue_result = {"hits": [{"_id": "1"}], "mode": "hybrid"}
        with (patch.object(server, "retrieve", return_value=issue_result) as retrieve,
              patch.object(server.codebase, "search", return_value={"items": []}),
              patch.object(server.codebase, "compose_answer", return_value="answer")):
            response = server.WorkbenchHandler._code_rag(handler, {
                "query": "needle", "size": 7, "candidate_pool": 42,
                "rank_constant": 35, "rerank": True,
            })
        retrieve.assert_called_once()
        kwargs = retrieve.call_args.kwargs
        self.assertEqual(kwargs["mode"], "hybrid")
        self.assertEqual(kwargs["candidate_pool"], 42)
        self.assertEqual(kwargs["rank_constant"], 35)
        self.assertTrue(kwargs["rerank"])
        self.assertEqual(retrieve.call_args.args[3], 7)
        self.assertEqual(response["issues"], issue_result)

        for invalid in (
            {"size": 0}, {"size": 51}, {"size": True},
            {"size": 7, "candidate_pool": 6}, {"size": 7, "candidate_pool": 201},
            {"size": 7, "candidate_pool": "42"},
            {"rank_constant": 0}, {"rank_constant": 201}, {"rank_constant": "35"},
            {"rerank": "true"},
        ):
            with self.subTest(invalid=invalid), patch.object(server, "retrieve") as retrieve_invalid:
                with self.assertRaises(ElasticsearchError):
                    server.WorkbenchHandler._code_rag(handler, {"query": "needle", **invalid})
                retrieve_invalid.assert_not_called()


if __name__ == "__main__":
    unittest.main()
