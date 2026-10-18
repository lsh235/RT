"""Synthetic HTTP acceptance for mapping-validated scalar match evidence.

The fixture uses a disposable SQLite database and synthetic Elasticsearch HTTP
service on dynamically allocated loopback ports. It never contacts a real
Elasticsearch cluster or provider.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from es_rag_tuner import server as workbench_server
try:
    from tests.cycle37_auth_test_support import api_request, install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import api_request, install_auth_fixture


def http_json(url: str, method: str = "GET", body: object | None = None):
    parsed = urlsplit(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if method == "POST":
        try:
            return api_request(base, parsed.path, body)
        except AssertionError:
            pass
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=data, method=method,
                      headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urlopen(request, timeout=3) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"error": raw.decode("utf-8", errors="replace")}
        return exc.code, payload


class SyntheticElasticsearch(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, object]] = []
    response: dict[str, object] = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": []}}

    def log_message(self, *_args):
        pass

    def _send(self, status: int, payload: object):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        type(self).requests.append(("GET", path, None))
        if path.endswith("/_mapping"):
            self._send(200, {"saved-corpus": {"mappings": {"properties": {
                "title": {"type": "text"}, "body": {"type": "text"},
                "summary": {"type": "text"}, "private_note": {"type": "text"},
                "comments": {"type": "nested", "properties": {"text": {"type": "text"}}},
                "tenant": {"type": "keyword"},
            }}}})
        else:
            self._send(404, {"error": "synthetic fixture route not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(("POST", path, body))
        if path.endswith("/_search"):
            self._send(200, type(self).response)
        else:
            self._send(404, {"error": "synthetic fixture route not found"})


class MatchEvidenceAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="es-rag-match-evidence-")
        cls.old_db = os.environ.get("ES_RAG_CONCEPT_DB")
        os.environ["ES_RAG_CONCEPT_DB"] = str(Path(cls.temp_dir.name) / "synthetic.sqlite3")
        SyntheticElasticsearch.requests = []
        SyntheticElasticsearch.response = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": []}}
        cls.es = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticElasticsearch)
        cls.es_thread = threading.Thread(target=cls.es.serve_forever, daemon=True)
        cls.es_thread.start()
        cls.app = ThreadingHTTPServer(("127.0.0.1", 0), workbench_server.WorkbenchHandler)
        cls.app_thread = threading.Thread(target=cls.app.serve_forever, daemon=True)
        cls.app_thread.start()
        cls.base = f"http://127.0.0.1:{cls.app.server_address[1]}"
        cls.connection = {"url": f"http://127.0.0.1:{cls.es.server_address[1]}", "auth": {"type": "none"}}

    @classmethod
    def tearDownClass(cls):
        for server, thread in ((cls.app, cls.app_thread), (cls.es, cls.es_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        if cls.old_db is None:
            os.environ.pop("ES_RAG_CONCEPT_DB", None)
        else:
            os.environ["ES_RAG_CONCEPT_DB"] = cls.old_db
        cls.temp_dir.cleanup()

    def setUp(self):
        install_auth_fixture(self, self.base, es_url=f"http://127.0.0.1:{self.es.server_address[1]}")
        SyntheticElasticsearch.requests.clear()
        SyntheticElasticsearch.response = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": []}}
        self.concept = {
            "id": f"evidence-{time.time_ns()}", "name": "Saved recovery concept",
            "description": "synthetic acceptance fixture",
            "corpus": {"index": "saved-corpus", "title_field": "title",
                       "text_fields": ["title", "body", "comments.text", "summary"],
                       "filter_fields": ["tenant"]},
            "filters": [{"field": "tenant", "value": "saved-tenant"}],
            "settings": {"size": 10, "candidate_size": 10, "mode": "bm25"},
            "queries": [{"id": "saved-query-id", "query": "saved evaluation phrase", "split": "train"}],
        }
        status, payload = http_json(self.base + "/api/concepts/save", "POST", {"concept": self.concept})
        self.assertEqual(status, 200, payload)
        self.concept = payload["concept"]

    def locate(self, **overrides):
        body = {"connection": self.connection, "concept_id": self.concept["id"],
                "text": "remembered locator phrase", **overrides}
        return http_json(self.base + "/api/concepts/locate-document", "POST", body)

    @staticmethod
    def search_request():
        return next(body for method, path, body in SyntheticElasticsearch.requests
                    if method == "POST" and urlsplit(path).path.endswith("/_search"))

    def test_highlight_request_is_scalar_only_finite_and_keeps_cycle9_scope(self):
        status, payload = self.locate(index="attacker-index", fields=["private_note"], size=500,
                                      highlight={"fields": {"private_note": {"no_match_size": 999999}}},
                                      dsl={"query": {"match_all": {}}})
        self.assertEqual(status, 200, payload)
        request = self.search_request()
        self.assertEqual(request["size"], 10)
        self.assertEqual(request["from"], 0)
        self.assertIs(request["track_total_hits"], False)
        highlights = request["highlight"]
        self.assertEqual(list(highlights["fields"]), ["title", "body", "summary"])
        for options in highlights["fields"].values():
            self.assertEqual(options["number_of_fragments"], 1)
            self.assertGreater(options["fragment_size"], 0)
            self.assertLessEqual(options["fragment_size"], 500)
            self.assertIs(options["require_field_match"], True)
            self.assertNotIn("no_match_size", options)
        encoded = json.dumps(request, sort_keys=True)
        self.assertNotIn("comments.text", json.dumps(highlights))
        self.assertNotIn("private_note", encoded)
        self.assertNotIn("no_match_size", encoded)
        self.assertNotIn("attacker-index", encoded)
        self.assertNotIn("saved-tenant", encoded)
        self.assertNotIn("saved evaluation phrase", encoded)
        self.assertNotIn("match_all", encoded)
        self.assertEqual(payload["fields"], ["title", "body", "comments.text", "summary"])

    def test_actual_nonfirst_scalar_highlight_is_the_only_excerpt_source(self):
        SyntheticElasticsearch.response = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{
            "_index": "saved-corpus", "_id": "doc-1", "_score": 1.0,
            "_source": {"title": "Title", "body": "body source decoy", "summary": "summary decoy",
                        "private_note": "private source decoy"},
            "highlight": {"body": ["<em>actual body evidence</em>"],
                          "summary": ["<em>actual summary evidence</em>"],
                          "private_note": ["unconfigured highlight decoy"]},
        }]}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["matched_fields"], ["body", "summary"])
        self.assertEqual(candidate["excerpt_field"], "body")
        self.assertEqual(candidate["excerpt"], "<em>actual body evidence</em>")
        self.assertNotIn("source decoy", candidate["excerpt"])
        self.assertNotIn("private source decoy", json.dumps(payload))
        self.assertNotIn("unconfigured highlight decoy", json.dumps(payload))

    def test_long_actual_fragment_is_capped_at_600_characters(self):
        fragment = "<em>" + ("x" * 1200) + "</em>"
        SyntheticElasticsearch.response = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{
            "_index": "saved-corpus", "_id": "doc-long-fragment", "_score": 0.8,
            "_source": {"title": "Long evidence"}, "highlight": {"body": [fragment]},
        }]}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["candidates"][0]["excerpt"]), 600)

    def test_candidate_without_scalar_highlight_has_empty_evidence_and_no_source_fallback(self):
        SyntheticElasticsearch.response = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{
            "_index": "saved-corpus", "_id": "doc-no-evidence", "_score": 0.5,
            "_source": {"title": "Candidate title", "body": "must not be fallback"},
        }]}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["candidates"]), 1)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["matched_fields"], [])
        self.assertIsNone(candidate["excerpt"])
        self.assertIsNone(candidate["excerpt_field"])
        self.assertNotIn("must not be fallback", json.dumps(payload))

    def test_nested_only_hit_never_uses_root_scalar_or_nested_excerpt(self):
        self.concept["corpus"]["title_field"] = ""
        self.concept["corpus"]["text_fields"] = ["comments.text"]
        status, payload = http_json(self.base + "/api/concepts/save", "POST", {"concept": self.concept})
        self.assertEqual(status, 200, payload)
        self.concept = payload["concept"]
        SyntheticElasticsearch.response = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{
            "_index": "saved-corpus", "_id": "nested-root", "_source": {"body": "root decoy", "comments": [{"text": "nested text"}]},
            "highlight": {"comments.text": ["nested highlight"]},
        }]}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["matched_fields"], [])
        self.assertIsNone(candidate["excerpt"])
        self.assertIsNone(candidate["excerpt_field"])
        self.assertTrue(candidate["excerpt_is_nested"])
        self.assertNotIn("root decoy", json.dumps(payload))
        self.assertNotIn("nested highlight", json.dumps(payload))
        request = self.search_request()
        self.assertNotIn("comments.text", request.get("highlight", {}).get("fields", {}))

    def test_ui_escapes_untrusted_highlight_text_and_preserves_selection_boundaries(self):
        app_js = (Path(__file__).resolve().parents[1] / "es_rag_tuner/web/app.js").read_text(encoding="utf-8")
        render = app_js.split("function renderDocumentLocatorResults", 1)[1].split(
            "async function locateManualDocument", 1
        )[0]
        for value in ("candidate.title", "candidate.document_index", "candidate.document_id", "candidate.excerpt_field"):
            self.assertIn(f"escapeHtml({value}", render)
        highlight_renderer = app_js.split("function renderLocatorHighlight", 1)[1].split(
            "function showToast", 1
        )[0]
        self.assertIn("escapeHtml(value)", highlight_renderer)
        self.assertIn('.replaceAll("&lt;em&gt;", "<mark>")', highlight_renderer)
        self.assertIn('.replaceAll("&lt;/em&gt;", "</mark>")', highlight_renderer)
        self.assertIn("renderLocatorHighlight(candidate.excerpt)", render)
        selection = app_js.split("function selectLocatedDocument", 1)[1].split(
            "function populateIndexSuggestions", 1
        )[0]
        self.assertNotIn("/api/concepts/judge", selection)
        self.assertNotIn("manual-query-id", selection)


if __name__ == "__main__":
    unittest.main()
