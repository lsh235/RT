"""Cycle 35 grouped mode-comparison acceptance.

Synthetic temporary SQLite and mocked Elasticsearch only. No profile, corpus,
credential, provider, or persistent search/write endpoint is used.
"""
from __future__ import annotations

import copy
import json
import math
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
try:
    from tests.cycle37_auth_test_support import install_auth_fixture, post_url
except ModuleNotFoundError:
    from cycle37_auth_test_support import install_auth_fixture, post_url


def _post(url, payload):
    return post_url(url, payload)


class GroupModeComparisonAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cycle35-group-comparison-")
        cls.db_path = Path(cls.temp.name) / "synthetic.sqlite3"
        cls.env = mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(cls.db_path), "ES_RAG_ACCEPTANCE_ES_URL": "http://127.0.0.1:1"})
        cls.env.start()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", port), server.WorkbenchHandler)
        cls.base = f"http://127.0.0.1:{port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.thread.join(timeout=5); cls.env.stop(); cls.temp.cleanup()

    def setUp(self):
        install_auth_fixture(self, self.base)
        self.concept = concepts.save_concept({
            "id": "cycle35-" + uuid.uuid4().hex[:10], "name": "Synthetic grouped need",
            "description": "synthetic", "aliases": [], "related": [],
            "corpus": {"index": "synthetic-alias", "text_fields": ["body"], "filter_fields": ["status"]},
            "filters": [{"field": "status", "value": "Open"}],
            "settings": {"mode": "bm25", "size": 2},
            "queries": [
                {"id": "q1", "query": "find retry owner", "split": "train", "information_need": " Retry   owner "},
                {"id": "q2", "query": "who owns recovery", "split": "train", "information_need": "retry owner"},
                {"id": "q3", "query": "recovery contact", "split": "train", "information_need": "RETRY OWNER"},
                {"id": "q4", "query": "validation retry contact", "split": "validation", "information_need": "other need"},
            ],
        })["concept"]
        # Current graded 0/null and stale positive. q2 has only a current positive.
        for qid, docid, rating, fp in [
            ("q1", "same", 3, None), ("q1", "zero", 0, None), ("q1", "unjudged", None, None),
            ("q1", "pinned", 3, None), ("q1", "stale", 3, "old-fingerprint"), ("q2", "same", 1, None),
            ("q4", "idx-a", 2, None),
        ]:
            query = next(q for q in self.concept["queries"] if q["id"] == qid)
            with concepts._connect_db() as db:
                db.execute("INSERT INTO judgments(concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at,query_fingerprint) VALUES(?,?,?,?,?,?,?,?,?)",
                           (self.concept["id"], qid, "idx-b" if qid == "q1" and docid == "same" else "idx-a", docid, 0 if qid == "q1" and docid == "same" else rating, 1 if docid == "pinned" else 0, "fixture", "2026-10-18T00:00:00Z", fp or concepts._query_judgment_fingerprint(query)))
            if qid == "q1" and docid == "same":
                with concepts._connect_db() as db:
                    db.execute("INSERT INTO judgments(concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at,query_fingerprint) VALUES(?,?,?,?,?,?,?,?,?)",
                               (self.concept["id"], qid, "idx-a", docid, 3, 0, "fixture", "2026-10-18T00:00:00Z", concepts._query_judgment_fingerprint(query)))

    def snapshot(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as db:
            return {t: db.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in ("concepts", "concept_versions", "judgments", "runs")}

    def _replace_saved_body(self, concept):
        """Install a controlled raw DB fixture that normal save validation rejects."""
        import sqlite3
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE concepts SET body=? WHERE id=?", (json.dumps(concept), concept["id"]))

    def _fields(self, _conn, concept):
        concept["_field_metadata"] = {
            "body": {"name": "body", "searchable": True, "filterable": False, "nested": False, "source_field": "body"},
            "status": {"name": "status", "searchable": False, "filterable": True, "nested": False, "source_field": "status"},
        }
        concept["filters"] = concepts._normalize_filters(concept, concept["filters"])
        return {"fields": list(concept["_field_metadata"].values())}

    @staticmethod
    def _response(ids):
        return {"timed_out": False, "_shards": {"failed": 0}, "hits": {"total": {"value": len(ids), "relation": "eq"}, "hits": [{"_index": i, "_id": d, "_score": 0.9, "_source": {"body": "synthetic"}} for i, d in ids]}}

    def _deps(self, fail_query=None):
        calls = []; seq = 0
        def req(_conn, method, path, body=None):
            nonlocal seq
            calls.append((method, path, copy.deepcopy(body)))
            # one BM25 and one vector response for every selected formulation
            qn = seq // 2 + 1; side = seq % 2; seq += 1
            if qn == fail_query and side == 0:
                raise concepts.ElasticsearchError("synthetic query failure")
            if side == 0:
                return self._response([("idx-a", "same"), ("idx-b", "same")])
            return self._response([("idx-b", "same"), ("idx-a", "same")])
        patchers = [
            mock.patch.object(concepts, "_validate_search_fields", side_effect=self._fields),
            mock.patch.object(concepts, "vector_mapping_targets", return_value=({}, {"idx-a", "idx-b"})),
            mock.patch.object(concepts, "count_vectors", return_value=10),
            mock.patch.object(concepts, "request", side_effect=req),
            mock.patch.object(concepts.embeddings, "embed_texts", return_value=[[0.01] * concepts.embeddings.MODEL_DIMENSIONS]),
        ]
        for p in patchers: p.start(); self.addCleanup(p.stop)
        return calls

    def call(self, payload=None):
        body = {"connection": {"url": "http://127.0.0.1:1"}, "concept_id": self.concept["id"], "query_id": "q1"}
        if payload: body.update(payload)
        return _post(self.base + "/api/concepts/mode-comparison-group", body)

    def test_normalized_group_saved_authority_equal_search_scope_and_no_writes(self):
        before = self.snapshot(); calls = self._deps()
        status, result = self.call({"query": "override", "information_need": "attacker", "query_ids": ["q4"], "filters": [], "size": 99, "model": "remote", "field": "evil", "query_dsl": {"match_all": {}}})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["information_need"].casefold(), "retry owner")
        self.assertEqual(result["split"], "train")
        self.assertEqual([row["query_id"] for row in result["queries"]], ["q1", "q2", "q3"])
        self.assertEqual((result["selected_count"], result["completed_count"], result["failed_count"]), (3, 3, 0))
        self.assertEqual(len(calls), 6)
        for method, path, body in calls:
            self.assertEqual(method, "POST"); self.assertTrue(path.startswith("synthetic-alias/_search"))
            self.assertEqual(body["size"], 2)
        for i in range(0, len(calls), 2):
            self.assertEqual(calls[i][2]["query"]["bool"]["filter"], [{"term": {"status": "Open"}}])
            self.assertEqual(calls[i+1][2]["knn"]["filter"], {"bool": {"filter": [{"term": {"status": "Open"}}]}})
        for metric in ("ndcg_at_k", "recall_of_judged_relevant_at_k"):
            for mode in ("concept_bm25", "e5_vector"):
                self.assertEqual(result["aggregate"][metric][mode]["query_count"], 2)
        for mode in ("concept_bm25", "e5_vector"):
            self.assertEqual(result["aggregate"]["judged_coverage_at_k"][mode]["query_count"], 2)
        # q1's pinned positive remains in the ideal judged set but is not
        # retrieved. q2 finds its sole positive in both modes. The vector
        # response's first identity is unjudged, so C34's condensed judged-only
        # nDCG omits it and leaves that positive at condensed rank 1.
        q1_idcg = 7 + 7 / math.log2(3)
        q1_bm25_ndcg = 7 / q1_idcg
        q1_vector_ndcg = (7 / math.log2(3)) / q1_idcg
        self.assertAlmostEqual(result["queries"][0]["metrics"]["concept_bm25"]["ndcg_at_k"], q1_bm25_ndcg)
        self.assertAlmostEqual(result["queries"][1]["metrics"]["concept_bm25"]["ndcg_at_k"], 1.0)
        q2_vector_ndcg = 1.0
        self.assertAlmostEqual(result["queries"][0]["metrics"]["e5_vector"]["ndcg_at_k"], q1_vector_ndcg)
        self.assertAlmostEqual(result["queries"][1]["metrics"]["e5_vector"]["ndcg_at_k"], q2_vector_ndcg)
        for mode in ("concept_bm25", "e5_vector"):
            self.assertAlmostEqual(result["aggregate"]["ndcg_at_k"][mode]["mean"],
                                   (q1_bm25_ndcg + 1.0) / 2 if mode == "concept_bm25"
                                   else (q1_vector_ndcg + q2_vector_ndcg) / 2)
            self.assertEqual(result["aggregate"]["ndcg_at_k"][mode]["query_count"], 2)
            self.assertAlmostEqual(result["aggregate"]["recall_of_judged_relevant_at_k"][mode]["mean"], 0.75)
            self.assertEqual(result["aggregate"]["recall_of_judged_relevant_at_k"][mode]["query_count"], 2)
            self.assertAlmostEqual(result["aggregate"]["judged_coverage_at_k"][mode]["mean"], 0.75)
            self.assertEqual(result["aggregate"]["judged_coverage_at_k"][mode]["query_count"], 2)
            for metric in ("ndcg_at_k", "recall_of_judged_relevant_at_k", "judged_coverage_at_k"):
                self.assertEqual(result["aggregate"][metric][mode]["selected_query_count"], 3)
        self.assertEqual(self.snapshot(), before)

    def test_exact_index_id_pairing_and_zero_null_stale_and_pin_semantics(self):
        calls = self._deps(); status, result = self.call()
        self.assertEqual(status, 200, result)
        row = result["queries"][0]
        metrics = row["metrics"]["concept_bm25"]
        self.assertEqual(metrics["explicit_unjudged_count"], 1)
        self.assertEqual(metrics["stale_judgment_count"], 1)
        self.assertEqual(metrics["judged_count"], 4)  # both same-ID indices, explicit zero, and pinned grade stay judged
        self.assertEqual(metrics["positive_judged_count"], 2)  # pinned positive stays graded
        self.assertEqual(metrics["relevant_found_at_k"], 1)
        self.assertEqual(metrics["retrieved_judged_count"], 2)
        self.assertEqual(metrics["positive_judged_count"] - metrics["relevant_found_at_k"], 1,
                         "the separately graded pinned positive is not injected into the ranking")
        self.assertEqual(row["metrics"]["e5_vector"]["relevant_found_at_k"], 1)
        self.assertEqual(row["metrics"]["e5_vector"]["positive_judged_count"], 2)
        self.assertEqual(row["metrics"]["e5_vector"]["positive_judged_count"] - row["metrics"]["e5_vector"]["relevant_found_at_k"], 1)
        self.assertNotEqual(metrics["ndcg_at_k"], row["metrics"]["e5_vector"]["ndcg_at_k"],
                            "same _id in different indices must retain its distinct grade and rank")
        self.assertEqual(len(calls), 6)

    def test_invalid_anchor_and_group_size_fail_before_any_search(self):
        calls = self._deps()
        for payload in ({"query_id": "missing"}, {"concept_id": "missing"}, {"query_id": "q4"}):
            status, body = self.call(payload)
            self.assertGreaterEqual(status, 400, body)
        self.assertEqual(calls, [])
        # 2 member group is valid; construct a singleton and an 11-member group.
        concept = copy.deepcopy(self.concept)
        concept["queries"] = [{"id": "single", "query": "one", "split": "train", "information_need": "alone"}]
        concepts.save_concept(concept)
        status, body = self.call({"query_id": "single"}); self.assertGreaterEqual(status, 400, body)
        concept["queries"] = [{"id": f"many-{i}", "query": f"q {i}", "split": "train", "information_need": "many"} for i in range(11)]
        concepts.save_concept(concept)
        status, body = self.call({"query_id": "many-0"}); self.assertGreaterEqual(status, 400, body)
        self.assertEqual(calls, [])

    def test_blank_and_mixed_split_saved_groups_fail_before_search(self):
        calls = self._deps()
        original = copy.deepcopy(self.concept)
        scenarios = [
            ("blank", [
                {"id": "blank-a", "query": "one", "split": "train", "information_need": "   "},
                {"id": "blank-b", "query": "two", "split": "train", "information_need": "\t"},
            ]),
            ("missing", [
                {"id": "missing-a", "query": "one", "split": "train"},
                {"id": "missing-b", "query": "two", "split": "train"},
            ]),
            ("mixed-split", [
                {"id": "mixed-a", "query": "one", "split": "train", "information_need": "same need"},
                {"id": "mixed-b", "query": "two", "split": "validation", "information_need": "Same   need"},
            ]),
        ]
        for label, queries in scenarios:
            with self.subTest(label=label):
                raw = copy.deepcopy(original)
                raw["queries"] = queries
                self._replace_saved_body(raw)
                before = self.snapshot()
                status, body = self.call({"query_id": queries[0]["id"]})
                self.assertGreaterEqual(status, 400, body)
                self.assertIn("error", body)
                self.assertEqual(calls, [], "invalid saved labels/splits must reject before search")
                self.assertEqual(self.snapshot(), before, "validation must not change saved tables")
    def test_partial_failure_preserves_safe_rows_and_suppresses_aggregate(self):
        before = self.snapshot(); calls = self._deps(fail_query=2)
        status, result = self.call()
        self.assertEqual(status, 200, result)
        self.assertEqual((result["selected_count"], result["completed_count"], result["failed_count"]), (3, 2, 1))
        self.assertIsNone(result["aggregate"])
        self.assertEqual(len(result["queries"]), 2)
        self.assertEqual([row["query_id"] for row in result["queries"]], ["q1", "q3"])
        for row in result["queries"]:
            self.assertEqual(set(row["metrics"]), {"concept_bm25", "e5_vector"},
                             "successful rows must be paired; failed members cannot have one-sided metrics")
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["query_id"], "q2")
        self.assertEqual(len(calls), 6, "the fixture attempts both retrieval sides for each selected query")
        self.assertEqual(self.snapshot(), before)

    def test_zero_metric_denominator_is_null(self):
        # A saved 2-query group with no current graded judgments still yields null aggregate metrics.
        concept = copy.deepcopy(self.concept)
        concept["queries"] = [{"id": "none-a", "query": "a", "split": "train", "information_need": "empty"}, {"id": "none-b", "query": "b", "split": "train", "information_need": "empty"}]
        self.concept = concepts.save_concept(concept)["concept"]
        before = self.snapshot()
        calls = self._deps(); status, result = self.call({"query_id": "none-a"})
        self.assertEqual(status, 200, result)
        for metric in result["aggregate"].values():
            for mode_metric in metric.values():
                self.assertIsNone(mode_metric["mean"])
                self.assertEqual(mode_metric["query_count"], 0)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(calls), 4)


if __name__ == "__main__": unittest.main()
