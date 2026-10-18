"""Synthetic acceptance for the read-only vector candidate discovery route.

This suite uses a disposable SQLite file, loopback workbench server, and a
synthetic Elasticsearch endpoint. It never reads a configured corpus or
contacts a live cluster/provider.
"""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import tempfile
import threading
import time
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
    count = 2
    mapping_dimensions = embeddings.MODEL_DIMENSIONS
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

    def do_GET(self):
        path = urlsplit(self.path).path
        type(self).requests.append(("GET", path, None))
        if path.endswith("/_mapping"):
            self._send(200, {"synthetic-vector-index": {"mappings": {"properties": {
                "title": {"type": "text"}, "body": {"type": "text"},
                "tenant": {"type": "keyword"}, "priority": {"type": "integer"},
                "rag_embedding": {"type": "dense_vector", "dims": type(self).mapping_dimensions},
            }}}})
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


class VectorCandidateDiscoveryAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="es-rag-vector-candidates-")
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
        install_auth_fixture(self, self.base, es_url="http://127.0.0.1:1")
        SyntheticElasticsearch.requests = []
        SyntheticElasticsearch.count = 2
        SyntheticElasticsearch.mapping_dimensions = embeddings.MODEL_DIMENSIONS
        SyntheticElasticsearch.response = {
            "timed_out": False, "_shards": {"failed": 0},
            "hits": {"total": {"value": 1, "relation": "eq"}, "hits": [{
                "_index": "synthetic-vector-index", "_id": "vector-only-1", "_score": 0.91,
                "_source": {"title": "Vector-only target", "body": "synthetic relevant evidence",
                            "tenant": "tenant-a", "priority": 2, "secret": "must not leak"},
            }]},
        }
        self.concept = {
            "id": "vector-" + uuid.uuid4().hex[:10], "name": "Vector candidate fixture",
            "corpus": {"index": "synthetic-vector-index", "title_field": "title",
                       "text_fields": ["title", "body"], "filter_fields": ["tenant", "priority"]},
            "filters": [{"field": "tenant", "value": "tenant-a"}, {"field": "priority", "value": "2"}],
            "settings": {"size": 3, "mode": "bm25", "candidate_size": 11},
            "queries": [
                {"id": "train-query", "query": "saved synthetic query", "split": "train"},
                {"id": "validation-query", "query": "validation phrase", "split": "validation"},
            ],
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

    def discover(self, **extra):
        return http_json(self.base + "/api/concepts/vector-candidates", "POST", {
            "connection": self.connection, "concept_id": self.concept["id"], "query_id": "train-query", **extra,
        })

    def search_request(self):
        return next(body for method, path, body in SyntheticElasticsearch.requests
                    if method == "POST" and urlsplit(path).path.endswith("/_search"))

    def db_snapshot(self):
        with sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True) as db:
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in ("concepts", "concept_versions", "judgments", "runs")}

    def db_files_snapshot(self):
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.db_path.parent.iterdir() if path.is_file()}

    def test_vector_only_target_is_bounded_to_saved_query_and_explicitly_gradeable(self):
        before = self.db_snapshot()
        files_before = self.db_files_snapshot()
        status, payload = self.discover(index="attacker-index", query="caller query", dsl={"query": {"match_all": {}}},
                                        mode="hybrid", model="attacker-model", vector_field="secret",
                                        filters=[{"field": "secret", "value": "x"}], source_fields=["secret"], size=50)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["query_id"], "train-query")
        self.assertEqual(payload["query"], "saved synthetic query")
        self.assertEqual(payload["index"], "synthetic-vector-index")
        self.assertEqual(payload["mode"], "vector")
        self.assertEqual(payload["field"], "rag_embedding")
        self.assertEqual(payload["candidates"][0]["_id"], "vector-only-1")
        self.assertEqual(payload["candidates"][0]["rank"], 1)
        self.assertEqual(payload["candidates"][0]["_score"], 0.91)
        self.assertEqual(payload["candidates"][0]["source"], {
            "title": "Vector-only target", "body": "synthetic relevant evidence",
        })
        self.assertTrue(payload["candidates"][0]["source_sha256"])
        self.assertNotIn("must not leak", json.dumps(payload))
        self.assertEqual(self.embedded_texts, [(["saved synthetic query"], "query", True)])
        request = self.search_request()
        self.assertEqual(request["size"], 3)
        self.assertEqual(request["knn"]["k"], 3)
        self.assertEqual(request["knn"]["field"], "rag_embedding")
        self.assertEqual(request["_source"], ["title", "body"])
        self.assertEqual(request["knn"]["filter"]["bool"]["filter"], [
            {"term": {"tenant": "tenant-a"}}, {"term": {"priority": 2}},
        ])
        search_url = next(path for method, path, _ in SyntheticElasticsearch.requests
                          if method == "POST" and urlsplit(path).path.endswith("/_search"))
        self.assertEqual(urlsplit(search_url).query, "allow_partial_search_results=false")
        encoded = json.dumps(request)
        for forbidden in ("attacker-index", "caller query", "match_all", "attacker-model", "secret"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(self.db_snapshot(), before)
        self.assertEqual(self.db_files_snapshot(), files_before)
        self.assertFalse(any(path.endswith(("_bulk", "_doc", "_update", "_delete")) for _, path, _ in SyntheticElasticsearch.requests))

    def test_existing_exact_judgment_is_attached_but_null_and_zero_remain_distinct(self):
        for doc_id, rating in (("vector-only-1", 0), ("other-query", 2), ("other-index", 1)):
            body = {"concept_id": self.concept["id"], "query_id": "train-query" if doc_id != "other-query" else "validation-query",
                    "document_index": "other-index" if doc_id == "other-index" else "synthetic-vector-index",
                    "document_id": doc_id, "rating": rating, "pinned": doc_id == "vector-only-1", "reason": "synthetic"}
            status, _ = http_json(self.base + "/api/concepts/judge", "POST", body)
            self.assertEqual(status, 200)
        status, payload = self.discover()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["candidates"][0]["judgment"]["rating"], 0)
        self.assertTrue(payload["candidates"][0]["judgment"]["pinned"])
        self.assertEqual(payload["candidates"][0]["judgment"]["reason"], "synthetic")
        self.assertEqual(payload["candidates"][0]["_index"], "synthetic-vector-index")

    def test_empty_candidates_are_a_clean_empty_only_for_complete_response(self):
        SyntheticElasticsearch.response = {"timed_out": False, "_shards": {"failed": 0},
                                           "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}}
        status, payload = self.discover()
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["candidates"], [])

    def test_partial_malformed_or_overbounded_search_results_fail_closed(self):
        cases = [
            {"timed_out": True, "_shards": {"failed": 0}, "hits": {"hits": []}},
            {"timed_out": False, "_shards": {"failed": 1}, "hits": {"hits": []}},
            {"timed_out": False, "_shards": {"failed": False}, "hits": {"total": 1, "hits": []}},
            {"timed_out": False, "hits": {"hits": []}},
            {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": "malformed"}},
            {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": []}},
            {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": [
                {"_index": "synthetic-vector-index", "_id": str(i), "_source": {"title": str(i)}} for i in range(4)
            ]}},
        ]
        for response in cases:
            with self.subTest(response=response):
                SyntheticElasticsearch.response = response
                status, payload = self.discover()
                self.assertGreaterEqual(status, 400, payload)
                self.assertNotIn("candidates", payload)

    def test_no_vectors_and_embedding_failure_fail_closed(self):
        SyntheticElasticsearch.count = 0
        status, payload = self.discover()
        self.assertGreaterEqual(status, 400, payload)
        self.assertNotIn("candidates", payload)
        self.assertEqual(self.embedded_texts, [])
        SyntheticElasticsearch.count = 1
        with patch.object(embeddings, "embed_texts", side_effect=RuntimeError("synthetic embedding error")):
            status, payload = self.discover()
        self.assertGreaterEqual(status, 400, payload)
        self.assertNotIn("candidates", payload)

    def test_missing_or_wrong_vector_dimensions_fail_closed(self):
        SyntheticElasticsearch.mapping_dimensions = embeddings.MODEL_DIMENSIONS - 1
        status, payload = self.discover()
        self.assertGreaterEqual(status, 400, payload)
        self.assertNotIn("candidates", payload)
        SyntheticElasticsearch.mapping_dimensions = embeddings.MODEL_DIMENSIONS
        with patch.object(embeddings, "embed_texts", return_value=[[0.0] * (embeddings.MODEL_DIMENSIONS - 1)]):
            status, payload = self.discover()
        self.assertGreaterEqual(status, 400, payload)
        self.assertNotIn("candidates", payload)

    def test_missing_local_embedding_model_does_not_trigger_download(self):
        self.embed_patch.stop()
        with patch.object(embeddings, "_model", side_effect=RuntimeError("synthetic local cache miss")) as model_loader:
            status, payload = self.discover()
        self.assertGreaterEqual(status, 400, payload)
        self.assertNotIn("candidates", payload)
        self.assertEqual(self.embedded_texts, [])
        model_loader.assert_called_once_with(local_files_only=True)

    def test_embed_texts_propagates_local_only_to_fastembed_loader(self):
        self.embed_patch.stop()
        class Model:
            @staticmethod
            def embed(inputs, batch_size):
                self.assertEqual(inputs, ["query: saved synthetic query"])
                self.assertEqual(batch_size, 32)
                return [[1.0] + [0.0] * (embeddings.MODEL_DIMENSIONS - 1)]

        with patch.object(embeddings, "_model", return_value=Model()) as model_loader:
            result = embeddings.embed_texts(["saved synthetic query"], "query", local_files_only=True)
        model_loader.assert_called_once_with(local_files_only=True)
        self.assertEqual(len(result[0]), embeddings.MODEL_DIMENSIONS)


if __name__ == "__main__":
    unittest.main()
