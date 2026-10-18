"""Synthetic HTTP acceptance for locating a saved concept document by text.

Uses a disposable SQLite database, a synthetic Elasticsearch HTTP service, and
independently allocated loopback ports. It never contacts Elasticsearch or a
provider outside this fixture.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from es_rag_tuner import server as workbench_server
from es_rag_tuner.es_client import ElasticsearchError
try:
    from tests.cycle37_auth_test_support import api_request, install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import api_request, install_auth_fixture
try:
    from tests.cycle37_auth_test_support import install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import install_auth_fixture


ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(url: str, method: str = "GET", body: object | None = None):
    parsed = urlsplit(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if method == "POST":
        try:
            return api_request(base, parsed.path, body)
        except AssertionError:
            pass
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method=method,
                  headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urlopen(req, timeout=3) as response:
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
    next_search: dict[str, object] = {"hits": {"hits": []}, "timed_out": False, "_shards": {"failed": 0}}
    search_status = 200
    search_delay = 0.0

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
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "body": {"type": "text"},
                "comments": {"type": "nested", "properties": {"text": {"type": "text"}}},
                "private_note": {"type": "text"},
                "tenant": {"type": "keyword"},
            }}}})
        else:
            self._send(404, {"error": "synthetic fixture route not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(("POST", path, body))
        if not path.endswith("/_search"):
            self._send(404, {"error": "synthetic fixture route not found"})
            return
        if type(self).search_delay:
            time.sleep(type(self).search_delay)
        self._send(type(self).search_status, type(self).next_search)


class DocumentLookupAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = __import__("tempfile").TemporaryDirectory(prefix="es-rag-document-lookup-")
        cls.db_path = Path(cls.temp_dir.name) / "synthetic.sqlite3"
        cls.old_db = os.environ.get("ES_RAG_CONCEPT_DB")
        os.environ["ES_RAG_CONCEPT_DB"] = str(cls.db_path)

        SyntheticElasticsearch.requests = []
        SyntheticElasticsearch.next_search = {"hits": {"hits": []}, "timed_out": False, "_shards": {"failed": 0}}
        SyntheticElasticsearch.search_status = 200
        SyntheticElasticsearch.search_delay = 0.0
        cls.es = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticElasticsearch)
        cls.es_port = cls.es.server_address[1]
        cls.es_thread = threading.Thread(target=cls.es.serve_forever, daemon=True)
        cls.es_thread.start()

        cls.app = ThreadingHTTPServer(("127.0.0.1", 0), workbench_server.WorkbenchHandler)
        cls.app_port = cls.app.server_address[1]
        cls.app_thread = threading.Thread(target=cls.app.serve_forever, daemon=True)
        cls.app_thread.start()
        cls.base = f"http://127.0.0.1:{cls.app_port}"
        cls.connection = {"url": f"http://127.0.0.1:{cls.es_port}", "auth": {"type": "none"}}

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        cls.app_thread.join(timeout=2)
        cls.es.shutdown()
        cls.es.server_close()
        cls.es_thread.join(timeout=2)
        if cls.old_db is None:
            os.environ.pop("ES_RAG_CONCEPT_DB", None)
        else:
            os.environ["ES_RAG_CONCEPT_DB"] = cls.old_db
        cls.temp_dir.cleanup()

    def setUp(self):
        install_auth_fixture(self, self.base, es_url=f"http://127.0.0.1:{self.es_port}")
        SyntheticElasticsearch.requests.clear()
        SyntheticElasticsearch.next_search = {"hits": {"hits": []}, "timed_out": False, "_shards": {"failed": 0}}
        SyntheticElasticsearch.search_status = 200
        SyntheticElasticsearch.search_delay = 0.0
        self.concept = {
            "id": f"lookup-{time.time_ns()}", "name": "Saved recovery concept",
            "description": "synthetic acceptance fixture",
            "corpus": {"index": "saved-corpus", "title_field": "title",
                       "text_fields": ["title", "body", "comments.text"],
                       "filter_fields": ["tenant"]},
            "filters": [{"field": "tenant", "value": "saved-tenant"}],
            "settings": {"size": 10, "candidate_size": 10, "mode": "bm25"},
            "queries": [{"id": "saved-query-id", "query": "saved evaluation phrase", "split": "train"}],
        }
        status, payload = self.test_api.post("/api/concepts/save", {"concept": self.concept})
        self.assertEqual(status, 200, payload)
        self.concept = payload["concept"]

    def locate(self, **overrides):
        body = {"connection": self.connection, "concept_id": self.concept["id"],
                "text": "remembered locator phrase", **overrides}
        return self.test_api.post("/api/concepts/locate-document", body)

    @staticmethod
    def search_request():
        return next(body for method, path, body in SyntheticElasticsearch.requests
                    if method == "POST" and urlsplit(path).path.endswith("/_search"))

    def test_lookup_uses_saved_index_and_fields_with_fixed_bounded_request(self):
        status, payload = self.locate(
            index="attacker-index", fields=["private_note"], size=500,
            query={"match_all": {}}, dsl={"query": {"match_all": {}}},
        )
        self.assertEqual(status, 200, payload)
        request = self.search_request()
        self.assertEqual(request["size"], 10)
        self.assertEqual(request["from"], 0)
        self.assertIs(request["track_total_hits"], False)
        search_paths = [urlsplit(path).path for method, path, _ in SyntheticElasticsearch.requests if method == "POST"]
        self.assertEqual(search_paths, ["/saved-corpus/_search"])
        serialized = json.dumps(request, sort_keys=True)
        self.assertIn("title", serialized)
        self.assertIn("body", serialized)
        self.assertIn("comments.text", serialized)
        self.assertNotIn("private_note", serialized)
        self.assertNotIn("attacker-index", serialized)
        self.assertNotIn("saved-tenant", serialized)  # locator intentionally omits evaluation filters
        self.assertNotIn("saved evaluation phrase", serialized)  # locator phrase is separate from saved query
        self.assertNotIn("match_all", serialized)
        self.assertEqual(payload["candidates"], [])

    def test_legacy_profile_searches_configured_title_field_once(self):
        # Save normally, then model a historical stored profile that predates
        # the current save-time title_field/text_fields consistency check.
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT body FROM concepts WHERE id=?", (self.concept["id"],)).fetchone()
            stored = json.loads(row[0])
            stored["corpus"]["text_fields"].remove("title")
            db.execute("UPDATE concepts SET body=? WHERE id=?",
                       (json.dumps(stored, ensure_ascii=False), self.concept["id"]))

        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["fields"].count("title"), 1)
        self.assertIn("title", payload["fields"])
        self.assertIn("body", payload["fields"])
        self.assertIn("comments.text", payload["fields"])

        request = self.search_request()
        query = request["query"]
        multi_match_fields = []

        def collect_fields(value):
            if isinstance(value, dict):
                multi_match = value.get("multi_match")
                if isinstance(multi_match, dict):
                    multi_match_fields.extend(multi_match.get("fields", []))
                for child in value.values():
                    collect_fields(child)
            elif isinstance(value, list):
                for child in value:
                    collect_fields(child)

        collect_fields(query)
        self.assertCountEqual(multi_match_fields, ["title", "body", "comments.text"])

    def test_mapping_groups_nested_query_and_keeps_root_document_identity(self):
        SyntheticElasticsearch.next_search = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{
            "_index": "saved-corpus", "_id": "root-document-id", "_score": 2.5,
            "_nested": {"field": "comments", "_id": "nested-object-id"},
            "_source": {"title": "Recovery title", "body": "body excerpt", "comments": [{"text": "nested match"}],
                         "private_note": "must not leak", "tenant": "secret"},
        }]}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        request = self.search_request()
        rendered_query = json.dumps(request.get("query", {}), sort_keys=True)
        self.assertIn('"nested"', rendered_query)
        self.assertIn('"path": "comments"', rendered_query)
        self.assertEqual(len(payload["candidates"]), 1)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["document_id"], "root-document-id")
        self.assertNotEqual(candidate["document_id"], "nested-object-id")
        self.assertNotIn("private_note", json.dumps(payload))
        self.assertNotIn("secret", json.dumps(payload))
        self.assertFalse(candidate["excerpt_is_nested"])

    def test_candidate_display_is_bounded_and_only_selected_text_is_returned(self):
        long_value = "x" * 10000
        SyntheticElasticsearch.next_search = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{
            "_index": "saved-corpus", "_id": "root-id", "_score": None,
            "_source": {"title": long_value, "body": long_value, "private_note": "do-not-return"},
        }]}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        candidate = payload["candidates"][0]
        self.assertLessEqual(len(candidate["title"]), 600)
        self.assertLessEqual(len(candidate.get("excerpt") or ""), 600)
        self.assertNotIn("do-not-return", json.dumps(payload))

    def test_clean_empty_hits_are_zero_candidates(self):
        SyntheticElasticsearch.next_search = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": []}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["candidates"], [])

    def test_http_error_timeout_timed_out_and_failed_shards_are_not_zero_hits(self):
        cases = (
            (503, {"error": "synthetic unavailable"}, 503),
            (200, {"timed_out": True, "_shards": {"failed": 0}, "hits": {"hits": []}}, 502),
            (200, {"timed_out": False, "_shards": {"failed": 1}, "hits": {"hits": []}}, 502),
        )
        for es_status, response, expected_api_status in cases:
            with self.subTest(es_status=es_status, response=response):
                SyntheticElasticsearch.search_status = es_status
                SyntheticElasticsearch.next_search = response
                status, payload = self.locate()
                self.assertEqual(status, expected_api_status, payload)
                self.assertNotIn("candidates", payload)

    def test_malformed_or_partial_2xx_responses_are_not_zero_hits(self):
        responses = (
            {"_shards": {"failed": 0}, "hits": {"hits": []}},  # timed_out missing
            {"timed_out": None, "_shards": {"failed": 0}, "hits": {"hits": []}},
            {"timed_out": False, "hits": {"hits": []}},  # shard metadata missing
            {"timed_out": False, "_shards": {}, "hits": {"hits": []}},  # failed count missing
            {"timed_out": False, "_shards": {"failed": "unknown"}, "hits": {"hits": []}},
            {"timed_out": False, "_shards": {"failed": 0}},  # hits missing
            {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": {}}},
            {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{"_id": "id-only"}]}},
            {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{"_index": "saved-corpus"}]}},
        )
        for response in responses:
            with self.subTest(response=response):
                SyntheticElasticsearch.search_status = 200
                SyntheticElasticsearch.next_search = response
                status, payload = self.locate()
                self.assertGreaterEqual(status, 400, payload)
                self.assertNotIn("candidates", payload)

    def test_transport_timeout_is_an_api_error_not_a_zero_hit(self):
        mapping = {"saved-corpus": {"mappings": {"properties": {
            "title": {"type": "text"}, "body": {"type": "text"},
            "comments": {"type": "nested", "properties": {"text": {"type": "text"}}},
            "tenant": {"type": "keyword"},
        }}}}

        def timeout_after_mapping(_connection, method, _path, _body=None, **_kwargs):
            if method == "GET":
                return mapping
            raise ElasticsearchError("synthetic transport timeout")

        with patch("es_rag_tuner.concepts.request", side_effect=timeout_after_mapping):
            status, payload = self.locate()
        self.assertGreaterEqual(status, 400, payload)
        self.assertNotIn("candidates", payload)

    def test_too_long_locator_is_rejected_without_search(self):
        status, payload = self.locate(text="x" * 4001)
        self.assertGreaterEqual(status, 400)
        self.assertFalse(any(urlsplit(path).path.endswith("/_search") for _, path, _ in SyntheticElasticsearch.requests))

    def test_lookup_does_not_change_saved_query_or_create_judgment(self):
        status, _ = self.locate()
        self.assertEqual(status, 200)
        status, saved = http_json(self.base + "/api/concepts/list", "POST", {})
        self.assertEqual(status, 200, saved)
        current = next(item for item in saved["concepts"] if item["id"] == self.concept["id"])
        self.assertEqual(current["queries"], self.concept["queries"])
        with sqlite3.connect(self.db_path) as db:
            judgments = db.execute("SELECT COUNT(*) FROM judgments WHERE concept_id=?", (self.concept["id"],)).fetchone()[0]
        self.assertEqual(judgments, 0)

    def test_nested_only_match_does_not_claim_root_excerpt(self):
        self.concept["corpus"]["title_field"] = ""
        self.concept["corpus"]["text_fields"] = ["comments.text"]
        status, payload = http_json(self.base + "/api/concepts/save", "POST", {"concept": self.concept})
        self.assertEqual(status, 200, payload)
        self.concept = payload["concept"]
        SyntheticElasticsearch.next_search = {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [{
            "_index": "saved-corpus", "_id": "root-id", "_source": {"title": "unselected", "comments": [{"text": "nested result"}]}
        }]}}
        status, payload = self.locate()
        self.assertEqual(status, 200, payload)
        candidate = payload["candidates"][0]
        self.assertTrue(candidate["excerpt_is_nested"])
        self.assertIsNone(candidate["excerpt"])
        self.assertNotIn("unselected", json.dumps(payload))

    def test_ui_escapes_candidate_text_and_selection_does_not_grade_or_change_query(self):
        app_js = (ROOT / "es_rag_tuner/web/app.js").read_text(encoding="utf-8")
        render = app_js.split("function renderDocumentLocatorResults", 1)[1].split(
            "async function locateManualDocument", 1
        )[0]
        for value in ("candidate.title", "candidate.document_index", "candidate.document_id", "candidate.excerpt"):
            self.assertIn(f"escapeHtml({value}", render)
        selection = app_js.split("function selectLocatedDocument", 1)[1].split(
            "function populateIndexSuggestions", 1
        )[0]
        self.assertNotIn("/api/concepts/judge", selection)
        self.assertNotIn("manual-query-id", selection)

    def test_ui_clears_candidates_and_selected_target_on_scope_changes(self):
        app_js = (ROOT / "es_rag_tuner/web/app.js").read_text(encoding="utf-8")
        locator = app_js.split("async function locateManualDocument", 1)[1].split(
            "function selectLocatedDocument", 1
        )[0]
        self.assertIn(
            'api("/api/concepts/locate-document", { connection: getConnection(), concept_id: state.conceptId, text })',
            locator,
        )
        self.assertNotIn("index:", locator)
        self.assertNotIn("fields:", locator)
        self.assertNotIn("size:", locator)
        clear_state = app_js.split("function clearDocumentLocatorState", 1)[1].split(
            "function renderDocumentLocatorResults", 1
        )[0]
        for marker in (
            "state.locatorRequestId += 1", "state.manualDocumentIndex = null",
            "state.manualDocumentFromLocator", '"#manual-document-id"',
            '"#locate-document-results"', '"#manual-document-result"',
            '"#manual-document-diagnosis"',
        ):
            self.assertIn(marker, clear_state)

        self.assertIn('for (const selector of ["#es-url", "#es-user", "#es-password", "#es-api-key"])', app_js)
        self.assertIn('$(selector).addEventListener("input", clearDocumentLocatorState)', app_js)
        self.assertIn('$(selector).addEventListener("change", clearDocumentLocatorState)', app_js)
        for selector in ("#auth-type", "#index-name", "#concept-title-field", "#concept-text-fields", "#locate-document-text"):
            self.assertIn(f'$("{selector}").addEventListener(', app_js)
        self.assertIn('$("#auth-type").addEventListener("change", clearDocumentLocatorState)', app_js)
        self.assertIn('$("#index-name").addEventListener("input", clearDocumentLocatorState)', app_js)
        self.assertIn('$("#index-name").addEventListener("change", clearDocumentLocatorState)', app_js)
        self.assertIn('$("#concept-title-field").addEventListener("change", clearDocumentLocatorState)', app_js)
        self.assertIn('$("#concept-text-fields").addEventListener("change", clearDocumentLocatorState)', app_js)
        self.assertIn('$("#locate-document-text").addEventListener("input", clearDocumentLocatorState)', app_js)
        populate = app_js.split("function populateConcept(concept)", 1)[1].split("function ", 1)[0]
        self.assertIn("clearDocumentLocatorState()", populate)
        fill_example = app_js.split("function fillConceptExample()", 1)[1].split("function ", 1)[0]
        self.assertIn("clearDocumentLocatorState()", fill_example)
        connect = app_js.split("async function connect()", 1)[1].split("function ", 1)[0]
        self.assertIn("clearDocumentLocatorState()", connect)

        fetch_document = app_js.split("async function fetchManualDocument", 1)[1].split(
            "async function diagnoseManualDocument", 1
        )[0]
        self.assertIn('state.manualDocumentIndex || $("#index-name").value.trim()', fetch_document)
        diagnose = app_js.split("async function diagnoseManualDocument", 1)[1].split(
            "async function runConceptTune", 1
        )[0]
        self.assertIn('state.manualDocumentIndex || $("#index-name").value.trim()', diagnose)
        # A hand-entered known ID remains available after scope changes, but
        # its stale locator-derived index is discarded and current index wins.
        self.assertIn('$("#manual-document-id").addEventListener("input", () => { state.manualDocumentIndex = null; state.manualDocumentFromLocator = false;', app_js)

    def test_locator_layout_has_narrow_viewport_single_column_rules(self):
        css = (ROOT / "es_rag_tuner/web/style.css").read_text(encoding="utf-8")
        self.assertIn(
            "@media(max-width:600px){.locator-controls{grid-template-columns:1fr}"
            ".locator-candidate{grid-template-columns:1fr}"
            ".locator-candidate button{max-width:none;width:100%}}",
            css,
        )
