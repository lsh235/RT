"""Cycle 34 API acceptance using a temporary DB and synthetic Elasticsearch.

No test in this module connects to Elasticsearch or opens the user's profile.
The API is exercised over local HTTP; search responses are provided by mocks.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from es_rag_tuner import concepts, server
from es_rag_tuner.es_client import ElasticsearchError
try:
    from tests.cycle37_auth_test_support import install_auth_fixture, post_url
except ModuleNotFoundError:
    from cycle37_auth_test_support import install_auth_fixture, post_url


ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def post(url: str, payload: dict):
    return post_url(url, payload)


class ModeComparisonAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cycle34-mode-comparison-")
        cls.db_path = Path(cls.temp.name) / "synthetic.sqlite3"
        cls.db_env = mock.patch.dict(os.environ, {
            "ES_RAG_CONCEPT_DB": str(cls.db_path),
            "ES_RAG_ACCEPTANCE_ES_URL": "http://127.0.0.1:1",
        })
        cls.db_env.start()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", free_port()), server.WorkbenchHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls.db_env.stop()
        cls.temp.cleanup()

    def setUp(self):
        install_auth_fixture(self, self.base)
        self.concept = concepts.save_concept({
            "id": "cycle34-" + uuid.uuid4().hex[:10],
            "name": "Synthetic retry recovery",
            "description": "recover failed requests",
            "aliases": ["backoff"],
            "related": [],
            "corpus": {"index": "synthetic-alias", "text_fields": ["body"], "filter_fields": ["status"]},
            "filters": [{"field": "status", "value": "Open"}],
            "settings": {"mode": "bm25", "size": 3},
            "queries": [
                {"id": "train-q", "query": "saved retry query", "split": "train"},
                {"id": "validation-q", "query": "validation query", "split": "validation"},
            ],
        })["concept"]
        self.add_judgment("idx-a", "x", 3, pinned=True)
        self.add_judgment("idx-a", "y", 0)
        self.add_judgment("idx-b", "x", 2)
        self.add_judgment("idx-a", "u", None)
        self.add_judgment("idx-a", "stale", 3, fingerprint="stale-fingerprint")

    def add_judgment(self, index, doc_id, rating, *, pinned=False, fingerprint=None):
        query = self.concept["queries"][0]
        fingerprint = fingerprint if fingerprint is not None else concepts._query_judgment_fingerprint(query)
        with concepts._connect_db() as db:
            db.execute(
                "INSERT INTO judgments(concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at,query_fingerprint) VALUES(?,?,?,?,?,?,?,?,?)",
                (self.concept["id"], query["id"], index, doc_id, rating, int(pinned), "synthetic", "2026-10-18T00:00:00Z", fingerprint),
            )

    def snapshot_db(self):
        with __import__("sqlite3").connect(self.db_path) as db:
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                    for table in ("concepts", "concept_versions", "judgments", "runs")}

    def fields_ok(self, _connection, concept):
        concept["_field_metadata"] = {
            "body": {"name": "body", "searchable": True, "filterable": False, "nested": False, "source_field": "body"},
            "status": {"name": "status", "searchable": False, "filterable": True, "nested": False, "source_field": "status"},
        }
        concept["filters"] = concepts._normalize_filters(concept, concept["filters"])
        return {"fields": list(concept["_field_metadata"].values())}

    @staticmethod
    def bm25_response(hits=None, total=None):
        return {"timed_out": False, "_shards": {"failed": 0},
                "hits": {"total": {"value": 99, "relation": "eq"} if total is None else total,
                         "hits": hits if hits is not None else [
                             {"_index": "idx-a", "_id": "x"},
                             {"_index": "idx-a", "_id": "y"},
                             {"_index": "idx-b", "_id": "x"},
                         ]}}

    @staticmethod
    def vector_response(hits=None, total=None):
        return {"timed_out": False, "_shards": {"failed": 0},
                "hits": {"total": {"value": 12, "relation": "eq"} if total is None else total,
                         "hits": hits if hits is not None else [
                             {"_index": "idx-b", "_id": "x", "_score": 0.9, "_source": {"body": "positive"}},
                             {"_index": "idx-a", "_id": "u", "_score": 0.8, "_source": {"body": "unjudged"}},
                             {"_index": "idx-a", "_id": "y", "_score": 0.7, "_source": {"body": "zero"}},
                         ]}}

    def patched_dependencies(self, responses=None, *, embedding_error=None, mapping_error=None):
        calls = []
        responses = list(responses or [self.bm25_response(), self.vector_response()])

        def request(connection, method, path, body=None):
            calls.append((method, path, copy.deepcopy(body)))
            if not responses:
                raise AssertionError("unexpected Elasticsearch request")
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        def mapping(connection, index):
            if mapping_error:
                raise mapping_error
            return {"synthetic": True}, {"idx-a", "idx-b", "idx-a|idx-b"}

        context = (
            mock.patch.object(concepts, "_validate_search_fields", side_effect=self.fields_ok),
            mock.patch.object(concepts, "vector_mapping_targets", side_effect=mapping),
            mock.patch.object(concepts, "count_vectors", return_value=5),
            mock.patch.object(concepts, "request", side_effect=request),
        )
        for patcher in context:
            patcher.start()
            self.addCleanup(patcher.stop)
        embed_patcher = (mock.patch.object(concepts.embeddings, "embed_texts", side_effect=embedding_error)
                         if embedding_error else
                         mock.patch.object(concepts.embeddings, "embed_texts", return_value=[[0.01] * concepts.embeddings.MODEL_DIMENSIONS]))
        embed_patcher.start()
        self.addCleanup(embed_patcher.stop)
        return calls

    def request_comparison(self, *, payload=None, expect=200):
        body = {"connection": {"url": "http://127.0.0.1:1"}, "concept_id": self.concept["id"], "query_id": "train-q"}
        if payload:
            body.update(payload)
        return post(self.base + "/api/concepts/mode-comparison", body)

    def test_saved_query_authority_same_filter_scope_exact_identity_metrics_and_read_only(self):
        before = self.snapshot_db()
        calls = self.patched_dependencies()
        status, result = self.request_comparison(payload={
            "query": "attacker override", "index": "attacker-index", "filters": [], "size": 99,
            "model": "remote-model", "field": "attacker-vector", "query_dsl": {"match_all": {}},
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["query"], "saved retry query")
        self.assertEqual(result["split"], "train")
        self.assertEqual(result["index"], "synthetic-alias")
        self.assertEqual(result["settings_size"], 3)
        self.assertEqual(result["effective_filters"], [{"field": "status", "value": "Open"}])
        self.assertEqual(result["filters_fingerprint"], concepts._json_hash(result["effective_filters"]))
        self.assertTrue(result["judgments_applied_to_current_filters"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[0] == "POST" for call in calls))
        self.assertTrue(all(call[1].startswith("synthetic-alias/_search") for call in calls))
        self.assertTrue(all(call[1].endswith("allow_partial_search_results=false") for call in calls))
        self.assertEqual(calls[0][2]["size"], 3)
        self.assertEqual(calls[1][2]["size"], 3)
        self.assertEqual(calls[0][2]["query"]["bool"]["filter"], [{"term": {"status": "Open"}}])
        self.assertEqual(calls[1][2]["knn"]["filter"], {"bool": {"filter": [{"term": {"status": "Open"}}]}})
        self.assertEqual(calls[0][2]["query"]["bool"]["should"][0]["multi_match"]["query"], "saved retry query")
        self.assertEqual(result["metrics"]["concept_bm25"]["status"], "available")
        self.assertEqual(result["metrics"]["concept_bm25"]["judged_count"], 3)
        self.assertEqual(result["metrics"]["concept_bm25"]["positive_judged_count"], 2)
        self.assertEqual(result["metrics"]["concept_bm25"]["stale_judgment_count"], 1)
        self.assertEqual(result["metrics"]["concept_bm25"]["explicit_unjudged_count"], 1)
        self.assertEqual(result["metrics"]["concept_bm25"]["relevant_found_at_k"], 2)
        self.assertAlmostEqual(result["metrics"]["concept_bm25"]["recall_of_judged_relevant_at_k"], 1.0)
        ideal_dcg = 7 + 3 / __import__("math").log2(3)
        self.assertAlmostEqual(result["metrics"]["concept_bm25"]["ndcg_at_k"], 8.5 / ideal_dcg)
        self.assertEqual(result["metrics"]["e5_vector"]["retrieved_judged_count"], 2)
        self.assertEqual(result["metrics"]["e5_vector"]["unjudged_retrieved_count"], 1)
        self.assertAlmostEqual(result["metrics"]["e5_vector"]["judged_coverage_at_k"], 2 / 3)
        self.assertAlmostEqual(result["metrics"]["e5_vector"]["ndcg_at_k"], 3 / ideal_dcg)
        # The pinned positive remains graded, but pinning itself did not insert or rank it.
        self.assertEqual(result["metrics"]["e5_vector"]["relevant_found_at_k"], 1)
        self.assertTrue(result["vector"]["approximate"])
        self.assertFalse(result["vector"]["exhaustive"])
        self.assertEqual(result["vector"]["candidate_limit"], 3)
        self.assertEqual(self.snapshot_db(), before, "comparison must not change concept, versions, judgments, or runs")

    def test_delimiter_collision_pairs_remain_distinct(self):
        # These pairs collide under naive `index + '|' + id` keys.
        self.add_judgment("idx-a", "idx-b|x", 3)
        self.add_judgment("idx-a|idx-b", "x", 0)
        calls = self.patched_dependencies(responses=[
            self.bm25_response(hits=[{"_index": "idx-a", "_id": "idx-b|x"}], total={"value": 1, "relation": "eq"}),
            self.vector_response(hits=[{"_index": "idx-a|idx-b", "_id": "x", "_score": 0.8, "_source": {"body": "collision"}}], total={"value": 1, "relation": "eq"}),
        ])
        status, result = self.request_comparison()
        self.assertEqual(status, 200, result)
        bm25 = result["metrics"]["concept_bm25"]
        vector = result["metrics"]["e5_vector"]
        self.assertEqual(bm25["relevant_found_at_k"], 1)
        self.assertEqual(vector["relevant_found_at_k"], 0)
        self.assertEqual(bm25["judged_coverage_at_k"], 1.0)
        self.assertEqual(vector["judged_coverage_at_k"], 1.0)

    def test_rejects_missing_concept_and_query_ids_before_search(self):
        self.patched_dependencies()
        for payload in ({"concept_id": "missing", "query_id": "train-q"},
                        {"concept_id": self.concept["id"], "query_id": "missing"},
                        {"concept_id": "", "query_id": "train-q"},
                        {"concept_id": self.concept["id"], "query_id": ""}):
            with self.subTest(payload=payload):
                status, body = self.request_comparison(payload=payload)
                self.assertGreaterEqual(status, 400, body)
                self.assertIn("error", body)

    def test_failure_modes_are_atomic_and_never_report_partial_metrics(self):
        scenarios = [
            ("BM25 total missing", [self.bm25_response(total=None) | {"hits": {"hits": self.bm25_response()["hits"]["hits"]}}, self.vector_response()]),
            ("BM25 total malformed type", [self.bm25_response(total="many"), self.vector_response()]),
            ("BM25 total malformed object", [self.bm25_response(total={"value": "many", "relation": "eq"}), self.vector_response()]),
            ("BM25 relation unsupported", [self.bm25_response(total={"value": 99, "relation": "gte"}), self.vector_response()]),
            ("BM25 malformed hit", [self.bm25_response(hits=[{"_id": "no-index"}]), self.vector_response()]),
            ("BM25 total smaller than hits", [self.bm25_response(total={"value": 1, "relation": "eq"}), self.vector_response()]),
            ("BM25 timeout", [{**self.bm25_response(), "timed_out": True}, self.vector_response()]),
            ("BM25 shard failure", [{**self.bm25_response(), "_shards": {"failed": 1}}, self.vector_response()]),
            ("BM25 malformed response", [None, self.vector_response()]),
            ("vector total malformed type", [self.bm25_response(), self.vector_response(total="many")]),
            ("vector total malformed object", [self.bm25_response(), self.vector_response(total={"value": "many", "relation": "eq"})]),
            ("vector relation unsupported", [self.bm25_response(), self.vector_response(total={"value": 12, "relation": "gte"})]),
            ("vector total smaller than hits", [self.bm25_response(), self.vector_response(total={"value": 1, "relation": "eq"})]),
            ("vector malformed hit", [self.bm25_response(), self.vector_response(hits=[{"_index": "idx-a", "_id": "x", "_score": 0.4}])]),
            ("vector bad score", [self.bm25_response(), self.vector_response(hits=[{"_index": "idx-a", "_id": "x", "_score": float("nan"), "_source": {}}])]),
            ("vector unknown alias target", [self.bm25_response(), self.vector_response(hits=[{"_index": "not-an-alias-target", "_id": "x", "_score": 0.4, "_source": {}}])]),
            ("vector timeout", [self.bm25_response(), {**self.vector_response(), "timed_out": True}]),
            ("vector shard failure", [self.bm25_response(), {**self.vector_response(), "_shards": {"failed": 1}}]),
            ("vector malformed response", [self.bm25_response(), None]),
        ]
        for label, responses in scenarios:
            with self.subTest(label=label):
                before = self.snapshot_db()
                self.patched_dependencies(responses=responses)
                status, body = self.request_comparison()
                self.assertGreaterEqual(status, 400, (label, body))
                self.assertIn("error", body)
                self.assertNotIn("metrics", body)
                self.assertEqual(self.snapshot_db(), before)

    def test_uncached_model_missing_alias_and_connection_timeout_fail_closed_without_download(self):
        calls = self.patched_dependencies(embedding_error=RuntimeError("cached E5 model unavailable"))
        before = self.snapshot_db()
        status, body = self.request_comparison()
        self.assertGreaterEqual(status, 400, body)
        self.assertNotIn("metrics", body)
        self.assertEqual(len(calls), 1, "vector failure must stop before vector search")
        self.assertEqual(self.snapshot_db(), before)

        self.patched_dependencies(mapping_error=ElasticsearchError("alias has no compatible vector mapping"))
        status, body = self.request_comparison()
        self.assertGreaterEqual(status, 400, body)
        self.assertNotIn("metrics", body)

        calls = self.patched_dependencies(responses=[self.bm25_response(), TimeoutError("synthetic timeout")])
        status, body = self.request_comparison()
        self.assertGreaterEqual(status, 400, body)
        self.assertNotIn("metrics", body)
        self.assertEqual(self.snapshot_db(), before)

    def test_local_embedding_is_files_only_and_validation_split_is_not_aggregated(self):
        self.patched_dependencies()
        status, result = self.request_comparison(payload={"query_id": "validation-q"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["split"], "validation")
        self.assertEqual(result["query_id"], "validation-q")
        for metric in result["metrics"].values():
            self.assertEqual(metric["status"], "no_judgments")
            self.assertIsNone(metric["ndcg_at_k"])
            self.assertIsNone(metric["recall_of_judged_relevant_at_k"])
        # The endpoint reports one selected query only; it exposes no aggregate split metric.
        self.assertEqual(set(result["metrics"]), {"concept_bm25", "e5_vector"})
        embed_call = concepts.embeddings.embed_texts.call_args
        self.assertTrue(embed_call.kwargs["local_files_only"])

    def test_vector_approximate_hits_total_relation_gte_is_rejected(self):
        self.patched_dependencies(responses=[
            self.bm25_response(),
            self.vector_response(total={"value": 12, "relation": "gte"}),
        ])
        status, body = self.request_comparison()
        self.assertEqual(status, 503, body)
        self.assertIn("error", body)
        self.assertNotIn("metrics", body)


if __name__ == "__main__":
    unittest.main()
