"""Cycle 17 acceptance for independent previews of one information need.

HTTP requests use a temporary SQLite database and an unreachable loopback URL.
The Elasticsearch boundary is mocked. The browser check is recorded in the
companion acceptance report and uses only intercepted synthetic API responses.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import sqlite3
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


class InformationNeedPreviewAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cycle17-information-need-")
        cls.db_path = Path(cls.temp.name) / "synthetic.sqlite3"
        cls._db_env = mock.patch.dict(os.environ, {
            "ES_RAG_CONCEPT_DB": str(cls.db_path),
            "ES_RAG_ACCEPTANCE_ES_URL": "http://127.0.0.1:1",
        })
        cls._db_env.start()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", free_port()), server.WorkbenchHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls._db_env.stop()
        cls.temp.cleanup()

    def setUp(self):
        install_auth_fixture(self, self.base)

    def send(self, payload: dict):
        return post(self.base + "/api/concepts/information-need-preview", payload)

    def make_concept(self, queries: list[dict] | None = None) -> dict:
        return {
            "id": "cycle17-" + uuid.uuid4().hex[:10],
            "name": "Synthetic incident recovery",
            "description": "retry timeout",
            "aliases": ["recovery"],
            "related": [{"term": "backoff", "weight": 1.4}],
            "corpus": {"index": "synthetic-index", "text_fields": ["body"], "filter_fields": ["tenant"]},
            "filters": [{"field": "tenant", "value": "alpha"}],
            "settings": {"size": 2, "candidate_size": 5, "mode": "bm25"},
            "queries": queries or [
                {"id": "train-a", "query": "recover request timeout", "split": "train", "information_need": "  Recover\tfailed requests  "},
                {"id": "train-b", "query": "resume after retry limit", "split": "train", "information_need": "recover failed requests"},
                {"id": "other", "query": "billing status", "split": "train", "information_need": "Billing status"},
                {"id": "validation", "query": "retry after outage", "split": "validation", "information_need": "Outage recovery"},
            ],
        }

    def save(self, concept: dict) -> dict:
        status, body = post(self.base + "/api/concepts/save", {"concept": concept})
        self.assertEqual(status, 200, body)
        return body["concept"]

    def query_rows(self, concept_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT body FROM concepts WHERE id=?", (concept_id,)).fetchone()
        return json.loads(row[0])["queries"]

    def run_rows(self, concept_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as db:
            return db.execute("SELECT id,kind,body FROM runs WHERE concept_id=? ORDER BY rowid", (concept_id,)).fetchall()

    @staticmethod
    def es_response(document_id: str):
        return {"hits": {"total": {"value": 1}, "hits": [{
            "_index": "synthetic-index", "_id": document_id, "_score": 1.0,
            "_source": {"body": "retry request recovery"},
        }]}}

    def mock_searches(self, captured: list):
        ids = ["doc-train-a", "doc-train-a", "doc-train-b", "doc-train-b"]
        def fake_request(connection, method, path, body=None):
            captured.append((connection, method, path, copy.deepcopy(body)))
            return self.es_response(ids[min(len(captured) - 1, len(ids) - 1)])
        return fake_request

    def test_group_uses_saved_canonical_label_excludes_other_groups_and_keeps_exact_query_grades(self):
        concept = self.save(self.make_concept())
        for query_id, doc_id, rating in (("train-a", "doc-train-a", 2), ("train-b", "doc-train-b", 0)):
            status, body = post(self.base + "/api/concepts/judge", {
                "concept_id": concept["id"], "query_id": query_id,
                "document_index": "synthetic-index", "document_id": doc_id,
                "rating": rating, "reason": "independent synthetic grade",
            })
            self.assertEqual(status, 200, body)
        calls = []
        with mock.patch.object(concepts, "_validate_search_fields", return_value={"fields": [{"name": "body", "searchable": True, "filterable": False, "nested": False}]}), \
                mock.patch.object(concepts, "_index_identity", return_value=({"available": False, "requested_index": "synthetic-index", "uuids": []}, None)), \
                mock.patch.object(concepts, "request", side_effect=self.mock_searches(calls)):
            status, result = self.send({
                "connection": {"url": "http://127.0.0.1:1"},
                "concept_id": concept["id"], "query_id": "train-a",
                # Unknown/caller-owned retrieval inputs must not override the saved record.
                "query": "ATTACKER QUERY", "concept": {"name": "untrusted"},
                "filters": [{"field": "tenant", "value": "attacker"}],
                "settings": {"size": 50},
            })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["information_need"], "Recover failed requests")
        self.assertEqual(result["split"], "train")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["count"], 2)
        self.assertEqual([row["query_id"] for row in result["results"]], ["train-a", "train-b"])
        self.assertEqual([row["query"] for row in result["results"]], ["recover request timeout", "resume after retry limit"])
        self.assertEqual([row["split"] for row in result["results"]], ["train", "train"])
        self.assertEqual([row["preview"]["candidate"]["hits"][0]["judgment"]["rating"] for row in result["results"]], [2, 0])
        self.assertEqual([row["preview"]["candidate"]["hits"][0]["judgment"]["reason"] for row in result["results"]], ["independent synthetic grade"] * 2)
        self.assertEqual(len(calls), 4, "two independent BM25 searches per saved query")
        self.assertTrue(all(call[2] == "synthetic-index/_search" for call in calls))
        self.assertTrue(all(call[3]["query"]["bool"]["filter"] == [{"term": {"tenant": "alpha"}}] for call in calls))
        self.assertTrue(all(call[0].url == "http://127.0.0.1:1" for call in calls))
        runs = self.run_rows(concept["id"])
        self.assertEqual(len(runs), 2)
        snapshots = [json.loads(row[2]) for row in runs]
        self.assertEqual([item["query_id"] for item in snapshots], ["train-a", "train-b"])
        self.assertEqual([item["effective_filters"] for item in snapshots], [[{"field": "tenant", "value": "alpha"}]] * 2)

    def test_blank_singleton_and_eleven_member_groups_reject_before_search_or_run_write(self):
        scenarios = [
            [{"id": "blank", "query": "standalone phrase", "split": "train", "information_need": "   "}],
            [{"id": "one", "query": "one member", "split": "train", "information_need": "solo"}],
            [{"id": f"q{i}", "query": f"synthetic formulation {i}", "split": "train", "information_need": "large group"} for i in range(11)],
        ]
        for queries in scenarios:
            with self.subTest(member_count=len(queries), label=queries[0].get("information_need")):
                concept = self.save(self.make_concept(queries))
                with mock.patch.object(concepts, "request", side_effect=AssertionError("validation must precede Elasticsearch")) as search:
                    status, body = self.send({"connection": {"url": "http://127.0.0.1:1"}, "concept_id": concept["id"], "query_id": queries[0]["id"]})
                self.assertGreaterEqual(status, 400, body)
                self.assertIn("error", body)
                search.assert_not_called()
                self.assertEqual(self.run_rows(concept["id"]), [])

    def test_validation_split_is_preserved_and_failure_is_not_reported_as_zero_hits(self):
        queries = [
            {"id": "val-a", "query": "outage recovery plan", "split": "validation", "information_need": "outage recovery"},
            {"id": "val-b", "query": "restore service after outage", "split": "validation", "information_need": "Outage   recovery"},
        ]
        concept = self.save(self.make_concept(queries))
        calls = []
        def alternating(*args, **kwargs):
            query_id = kwargs["query_id"]
            if query_id == "val-b":
                raise ElasticsearchError("synthetic search unavailable")
            concepts._store_run(concept["id"], "preview", {"query_id": query_id})
            return {"query_id": query_id, "candidate": {"hits": [{"_id": "synthetic-result"}]}}
        with mock.patch.object(concepts, "preview", side_effect=alternating) as preview:
            status, result = self.send({"connection": {"url": "http://127.0.0.1:1"}, "concept_id": concept["id"], "query_id": "val-a"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["split"], "validation")
        self.assertEqual([row["split"] for row in result["results"]], ["validation"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["results"][0]["preview"]["candidate"]["hits"], [{"_id": "synthetic-result"}])
        self.assertEqual(result["failures"], [{"query_id": "val-b", "query": "restore service after outage", "split": "validation", "error": "synthetic search unavailable"}])
        self.assertEqual(len(self.run_rows(concept["id"])), 1)
        preview.assert_has_calls([mock.call(mock.ANY, mock.ANY, query_id="val-a"), mock.call(mock.ANY, mock.ANY, query_id="val-b")])
        self.assertNotIn("metrics", result)
        self.assertNotIn("aggregate", result)

    def test_member_limit_is_enforced_at_ten_before_any_preview(self):
        queries = [{"id": f"q{i}", "query": f"phrase {i}", "split": "train", "information_need": "need"} for i in range(10)]
        concept = self.save(self.make_concept(queries))
        with mock.patch.object(concepts, "preview", side_effect=AssertionError("11-member group must reject first")) as preview:
            # Add an eleventh through a direct saved update to exercise the upper bound
            # even if normal validation later tightens the supported query count.
            changed = copy.deepcopy(concept)
            changed["queries"].append({"id": "q10", "query": "phrase 10", "split": "train", "information_need": "need"})
            concepts.save_concept(changed)
            status, body = self.send({"connection": {"url": "http://127.0.0.1:1"}, "concept_id": concept["id"], "query_id": "q0"})
        self.assertGreaterEqual(status, 400, body)
        preview.assert_not_called()
        self.assertEqual(self.run_rows(concept["id"]), [])

    def test_ten_member_group_is_inclusive_and_each_success_stores_its_own_run(self):
        queries = [{"id": f"q{i}", "query": f"phrase {i}", "split": "train", "information_need": "need"} for i in range(10)]
        concept = self.save(self.make_concept(queries))
        calls = []
        def successful_preview(_connection, _saved_concept, *, query_id):
            calls.append(query_id)
            concepts._store_run(concept["id"], "preview", {"query_id": query_id})
            return {"query_id": query_id, "candidate": {"hits": []}}
        with mock.patch.object(concepts, "preview", side_effect=successful_preview):
            status, result = self.send({"connection": {"url": "http://127.0.0.1:1"}, "concept_id": concept["id"], "query_id": "q0"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["count"], 10)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls, [f"q{i}" for i in range(10)])
        self.assertEqual(len(self.run_rows(concept["id"])), 10)

    def test_source_contract_keeps_member_cards_exact_query_judgments_and_stale_guards(self):
        app = (ROOT / "es_rag_tuner/web/app.js").read_text(encoding="utf-8")
        self.assertIn("/api/concepts/information-need-preview", app)
        self.assertIn("query_id: queryId", app)
        self.assertIn("informationNeedPreviewGeneration", app)
        action = app[app.index("function updateInformationNeedPreviewAction("):app.index("function collectConcept(")]
        self.assertIn("count >= 2 && count <= 10", action)
        self.assertIn("count > 10", action)
        self.assertIn("최대 10개", action)
        self.assertRegex(app, r"informationNeedPreviewGeneration[^;\n]*\+\+|\+\+[^;\n]*informationNeedPreviewGeneration")
        self.assertIn("result.query_id", app)
        self.assertIn("result.failures", app)
        self.assertRegex(app, r"partial|부분")
        self.assertRegex(app, r"별도.*기록|separate.*run|각.*미리보기")
        self.assertNotRegex(app, r"informationNeedPreview[^;\n]*(?:mean|average|precision|recall|nDCG|NDCG)")


if __name__ == "__main__":
    unittest.main()
