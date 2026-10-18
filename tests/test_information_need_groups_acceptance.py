"""Cycle 11 acceptance for query variants grouped by information need.

The HTTP workflow uses a temporary SQLite database and synthetic records only.
Snapshot/export and preview checks mock the Elasticsearch boundary. It never
opens a configured customer index or reads credentials.

Run with:
  ./.venv/bin/python -m unittest discover -s tests -p 'test_information_need_groups_acceptance.py' -v
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
from pathlib import Path
from unittest import mock
from http.server import ThreadingHTTPServer

try:
    from tests.cycle37_auth_test_support import api_request, install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import api_request, install_auth_fixture


ROOT = Path(__file__).resolve().parents[1]
APP_PYTHON = os.environ.get("ES_RAG_ACCEPTANCE_PYTHON", str(ROOT / ".venv/bin/python"))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, method: str = "GET", body: object | None = None, timeout: float = 5):
    if method == "POST":
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        return api_request(f"{parsed.scheme}://{parsed.netloc}", parsed.path, body)
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"error": raw.decode("utf-8", errors="replace")}
        return exc.code, payload


class InformationNeedGroupsAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from es_rag_tuner import server
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", free_port()), server.WorkbenchHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        install_auth_fixture(self, self.base)

    def post(self, route: str, body: dict, expect: int = 200):
        status, payload = request(self.base + route, "POST", body)
        self.assertEqual(status, expect, f"{route} returned {status}: {payload}")
        return payload

    def concept(self, queries: list[dict] | None = None) -> dict:
        return {
            "id": "information-need-" + uuid.uuid4().hex[:12],
            "name": "Information need acceptance fixture",
            "corpus": {"index": "synthetic-index", "text_fields": ["body"]},
            "queries": queries or [
                {"id": "train-a", "query": "request recovery", "split": "train"},
                {"id": "train-b", "query": "resume a failed request", "split": "train"},
                {"id": "train-c", "query": "retry timeout", "split": "train"},
                {"id": "validation-a", "query": "backoff after timeout", "split": "validation"},
            ],
        }

    def save(self, concept: dict) -> dict:
        return self.post("/api/concepts/save", {"concept": concept})

    def judge(self, concept: dict, query_id: str, doc_id: str, rating: int | None):
        return self.post("/api/concepts/judge", {
            "concept_id": concept["id"], "query_id": query_id,
            "document_index": "synthetic-index", "document_id": doc_id,
            "rating": rating, "reason": "synthetic acceptance reason",
        })

    def test_legacy_queries_and_judgments_load_without_rewriting_concept(self):
        legacy = self.concept([
            {"id": "legacy-q", "query": "unchanged query", "split": "train"},
            {"id": "legacy-stale-q", "query": "another unchanged query", "split": "validation"},
        ])
        self.save(legacy)
        self.judge(legacy, "legacy-q", "doc-old", 2)
        self.judge(legacy, "legacy-stale-q", "doc-stale", 1)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "UPDATE judgments SET query_fingerprint='prior-query-version' WHERE concept_id=? AND query_id=?",
                (legacy["id"], "legacy-stale-q"),
            )
            db.commit()
            body_before = db.execute("SELECT body FROM concepts WHERE id=?", (legacy["id"],)).fetchone()[0]
            schema_before = db.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            judgment_before = db.execute(
                "SELECT concept_id,query_id,document_index,document_id,rating,pinned,reason,query_fingerprint "
                "FROM judgments WHERE concept_id=?", (legacy["id"],)
            ).fetchall()

        listed = self.post("/api/concepts/list", {})["concepts"]
        loaded = next(item for item in listed if item["id"] == legacy["id"])
        from es_rag_tuner import concepts as concept_store
        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}):
            judgments = concept_store._judgments(legacy["id"], legacy)
        with sqlite3.connect(self.db_path) as db:
            body_after = db.execute("SELECT body FROM concepts WHERE id=?", (legacy["id"],)).fetchone()[0]
            schema_after = db.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            judgment_after = db.execute(
                "SELECT concept_id,query_id,document_index,document_id,rating,pinned,reason,query_fingerprint "
                "FROM judgments WHERE concept_id=?", (legacy["id"],)
            ).fetchall()

        self.assertEqual(body_after, body_before)
        self.assertEqual(schema_after, schema_before)
        self.assertEqual(judgment_after, judgment_before)
        self.assertEqual([q["id"] for q in loaded["queries"]], ["legacy-q", "legacy-stale-q"])
        self.assertNotIn("information_need", loaded["queries"][0])
        self.assertEqual([row["query_id"] for row in judgments], ["legacy-q", "legacy-stale-q"])
        self.assertEqual([row["stale"] for row in judgments], [False, True])

    def test_group_normalization_independent_group_and_blank_singletons(self):
        concept = self.concept([
            {"id": "a", "query": "open incident", "split": "train", "information_need": "  Find\tincident   owner "},
            {"id": "b", "query": "who owns the incident", "split": "train", "information_need": "find incident owner"},
            {"id": "c", "query": "billing status", "split": "train", "information_need": "Billing"},
            {"id": "d", "query": "standalone phrasing", "split": "train", "information_need": "   "},
            {"id": "e", "query": "another standalone", "split": "train"},
        ])
        saved = self.save(concept)["concept"]
        q = {item["id"]: item for item in saved["queries"]}
        self.assertEqual(q["a"]["information_need"], "Find incident owner")
        self.assertEqual(q["b"]["information_need"], "find incident owner")
        self.assertNotIn("information_need", q["d"])
        self.assertNotIn("information_need", q["e"])
        readiness = self.post("/api/concepts/tune/readiness", {"concept": saved})
        counts = readiness["counts"]
        self.assertEqual(counts["training_information_need_groups"], 4)
        self.assertEqual(counts["validation_information_need_groups"], 0)

    def test_cross_split_group_rejected_without_changing_saved_version(self):
        original = self.concept([
            {"id": "a", "query": "find incident", "split": "train", "information_need": "incident owner"},
            {"id": "b", "query": "incident responsibility", "split": "train", "information_need": "incident owner"},
        ])
        saved = self.save(original)
        versions_before = self.post("/api/concepts/versions", {"concept_id": original["id"]})
        body_before = json.dumps(next(c for c in self.post("/api/concepts/list", {})["concepts"] if c["id"] == original["id"]), sort_keys=True)
        invalid = copy.deepcopy(original)
        invalid["queries"][1]["split"] = "validation"
        status, payload = request(self.base + "/api/concepts/save", "POST", {"concept": invalid})
        self.assertGreaterEqual(status, 400)
        self.assertRegex(payload.get("error", ""), r"묶음|split|학습용|별도 확인용")
        versions_after = self.post("/api/concepts/versions", {"concept_id": original["id"]})
        body_after = json.dumps(next(c for c in self.post("/api/concepts/list", {})["concepts"] if c["id"] == original["id"]), sort_keys=True)
        self.assertEqual(body_after, body_before)
        self.assertEqual(versions_after, versions_before)
        self.assertEqual(versions_before["versions"][0]["version_id"], saved["version_id"])

    def test_group_only_edit_preserves_judgments_and_fingerprint_but_query_edits_are_stale(self):
        original = self.concept([
            {"id": "q1", "query": "find the owner", "split": "train"},
            {"id": "q2", "query": "a separate query", "split": "train"},
        ])
        self.save(original)
        self.judge(original, "q1", "doc-graded", 2)
        from es_rag_tuner import concepts as concept_store
        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}):
            before = concept_store._judgments(original["id"], original)[0]
        grouped = copy.deepcopy(original)
        grouped["queries"][0]["information_need"] = "  incident   owner "
        self.save(grouped)
        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}):
            after_group = concept_store._judgments(grouped["id"], grouped)[0]
        self.assertEqual(after_group["query_fingerprint"], before["query_fingerprint"])
        self.assertFalse(after_group["stale"])
        edited_query = copy.deepcopy(grouped)
        edited_query["queries"][0]["query"] = "find another owner"
        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}):
            stale_query = concept_store._judgments(grouped["id"], edited_query)[0]
        self.assertTrue(stale_query["stale"])
        edited_split = copy.deepcopy(grouped)
        edited_split["queries"][0]["split"] = "validation"
        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}):
            stale_split = concept_store._judgments(grouped["id"], edited_split)[0]
        self.assertTrue(stale_split["stale"])

    def test_readiness_counts_groups_and_queries_without_adding_group_metrics(self):
        concept = self.concept([
            {"id": "t1", "query": "find issue owner", "split": "train", "information_need": "Issue owner"},
            {"id": "t2", "query": "who owns issue", "split": "train", "information_need": "issue owner"},
            {"id": "t3", "query": "find deployment status", "split": "train", "information_need": "Deployment status"},
            {"id": "v1", "query": "incident resolution", "split": "validation", "information_need": "Resolution"},
            {"id": "v2", "query": "resolve incident", "split": "validation", "information_need": "resolution"},
        ])
        saved = self.save(concept)["concept"]
        self.judge(saved, "t1", "positive", 2)
        self.judge(saved, "t2", "zero", 0)
        self.judge(saved, "v1", "validation-positive", 3)
        readiness = self.post("/api/concepts/tune/readiness", {"concept": saved})
        counts = readiness["counts"]
        self.assertTrue(readiness["eligible"])
        self.assertEqual(readiness["reason_code"], "train_positive_available")
        self.assertEqual((counts["training_queries"], counts["training_graded_queries"], counts["training_positive_queries"]), (3, 2, 1))
        self.assertEqual((counts["training_information_need_groups"], counts["training_graded_information_need_groups"], counts["training_positive_information_need_groups"]), (2, 1, 1))
        self.assertEqual((counts["validation_queries"], counts["validation_graded_queries"], counts["validation_positive_queries"]), (2, 1, 1))
        self.assertEqual((counts["validation_information_need_groups"], counts["validation_graded_information_need_groups"], counts["validation_positive_information_need_groups"]), (1, 1, 1))
        self.assertFalse(any("score" in key or "metric" in key for key in readiness))
        self.assertFalse(any("score" in key or "metric" in key for key in counts))

    def test_profile_and_run_exports_preserve_group_labels_and_membership(self):
        from es_rag_tuner import concepts as concept_store

        concept = self.concept([
            {"id": "q1", "query": "find outage owner", "split": "train", "information_need": "Outage owner"},
            {"id": "q2", "query": "who owns outage", "split": "train", "information_need": "outage owner"},
            {"id": "q3", "query": "status of deployment", "split": "validation", "information_need": "Deployment status"},
        ])
        saved = self.save(concept)["concept"]
        conn = object()
        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}), \
                mock.patch.object(concept_store, "_validate_search_fields", return_value={"fields": [{"name": "body"}]}):
            profile = concept_store.export_profile(conn, saved["id"])
            run_body = {
                "input_snapshot": {"concept": saved, "judgments": [], "queries": saved["queries"]},
                "output_snapshot": {"train": {"baseline": ["doc-1"], "tuned": ["doc-1"]}},
                "query": saved["queries"][0]["query"],
            }
            run_id = concept_store._store_run(saved["id"], "tune", run_body, run_id="synthetic-run-" + uuid.uuid4().hex[:8])
            exported = concept_store.export_run(saved["id"], run_id)
        profile_queries = profile["profile"]["concept"]["queries"]
        run_queries = exported["run"]["input_snapshot"]["concept"]["queries"]
        self.assertEqual(profile_queries, saved["queries"])
        self.assertEqual(run_queries, saved["queries"])
        self.assertEqual(exported["run"]["input_snapshot"]["queries"], saved["queries"])
        self.assertEqual([q["id"] for q in run_queries], ["q1", "q2", "q3"])

    def test_group_label_does_not_change_query_or_retrieval_request_results(self):
        from es_rag_tuner import concepts as concept_store

        concept = self.concept([{"id": "q1", "query": "find service owner", "split": "train"}])
        self.save(concept)
        grouped = copy.deepcopy(concept)
        grouped["queries"][0]["information_need"] = "service owner"
        self.save(grouped)
        schema = {"fields": [{"name": "body", "searchable": True, "filterable": False, "nested": False}]}
        es_hits = {"hits": {"total": {"value": 2}, "hits": [
            {"_index": "synthetic-index", "_id": "Doc-A", "_score": 2.0, "_source": {"body": "service owner"}},
            {"_index": "synthetic-index", "_id": "doc-a", "_score": 1.0, "_source": {"body": "owner contact"}},
        ]}}
        request_bodies = []

        def fake_request(_connection, _method, _path, body=None):
            request_bodies.append(copy.deepcopy(body))
            return copy.deepcopy(es_hits)

        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}), \
                mock.patch.object(concept_store, "_validate_search_fields", side_effect=lambda _c, c: (c.update(_field_metadata={"body": schema["fields"][0]}) or schema)), \
                mock.patch.object(concept_store, "_index_identity", return_value=({"available": False, "requested_index": "synthetic-index", "uuids": []}, None)), \
                mock.patch.object(concept_store, "request", side_effect=fake_request):
            before = concept_store.preview(object(), concept, query_id="q1")
            split_at = len(request_bodies)
            after = concept_store.preview(object(), grouped, query_id="q1")
        self.assertEqual(request_bodies[:split_at], request_bodies[split_at:])
        self.assertEqual([row["_id"] for row in before["candidate"]["hits"]], [row["_id"] for row in after["candidate"]["hits"]])
        self.assertEqual([row["_id"] for row in before["baseline"]["hits"]], [row["_id"] for row in after["baseline"]["hits"]])


if __name__ == "__main__":
    unittest.main()
