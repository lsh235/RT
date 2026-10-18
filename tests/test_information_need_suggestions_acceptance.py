"""Cycle 12 acceptance for optional information-need suggestions.

This API-side check proves that free-text labels and blank labels continue to
round-trip without changing query identity or retrieval requests. Real-browser
interaction, native datalist keyboard behavior, and responsive layout are
recorded separately in docs/cycle12-information-need-suggestions-acceptance.md.

Run with:
  ./.venv/bin/python -m unittest discover -s tests -p 'test_information_need_suggestions_acceptance.py' -v

Only a temporary SQLite database, synthetic identifiers, and mocked search
responses are used; no configured Elasticsearch endpoint or credentials are
read.
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


class InformationNeedSuggestionsAcceptance(unittest.TestCase):
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

    def concept(self, queries: list[dict]) -> dict:
        return {
            "id": "suggestions-" + uuid.uuid4().hex[:12],
            "name": "Information need suggestions acceptance",
            "corpus": {"index": "synthetic-index", "text_fields": ["body"]},
            "queries": queries,
        }

    def test_selected_novel_and_blank_values_save_and_reload_exact_query_rows(self):
        concept = self.concept([
            {"id": "train-selected", "query": "  request recovery  ", "split": "train", "information_need": "  Service\towner  "},
            {"id": "train-novel", "query": "billing delay", "split": "train", "information_need": "Billing escalation <img src=x onerror=alert(1)>"},
            {"id": "validation-blank", "query": "check delayed invoice", "split": "validation", "information_need": "   "},
        ])
        saved = self.post("/api/concepts/save", {"concept": concept})["concept"]
        listed = self.post("/api/concepts/list", {})["concepts"]
        reloaded = next(item for item in listed if item["id"] == concept["id"])

        self.assertEqual(reloaded["queries"], [
            {"id": "train-selected", "query": "request recovery", "split": "train", "information_need": "Service owner"},
            {"id": "train-novel", "query": "billing delay", "split": "train", "information_need": "Billing escalation <img src=x onerror=alert(1)>"},
            {"id": "validation-blank", "query": "check delayed invoice", "split": "validation"},
        ])
        self.assertEqual(saved["queries"], reloaded["queries"])

    def test_label_only_edits_leave_query_freshness_and_mocked_retrieval_unchanged(self):
        from es_rag_tuner import concepts as concept_store

        concept = self.concept([
            {"id": "train-query", "query": "find service owner", "split": "train"},
            {"id": "validation-query", "query": "find service contact", "split": "validation"},
        ])
        self.post("/api/concepts/save", {"concept": concept})
        self.post("/api/concepts/judge", {
            "concept_id": concept["id"], "query_id": "train-query",
            "document_index": "synthetic-index", "document_id": "synthetic-doc",
            "rating": 2, "reason": "synthetic acceptance reason",
        })
        labeled = copy.deepcopy(concept)
        labeled["queries"][0]["information_need"] = "Service ownership"
        labeled["queries"][1]["information_need"] = "Support contact"
        self.post("/api/concepts/save", {"concept": labeled})

        schema = {"fields": [{"name": "body", "searchable": True, "filterable": False, "nested": False}]}
        es_hits = {"hits": {"total": {"value": 1}, "hits": [
            {"_index": "synthetic-index", "_id": "synthetic-doc", "_score": 1.0, "_source": {"body": "service owner"}},
        ]}}
        request_bodies = []

        def fake_request(_connection, _method, _path, body=None):
            request_bodies.append(copy.deepcopy(body))
            return copy.deepcopy(es_hits)

        with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)}), \
                mock.patch.object(concept_store, "_validate_search_fields", side_effect=lambda _c, c: (c.update(_field_metadata={"body": schema["fields"][0]}) or schema)), \
                mock.patch.object(concept_store, "_index_identity", return_value=({"available": False, "requested_index": "synthetic-index", "uuids": []}, None)), \
                mock.patch.object(concept_store, "request", side_effect=fake_request):
            before_judgment = concept_store._judgments(concept["id"], concept)[0]
            before = concept_store.preview(object(), concept, query_id="train-query")
            split_at = len(request_bodies)
            after_judgment = concept_store._judgments(labeled["id"], labeled)[0]
            after = concept_store.preview(object(), labeled, query_id="train-query")

        self.assertEqual(before_judgment["query_fingerprint"], after_judgment["query_fingerprint"])
        self.assertFalse(before_judgment["stale"])
        self.assertFalse(after_judgment["stale"])
        self.assertEqual(concept["queries"], [
            {"id": "train-query", "query": "find service owner", "split": "train"},
            {"id": "validation-query", "query": "find service contact", "split": "validation"},
        ])
        self.assertEqual(labeled["queries"][0]["id"], concept["queries"][0]["id"])
        self.assertEqual(labeled["queries"][0]["query"], concept["queries"][0]["query"])
        self.assertEqual(labeled["queries"][0]["split"], concept["queries"][0]["split"])
        self.assertEqual(request_bodies[:split_at], request_bodies[split_at:])
        self.assertEqual([row["_id"] for row in before["candidate"]["hits"]], [row["_id"] for row in after["candidate"]["hits"]])
        self.assertEqual([row["_id"] for row in before["baseline"]["hits"]], [row["_id"] for row in after["baseline"]["hits"]])


if __name__ == "__main__":
    unittest.main()
