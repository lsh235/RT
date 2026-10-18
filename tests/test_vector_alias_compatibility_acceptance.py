"""Synthetic acceptance for vector discovery through Elasticsearch aliases.

The fixture uses a disposable SQLite database, loopback workbench server, and
synthetic Elasticsearch endpoint. It never contacts a configured corpus or a
live cluster.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from unittest.mock import patch

from es_rag_tuner import embeddings, server as workbench_server
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
        with urlopen(request, timeout=4) as response:
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
    mappings: dict[str, dict[str, object]] = {}
    count = 2
    response: dict[str, object] = {}

    def log_message(self, *_args):
        pass

    def _send(self, status: int, payload: object):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _mapping_response(self):
        return {
            name: {"mappings": {"properties": properties}}
            for name, properties in type(self).mappings.items()
        }

    def do_HEAD(self):
        type(self).requests.append(("HEAD", urlsplit(self.path).path, None))
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        type(self).requests.append(("GET", path, None))
        if path == "/":
            self._send(200, {"cluster_name": "cycle14-synthetic", "version": {"number": "9.5.5"}, "tagline": "You Know, for Search"})
        elif path == "/_cat/indices":
            self._send(200, [{"index": name, "health": "green", "status": "open", "docs.count": "2", "store.size": "1kb"}
                             for name in type(self).mappings])
        elif path.endswith("/_mapping"):
            self._send(200, self._mapping_response())
        elif path.endswith("/_count"):
            self._send(200, {"count": type(self).count})
        else:
            self._send(404, {"error": "synthetic fixture route not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(("POST", self.path, body))
        if path.endswith("/_count"):
            self._send(200, {"count": type(self).count})
        elif path.endswith("/_search"):
            self._send(200, type(self).response)
        else:
            self._send(404, {"error": "synthetic fixture route not found"})


def vector_properties(*, dims=None, field_type="dense_vector", index=True,
                      element_type="float", similarity="cosine", index_options=None):
    mapping = {"type": field_type}
    if field_type == "dense_vector":
        mapping.update({"dims": dims or embeddings.MODEL_DIMENSIONS, "index": index,
                        "element_type": element_type, "similarity": similarity})
        if index_options is not None:
            mapping["index_options"] = index_options
    return {"title": {"type": "text"}, "body": {"type": "text"}, "rag_embedding": mapping}


class VectorAliasCompatibilityAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="es-rag-vector-alias-")
        cls.db_path = Path(cls.temp_dir.name) / "synthetic.sqlite3"
        cls.old_db = os.environ.get("ES_RAG_CONCEPT_DB")
        os.environ["ES_RAG_CONCEPT_DB"] = str(cls.db_path)
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
        SyntheticElasticsearch.requests = []
        SyntheticElasticsearch.mappings = {"docs-000001": vector_properties()}
        SyntheticElasticsearch.count = 2
        SyntheticElasticsearch.response = {
            "timed_out": False, "_shards": {"failed": 0},
            "hits": {"total": {"value": 1, "relation": "eq"}, "hits": [{
                "_index": "docs-000001", "_id": "same-id", "_score": 0.91,
                "_source": {"title": "Alias target", "body": "synthetic relevant evidence", "private": "not returned"},
            }]},
        }
        self.alias = "docs-current"
        self.concept = {
            "id": "alias-" + uuid.uuid4().hex[:10], "name": "Vector alias fixture",
            "corpus": {"index": self.alias, "title_field": "title", "text_fields": ["title", "body"], "filter_fields": []},
            "filters": [], "settings": {"size": 3, "mode": "bm25", "candidate_size": 11},
            "queries": [{"id": "saved-query", "query": "saved alias query", "split": "train"}],
        }
        status, payload = http_json(self.base + "/api/concepts/save", "POST", {"concept": self.concept})
        self.assertEqual(status, 200, payload)
        self.concept = payload["concept"]
        self.embedded_texts: list[tuple[list[str], str, bool]] = []
        self.embed_patch = patch.object(embeddings, "embed_texts", side_effect=self.fake_embed)
        self.embed_patch.start()

    def tearDown(self):
        self.embed_patch.stop()

    def fake_embed(self, texts, role, *, local_files_only=False):
        self.embedded_texts.append((list(texts), role, local_files_only))
        return [[0.0] * embeddings.MODEL_DIMENSIONS for _ in texts]

    def discover(self):
        return http_json(self.base + "/api/concepts/vector-candidates", "POST", {
            "connection": self.connection, "concept_id": self.concept["id"], "query_id": "saved-query",
        })

    def search_requests(self):
        return [(path, body) for method, path, body in SyntheticElasticsearch.requests
                if method == "POST" and urlsplit(path).path.endswith("/_search")]

    def test_single_target_alias_uses_alias_for_mapping_count_and_search_and_concrete_judgment_identity(self):
        status, _ = http_json(self.base + "/api/concepts/judge", "POST", {
            "concept_id": self.concept["id"], "query_id": "saved-query", "document_index": "docs-000001",
            "document_id": "same-id", "rating": 0, "pinned": True, "reason": "exact concrete identity",
        })
        self.assertEqual(status, 200)
        status, payload = self.discover()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["index"], self.alias)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["_index"], "docs-000001")
        self.assertEqual(candidate["_id"], "same-id")
        self.assertEqual(candidate["judgment"], {"rating": 0, "pinned": True, "reason": "exact concrete identity"})
        self.assertEqual(candidate["source"], {"title": "Alias target", "body": "synthetic relevant evidence"})
        self.assertEqual(self.embedded_texts, [(["saved alias query"], "query", True)])
        requested_paths = [urlsplit(path).path for method, path, _ in SyntheticElasticsearch.requests]
        self.assertIn(f"/{self.alias}/_mapping", requested_paths)
        self.assertIn(f"/{self.alias}/_count", requested_paths)
        search_path, body = self.search_requests()[0]
        self.assertIn(f"/{self.alias}/_search", search_path)
        self.assertEqual(urlsplit(search_path).query, "allow_partial_search_results=false")
        self.assertEqual(body["knn"]["field"], "rag_embedding")

    def test_max_inner_product_alias_is_accepted_and_search_remains_alias_bounded(self):
        SyntheticElasticsearch.mappings = {
            "docs-000001": vector_properties(similarity="max_inner_product"),
        }
        status, payload = self.discover()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["index"], self.alias)
        self.assertEqual(payload["candidates"][0]["_index"], "docs-000001")
        self.assertEqual(payload["candidates"][0]["_id"], "same-id")
        requested_paths = [urlsplit(path).path for method, path, _ in SyntheticElasticsearch.requests]
        self.assertIn(f"/{self.alias}/_mapping", requested_paths)
        self.assertIn(f"/{self.alias}/_count", requested_paths)
        search_path, body = self.search_requests()[0]
        self.assertEqual(urlsplit(search_path).path, f"/{self.alias}/_search")
        self.assertEqual(urlsplit(search_path).query, "allow_partial_search_results=false")
        self.assertEqual(body["knn"]["field"], "rag_embedding")
        self.assertEqual(len(body["knn"]["query_vector"]), embeddings.MODEL_DIMENSIONS)
        self.assertEqual(self.embedded_texts, [(["saved alias query"], "query", True)])

    def test_compatible_multi_target_alias_accepts_all_targets_and_preserves_same_id_per_index(self):
        SyntheticElasticsearch.mappings = {
            "docs-000001": vector_properties(),
            "docs-000002": vector_properties(),
        }
        SyntheticElasticsearch.response["hits"]["hits"] = [
            {"_index": "docs-000001", "_id": "duplicate-id", "_score": 0.9, "_source": {"title": "First", "body": "A"}},
            {"_index": "docs-000002", "_id": "duplicate-id", "_score": 0.8, "_source": {"title": "Second", "body": "B"}},
        ]
        SyntheticElasticsearch.response["hits"]["total"] = {"value": 2, "relation": "eq"}
        status, first = http_json(self.base + "/api/concepts/judge", "POST", {
            "concept_id": self.concept["id"], "query_id": "saved-query", "document_index": "docs-000001",
            "document_id": "duplicate-id", "rating": 1,
        })
        self.assertEqual(status, 200, first)
        status, payload = self.discover()
        self.assertEqual(status, 200, payload)
        self.assertEqual([(item["_index"], item["_id"]) for item in payload["candidates"]], [
            ("docs-000001", "duplicate-id"), ("docs-000002", "duplicate-id"),
        ])
        self.assertEqual(payload["candidates"][0]["judgment"]["rating"], 1)
        self.assertIsNone(payload["candidates"][1]["judgment"]["rating"])
        self.assertEqual(len(self.embedded_texts), 1)

    def test_incompatible_alias_targets_fail_before_embedding_or_candidate_search(self):
        cases = {
            "missing vector": {"title": {"type": "text"}, "body": {"type": "text"}},
            "wrong field type": vector_properties(field_type="keyword"),
            "wrong dimensions": vector_properties(dims=embeddings.MODEL_DIMENSIONS - 1),
            "unequal target dimensions": vector_properties(dims=embeddings.MODEL_DIMENSIONS + 1),
            "disabled indexing": vector_properties(index=False),
            "non-float elements": vector_properties(element_type="byte"),
            "similarity conflict": vector_properties(similarity="dot_product"),
            "index options conflict": vector_properties(index_options={"type": "hnsw", "m": 32, "ef_construction": 100}),
        }
        for label, incompatible in cases.items():
            with self.subTest(label=label):
                SyntheticElasticsearch.requests = []
                SyntheticElasticsearch.mappings = {
                    "docs-000001": vector_properties(), "docs-000002": incompatible,
                }
                self.embedded_texts.clear()
                status, payload = self.discover()
                self.assertGreaterEqual(status, 400, payload)
                self.assertIsInstance(payload.get("error"), str)
                self.assertTrue(payload["error"].strip())
                self.assertNotIn("candidates", payload)
                self.assertEqual(self.embedded_texts, [])
                self.assertEqual(self.search_requests(), [])

    def test_out_of_alias_target_hit_fails_closed(self):
        SyntheticElasticsearch.response["hits"]["hits"][0]["_index"] = "not-a-resolved-target"
        status, payload = self.discover()
        self.assertGreaterEqual(status, 400, payload)
        self.assertNotIn("candidates", payload)

    def test_concrete_index_behavior_and_api_health_mapping_contract_remain_available(self):
        self.concept["corpus"]["index"] = "docs-000001"
        status, saved = http_json(self.base + "/api/concepts/save", "POST", {"concept": self.concept})
        self.assertEqual(status, 200, saved)
        self.concept = saved["concept"]
        status, schema = http_json(self.base + "/api/corpus/schema", "POST", {
            "connection": self.connection, "index": "docs-current",
        })
        self.assertEqual(status, 200, schema)
        self.assertEqual(schema["index"], "docs-current")
        self.assertTrue(any(field["name"] == "title" for field in schema["fields"]))
        status, mapping = http_json(self.base + "/api/mapping", "POST", {
            "connection": self.connection, "index": "docs-current",
        })
        self.assertEqual(status, 200, mapping)
        self.assertTrue(mapping["has_rag_embedding_mapping"])
        status, connected = http_json(self.base + "/api/connect", "POST", {
            "connection": self.connection, "index": "docs-current",
        })
        self.assertEqual(status, 200, connected)
        self.assertEqual(connected["selected_index"], "docs-current")
        self.assertTrue(connected["embedding"]["mapping_available"])
        self.assertEqual(connected["embedding"]["mapping_dimensions"], embeddings.MODEL_DIMENSIONS)
        status, payload = self.discover()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["index"], "docs-000001")
        self.assertEqual(payload["candidates"][0]["_index"], "docs-000001")
        status, health = http_json(self.base + "/api/health")
        self.assertEqual(status, 200, health)
        self.assertTrue(health["ok"])


if __name__ == "__main__":
    unittest.main()
