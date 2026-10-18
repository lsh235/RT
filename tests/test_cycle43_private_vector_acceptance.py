"""Cycle 43 private vector acceptance against disposable SQLite and fake HTTP ES.

Run with: python -m unittest tests.test_cycle43_private_vector_acceptance -v
No live Elasticsearch, model provider, credentials, or user knowledge are used.
"""
from __future__ import annotations

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
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from es_rag_tuner import auth, embeddings, es_client, knowledge, server, token_preview


PASSWORD = "Cycle43-offline-acceptance-password-001!"


class FakeVectorElasticsearch(BaseHTTPRequestHandler):
    indexes: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    calls: list[tuple[str, str, object]] = []
    fail_bulk = False
    search_responses: dict[str, list[dict]] = {}
    on_private_search = None

    def log_message(self, *_args):
        pass

    def _body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.headers.get("Content-Type", "").startswith("application/x-ndjson"):
            return raw.decode("utf-8")
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return raw.decode("utf-8", errors="replace")

    def _send(self, status=200, body=None):
        raw = json.dumps({} if body is None else body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        path = urlsplit(self.path).path.strip("/")
        body = self._body() if self.command in {"POST", "PUT"} else None
        type(self).calls.append((self.command, path, body))
        if path == "" and self.command == "GET":
            return self._send(200, {"cluster_name": "cycle43-fake", "version": {"number": "mock"}})
        if path.startswith("_cat/indices") and self.command == "GET":
            names = set(type(self).indexes) | set(type(self).aliases.values())
            return self._send(200, [{"index": name} for name in sorted(names)])
        if path.startswith("_alias/") and self.command == "GET":
            alias = path.split("/", 1)[1]
            target = type(self).aliases.get(alias)
            if not target:
                return self._send(404, {"error": {"reason": "alias missing"}})
            return self._send(200, {target: {"aliases": {alias: {}}}})
        if path.endswith("/_mapping") and self.command == "GET":
            name = path.rsplit("/", 1)[0]
            name = type(self).aliases.get(name, name)
            index = type(self).indexes.get(name)
            if not index:
                return self._send(404, {"error": {"reason": "index missing"}})
            return self._send(200, {name: index["mapping"]})
        if self.command == "PUT":
            type(self).indexes[path] = {"mapping": body, "documents": {}}
            return self._send(200, {"acknowledged": True})
        if path == "_bulk" and self.command == "POST":
            lines = [line for line in str(body or "").splitlines() if line]
            items = []
            for offset in range(0, len(lines), 2):
                metadata = json.loads(lines[offset])["index"]
                document = json.loads(lines[offset + 1])
                status = 400 if type(self).fail_bulk and offset == 0 else 201
                if status < 300:
                    type(self).indexes.setdefault(metadata["_index"], {"mapping": {}, "documents": {}})["documents"][metadata["_id"]] = document
                items.append({"index": {"_id": metadata["_id"], "status": status}})
            return self._send(200, {"errors": any(x["index"]["status"] >= 300 for x in items), "items": items})
        if path == "_aliases" and self.command == "POST":
            for action in body.get("actions", []):
                if "remove" in action:
                    item = action["remove"]
                    if type(self).aliases.get(item["alias"]) == item["index"]:
                        type(self).aliases.pop(item["alias"], None)
                if "add" in action:
                    item = action["add"]
                    type(self).aliases[item["alias"]] = item["index"]
            return self._send(200, {"acknowledged": True})
        if self.command == "DELETE":
            type(self).indexes.pop(path, None)
            return self._send(200, {"acknowledged": True})
        if self.command == "POST" and path.endswith("/_refresh"):
            return self._send(200, {"_shards": {"successful": 1, "failed": 0}})
        if self.command == "POST" and path.endswith("/_mget"):
            target = path.rsplit("/", 1)[0]
            concrete = type(self).aliases.get(target, target)
            docs = type(self).indexes.get(concrete, {}).get("documents", {})
            requested = (body or {}).get("docs", [])
            return self._send(200, {"docs": [
                {"_id": item.get("_id"), "found": item.get("_id") in docs,
                 **({"_source": docs[item.get("_id")]} if item.get("_id") in docs else {})}
                for item in requested
            ]})
        if self.command == "POST" and path.endswith("/_search"):
            target = path.rsplit("/", 1)[0]
            alias = target
            concrete = type(self).aliases.get(alias, alias)
            if alias.startswith("esrag-private-") and type(self).on_private_search:
                type(self).on_private_search()
            queue_key = "vector" if isinstance(body, dict) and "knn" in body else "bm25"
            queue = type(self).search_responses.get(queue_key)
            if queue:
                hits = queue.pop(0)
            else:
                docs = type(self).indexes.get(concrete, {}).get("documents", {})
                owner_filter = None
                if isinstance(body, dict):
                    owner_filter = (body.get("knn", {}).get("filter", {}).get("term", {}).get("owner_id")
                                    or body.get("query", {}).get("bool", {}).get("filter", [{}])[0].get("term", {}).get("owner_id"))
                hits = [{"_id": key, "_index": concrete, "_score": 0.5, "_source": value}
                        for key, value in docs.items() if owner_filter is None or value.get("owner_id") == owner_filter]
            return self._send(200, {"hits": {"total": {"value": len(hits)}, "hits": hits}})
        return self._send(200, {})

    do_GET = do_POST = do_PUT = do_DELETE = _handle


class Client:
    def __init__(self, base, username):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        status, session = self.request("/api/auth/session")
        if status != 200:
            raise AssertionError(f"session bootstrap failed: {status}")
        status, login = self.request("/api/auth/login", {"username": username, "password": PASSWORD}, csrf=session["csrf_token"])
        if status != 200:
            raise AssertionError(f"login failed: {status}: {login}")
        self.csrf = login["csrf_token"]

    def request(self, path, payload=None, *, method=None, csrf=None):
        method = method or ("POST" if payload is not None else "GET")
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {}
        if data is not None:
            headers.update({"Content-Type": "application/json", "Origin": self.base,
                            "X-CSRF-Token": csrf if csrf is not None else getattr(self, "csrf", "")})
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, json.loads(raw) if raw else {}

    def post(self, path, body):
        return self.request(path, body)


class Cycle43PrivateVectorAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); cls.app_port = sock.getsockname()[1]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); cls.es_port = sock.getsockname()[1]
        cls.temp = tempfile.TemporaryDirectory(prefix="cycle43-private-vector-")
        cls.env = mock.patch.dict(os.environ, {
            "ES_RAG_CONCEPT_DB": str(Path(cls.temp.name) / "shared.sqlite3"),
            "ES_RAG_ACCEPTANCE_ES_URL": f"http://127.0.0.1:{cls.es_port}",
        })
        cls.env.start()
        cls.es = ThreadingHTTPServer(("127.0.0.1", cls.es_port), FakeVectorElasticsearch)
        cls.es_thread = threading.Thread(target=cls.es.serve_forever, daemon=True); cls.es_thread.start()
        cls.app = ThreadingHTTPServer(("127.0.0.1", cls.app_port), server.WorkbenchHandler)
        cls.app_thread = threading.Thread(target=cls.app.serve_forever, daemon=True); cls.app_thread.start()
        cls.base = f"http://127.0.0.1:{cls.app_port}"
        auth.bootstrap_admin("cycle43-admin", "Cycle 43 Admin", PASSWORD)

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown(); cls.app.server_close(); cls.app_thread.join(timeout=5)
        cls.es.shutdown(); cls.es.server_close(); cls.es_thread.join(timeout=5)
        cls.env.stop(); cls.temp.cleanup()

    def setUp(self):
        FakeVectorElasticsearch.indexes = {}
        FakeVectorElasticsearch.aliases = {}
        FakeVectorElasticsearch.calls = []
        FakeVectorElasticsearch.fail_bulk = False
        FakeVectorElasticsearch.search_responses = {}
        FakeVectorElasticsearch.on_private_search = None
        self.users = []
        self.admin = Client(self.base, "cycle43-admin")
        self.addCleanup(self.cleanup_users)

    def cleanup_users(self):
        for path in self.users:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)

    def new_user(self):
        user = auth.create_account("cycle43-user-" + uuid.uuid4().hex[:8], "Cycle 43 User", PASSWORD)
        self.users.append(auth.state_database_path(user["id"]))
        return user, Client(self.base, user["username"])

    @property
    def connection(self):
        return {"url": f"http://127.0.0.1:{self.es_port}"}

    def save(self, client, title="Private guide", content="private procedure"):
        status, result = client.post("/api/knowledge/save", {"title": title, "content": content})
        self.assertEqual(status, 200, result)
        return result["document"]["document_id"]

    @staticmethod
    def ready_tokenizer():
        return {"available": True, "tokenizers_installed": True, "huggingface_hub_installed": True,
                "cached": True, "revision": token_preview.REVISION, "max_tokens": 512}

    @staticmethod
    def token_preview_stub(input_text):
        # Deterministic tokenizer stand-in: whitespace tokens, including the exact E5 role prefix.
        tokens = list(__import__("re").finditer(r"\S+\s*", input_text))
        if len(tokens) <= 512:
            return {"available": True, "truncated": False, "cut_char_offset": len(input_text), "max_tokens": 512}
        cut = tokens[511].end()
        return {"available": True, "truncated": True, "cut_char_offset": cut, "max_tokens": 512}

    def test_bm25_sync_and_search_work_without_optional_vector_runtime(self):
        _, client = self.new_user(); self.save(client, content="offline BM25 needle")
        with mock.patch.object(embeddings, "embed_texts", side_effect=AssertionError("BM25 must not load/embed")), \
                mock.patch.object(token_preview, "status", return_value={"available": False, "tokenizers_installed": False, "cached": False}):
            status, synced = client.post("/api/knowledge/es-sync", {"connection": self.connection})
            self.assertEqual(status, 200, synced)
            self.assertEqual(synced["vector_state"], "not_indexed")
            self.assertEqual(synced["vector_chunks"], 0)
            self.assertTrue(synced["tokenizer"])
            with mock.patch.object(server, "retrieve", return_value={"mode": "bm25", "hits": [], "total": 0,
                                                                       "query": {}, "took_ms": 1}):
                status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture",
                                                              "query": "offline BM25 needle", "mode": "bm25"})
            self.assertEqual(status, 200, result)
            self.assertEqual(result["private_knowledge"]["state"], "in_sync")
            self.assertEqual(result["private_knowledge"]["mode"], "bm25")
            self.assertTrue(any("rag_embedding" not in str(body) for method, _, body in FakeVectorElasticsearch.calls if method == "PUT"))

    def test_pre_cycle43_state_schema_migrates_with_safe_vector_defaults(self):
        owner, client = self.new_user()
        state_path = auth.state_database_path(owner["id"])
        with sqlite3.connect(state_path) as db:
            db.execute("CREATE TABLE knowledge_es_state (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, generation INTEGER NOT NULL, indexed_chunks INTEGER NOT NULL, local_fingerprint TEXT NOT NULL, synced_fingerprint TEXT NOT NULL, last_synced_at TEXT, error TEXT NOT NULL)")
            db.execute("INSERT INTO knowledge_es_state VALUES (1,'error',7,3,'legacy-local-fingerprint','legacy-synced-fingerprint','2026-10-17T00:00:00+00:00','legacy-safe-error')")
        status, result = client.request("/api/knowledge/es-status")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["vector_state"], "empty")
        self.assertEqual(result["vector_chunks"], 0)
        with sqlite3.connect(state_path) as db:
            row = dict(zip([item[1] for item in db.execute("PRAGMA table_info(knowledge_es_state)")], db.execute("SELECT * FROM knowledge_es_state WHERE id=1").fetchone()))
        self.assertEqual(row["generation"], 7)
        self.assertEqual(row["indexed_chunks"], 3)
        self.assertEqual(row["local_fingerprint"], "legacy-local-fingerprint")
        self.assertEqual(row["synced_fingerprint"], "legacy-synced-fingerprint")
        self.assertEqual(row["state"], "error")
        self.assertEqual(row["vector_state"], "not_indexed")
        self.assertEqual(row["vector_recipe"], "")
        self.assertEqual(row["vector_chunks"], 0)

    def test_vector_sync_requires_consent_and_stores_bounded_complete_passages_recipe_and_mapping(self):
        owner, client = self.new_user()
        long_text = " ".join(f"token{i}" for i in range(1300))
        self.save(client, content=long_text)
        status, denied = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection})
        self.assertEqual(status, 400, denied)
        self.assertIn("consent", denied.get("error", "").lower())
        self.assertFalse(any(method == "PUT" for method, _, _ in FakeVectorElasticsearch.calls))
        calls = []

        def embed(texts, role, *, local_files_only=False):
            calls.append((list(texts), role, local_files_only))
            return [[1.0] + [0.0] * 1023 for _ in texts]

        with mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "prepare", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", side_effect=embed):
            status, synced = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection,
                                                                            "allow_model_download": True,
                                                                            "owner_id": "forged-owner",
                                                                            "index": "esrag-private-" + "f" * 32})
        self.assertEqual(status, 200, synced)
        self.assertEqual(synced["vector_state"], "in_sync")
        self.assertEqual(synced["vector_chunks"], len(calls[0][0]))
        self.assertEqual(calls[0][1:], ("passage", False))
        passages = calls[0][0]
        self.assertGreater(len(passages), 1)
        indexed = FakeVectorElasticsearch.indexes[FakeVectorElasticsearch.aliases[synced["alias"]]]["documents"]
        by_chunk = {}
        for document in indexed.values():
            self.assertEqual(long_text[document["start_offset"]:document["end_offset"]], document["rag_chunk_text"])
            by_chunk.setdefault(document["chunk_id"], []).append(document)
        with sqlite3.connect(auth.state_database_path(owner["id"])) as db:
            source_chunks = {row[0]: row[1] for row in db.execute("SELECT id,content FROM knowledge_chunks")}
        self.assertEqual(set(by_chunk), set(source_chunks))
        for chunk_id, chunk_passages in by_chunk.items():
            ordered = sorted(chunk_passages, key=lambda item: item["passage_ordinal"])
            self.assertEqual("".join(item["rag_chunk_text"] for item in ordered), source_chunks[chunk_id])
            self.assertEqual([item["passage_ordinal"] for item in ordered], list(range(len(ordered))))
        self.assertTrue(all(len(text.split()) + 1 <= 512 for text in passages))
        self.assertEqual(embeddings.format_embedding_input("hello", "passage"), "passage: hello")
        self.assertEqual(embeddings.format_embedding_input("hello", "query"), "query: hello")
        expected_alias = "esrag-private-" + owner["id"].replace("-", "")
        self.assertEqual(synced["alias"], expected_alias)
        self.assertNotIn("f" * 32, str(FakeVectorElasticsearch.calls))
        mapping_body = next(body for method, name, body in FakeVectorElasticsearch.calls if method == "PUT")
        mapping = mapping_body["mappings"]
        field = mapping["properties"]["rag_embedding"]
        self.assertEqual(field, {"type": "dense_vector", "dims": 1024, "index": True, "similarity": "cosine"})
        self.assertEqual(mapping["_meta"]["private_vector_recipe"], synced["vector_recipe"])
        self.assertIn("fastembed_version", synced["vector_recipe"])
        self.assertTrue(synced["vector_recipe"]["fastembed_version"])
        indexed = FakeVectorElasticsearch.indexes[FakeVectorElasticsearch.aliases[expected_alias]]["documents"]
        self.assertEqual(len(indexed), len(passages))
        self.assertTrue(all(doc["owner_id"] == owner["id"] and len(doc["rag_embedding"]) == 1024 for doc in indexed.values()))

    def test_missing_tokenizer_or_embedding_runtime_fails_without_moving_prior_alias(self):
        owner, client = self.new_user(); self.save(client)
        status, initial = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, initial)
        alias = initial["alias"]; prior = FakeVectorElasticsearch.aliases[alias]
        with mock.patch.object(token_preview, "status", return_value={"available": False, "reason": "tokenizer missing"}), \
                mock.patch.object(token_preview, "prepare", return_value={"available": False, "reason": "tokenizer missing"}):
            status, failure = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection, "allow_model_download": True})
        self.assertEqual(status, 503, failure)
        self.assertEqual(FakeVectorElasticsearch.aliases[alias], prior)
        self.assertEqual(failure.get("error"), "tokenizer missing")
        with mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "prepare", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", side_effect=RuntimeError("model unavailable")):
            status, failure = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection, "allow_model_download": True})
        self.assertNotEqual(status, 200)
        self.assertEqual(FakeVectorElasticsearch.aliases[alias], prior)

    def test_partial_generation_failure_preserves_previous_alias_and_search_requires_current_vectors(self):
        _, client = self.new_user(); self.save(client)
        status, initial = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, initial)
        alias = initial["alias"]; prior = FakeVectorElasticsearch.aliases[alias]
        FakeVectorElasticsearch.fail_bulk = True
        with mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "prepare", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]):
            status, failure = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection, "allow_model_download": True})
        self.assertEqual(status, 503, failure)
        self.assertEqual(FakeVectorElasticsearch.aliases[alias], prior)
        FakeVectorElasticsearch.fail_bulk = False
        with mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0,
                                                                   "query": {}, "took_ms": 1}):
            status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture",
                                                          "query": "private", "mode": "vector"})
        self.assertEqual(status, 200, result)
        self.assertNotEqual(result["private_knowledge"]["state"], "in_sync")
        self.assertEqual(result["private_knowledge"]["results"], [])

    def test_vector_hybrid_owner_prefilters_and_shared_private_lanes_stay_separate(self):
        owner, client = self.new_user(); self.save(client, content="owner only marker")
        with mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "prepare", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]):
            status, synced = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection, "allow_model_download": True})
        self.assertEqual(status, 200, synced)
        target = FakeVectorElasticsearch.aliases[synced["alias"]]
        hit_a = {"_id": "shared-rank", "_index": target, "_score": 99, "_source": {"owner_id": owner["id"], "title": "A"}}
        hit_b = {"_id": "vector-rank", "_index": target, "_score": 1, "_source": {"owner_id": owner["id"], "title": "B"}}
        FakeVectorElasticsearch.search_responses = {"bm25": [[hit_a]], "vector": [[hit_b, hit_a]]}
        FakeVectorElasticsearch.calls = []
        query_inputs = []
        def inspect_query(text):
            query_inputs.append(text)
            return {"available": True, "truncated": False, "max_tokens": 512}
        shared = {"mode": "hybrid", "hits": [{"_id": "public", "_index": "shared-fixture", "_score": 7,
                                                   "_source": {"summary": "shared lane"}}], "total": 1,
                  "query": {"rank_constant": 60}, "took_ms": 1}
        with mock.patch.object(embeddings, "runtime_status", return_value={"runtime_installed": True, "model_cached": True}), \
                mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=inspect_query), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]) as embed_query, \
                mock.patch.object(server, "retrieve", return_value=shared):
            status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture",
                                                          "query": "query marker", "mode": "hybrid",
                                                          "owner_id": "forged-owner", "document_id": "forged-document"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["hits"], shared["hits"])
        private = result["private_knowledge"]
        self.assertEqual(private["state"], "in_sync")
        self.assertEqual(private["mode"], "hybrid")
        self.assertTrue(all(hit["_source"].get("owner_id") == owner["id"] for hit in private["results"]))
        self.assertEqual(embed_query.call_args.args[1], "query")
        self.assertIn("query: query marker", query_inputs)
        private_searches = [(body, path) for method, path, body in FakeVectorElasticsearch.calls
                            if method == "POST" and path.endswith("/_search") and isinstance(body, dict)
                            and ("knn" in body or "query" in body)]
        self.assertTrue(any("knn" in body and body["knn"]["filter"] == {"term": {"owner_id": owner["id"]}}
                            for body, _ in private_searches))
        self.assertTrue(any(body.get("query", {}).get("bool", {}).get("filter") == [{"term": {"owner_id": owner["id"]}}]
                            for body, _ in private_searches))
        self.assertTrue(all(path.startswith(synced["alias"] + "/") for _, path in private_searches))
        fused = private["results"][0]
        self.assertEqual(fused["_id"], "shared-rank")  # RRF puts the jointly ranked hit first.
        self.assertNotEqual(fused["_index"], result["hits"][0]["_index"])
        expected_rrf = 1 / (60 + 1) + 1 / (60 + 2)
        self.assertAlmostEqual(fused["_score"], expected_rrf)
        self.assertNotIn(fused["_score"], (99, 1))
        self.assertEqual(fused["retrieval_scores"], {"bm25": 99, "vector": 99})
        self.assertEqual(fused["lane_ranks"], {"bm25": 1, "vector": 2})
        FakeVectorElasticsearch.search_responses = {"bm25": [[hit_a]], "vector": [[hit_b, hit_a]]}
        with mock.patch.object(embeddings, "runtime_status", return_value={"runtime_installed": True, "model_cached": True}), \
                mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", return_value={"available": True, "truncated": False, "max_tokens": 512}), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]), \
                mock.patch.object(server, "retrieve", side_effect=es_client.ElasticsearchError("shared mapping/vector unavailable", 400)):
            status, unavailable = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture",
                                                                "query": "query marker", "mode": "hybrid"})
        self.assertEqual(status, 200, unavailable)
        self.assertEqual(unavailable["shared_search"]["state"], "unavailable")
        self.assertEqual(unavailable["hits"], [])
        self.assertEqual(unavailable["private_knowledge"]["state"], "in_sync")
        self.assertTrue(unavailable["private_knowledge"]["results"], "private hybrid should continue when shared retrieval fails")

    def test_vector_search_with_stale_generation_withholds_results(self):
        _, client = self.new_user(); document_id = self.save(client)
        with mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "prepare", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]):
            status, _ = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection, "allow_model_download": True})
        self.assertEqual(status, 200)
        self.assertEqual(client.post("/api/knowledge/save", {"document_id": document_id, "title": "changed", "content": "new content"})[0], 200)
        FakeVectorElasticsearch.search_responses = {"vector": [[{"_id": "must-not-return", "_source": {"title": "stale"}}]]}
        with mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0,
                                                                   "query": {}, "took_ms": 1}):
            status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture",
                                                          "query": "stale", "mode": "vector"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["private_knowledge"]["state"], "stale")
        self.assertEqual(result["private_knowledge"]["results"], [])
        self.assertFalse(any(path.endswith("/_search") and isinstance(body, dict) and "knn" in body
                             for method, path, body in FakeVectorElasticsearch.calls))

    def test_model_tokenizer_query_and_mapping_failures_never_claim_vector_success(self):
        owner, client = self.new_user(); self.save(client)
        with mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "prepare", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]):
            status, synced = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection, "allow_model_download": True})
        self.assertEqual(status, 200, synced)
        payload = {"connection": self.connection, "index": "shared-fixture", "query": "query", "mode": "vector"}
        with mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0, "query": {}, "took_ms": 1}), \
                mock.patch.object(embeddings, "runtime_status", return_value={"runtime_installed": False, "model_cached": False}):
            status, result = client.post("/api/search", payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["private_knowledge"]["state"], "model_unavailable")
        self.assertEqual(result["private_knowledge"]["results"], [])
        with mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0, "query": {}, "took_ms": 1}), \
                mock.patch.object(embeddings, "runtime_status", return_value={"runtime_installed": True, "model_cached": True}), \
                mock.patch.object(token_preview, "status", return_value={"available": False, "tokenizers_installed": True, "cached": False}):
            status, result = client.post("/api/search", payload)
        self.assertEqual(result["private_knowledge"]["state"], "tokenizer_unavailable")
        with mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0, "query": {}, "took_ms": 1}), \
                mock.patch.object(embeddings, "runtime_status", return_value={"runtime_installed": True, "model_cached": True}), \
                mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", return_value={"available": True, "truncated": True, "max_tokens": 512}):
            status, result = client.post("/api/search", payload)
        self.assertEqual(result["private_knowledge"]["state"], "query_too_long")
        self.assertEqual(result["private_knowledge"]["results"], [])
        stale_recipe = dict(synced["vector_recipe"]); stale_recipe["fastembed_version"] = "different-fixture-version"
        with sqlite3.connect(auth.state_database_path(owner["id"])) as db:
            db.execute("UPDATE knowledge_es_state SET vector_recipe=? WHERE id=1", (json.dumps(stale_recipe),))
        with mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0, "query": {}, "took_ms": 1}):
            status, result = client.post("/api/search", payload)
        self.assertEqual(result["private_knowledge"]["state"], "stale")
        self.assertEqual(result["private_knowledge"]["results"], [])
        with sqlite3.connect(auth.state_database_path(owner["id"])) as db:
            db.execute("UPDATE knowledge_es_state SET vector_recipe=? WHERE id=1", (json.dumps(synced["vector_recipe"], sort_keys=True, separators=(",", ":")),))
        target = FakeVectorElasticsearch.aliases[synced["alias"]]
        FakeVectorElasticsearch.indexes[target]["mapping"]["mappings"]["properties"]["rag_embedding"]["dims"] = 768
        with mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0, "query": {}, "took_ms": 1}), \
                mock.patch.object(embeddings, "runtime_status", return_value={"runtime_installed": True, "model_cached": True}), \
                mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", return_value={"available": True, "truncated": False, "max_tokens": 512}):
            status, result = client.post("/api/search", payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["private_knowledge"]["state"], "mapping_unavailable")
        self.assertEqual(result["private_knowledge"]["results"], [])

    def test_local_edit_during_vector_search_discards_hits_after_retrieval(self):
        _, client = self.new_user(); self.save(client)
        with mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "prepare", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]):
            status, synced = client.post("/api/knowledge/es-vector-sync", {"connection": self.connection, "allow_model_download": True})
        self.assertEqual(status, 200, synced)
        calls = []

        def mutate_once():
            if calls:
                return
            calls.append(True)
            status, saved = client.post("/api/knowledge/save", {"title": "edited during retrieval", "content": "new private text"})
            if status != 200:
                raise AssertionError(f"fixture edit failed: {status} {saved}")

        FakeVectorElasticsearch.on_private_search = mutate_once
        with mock.patch.object(embeddings, "runtime_status", return_value={"runtime_installed": True, "model_cached": True}), \
                mock.patch.object(token_preview, "status", return_value=self.ready_tokenizer()), \
                mock.patch.object(token_preview, "preview_input", side_effect=self.token_preview_stub), \
                mock.patch.object(embeddings, "embed_texts", return_value=[[1.0] + [0.0] * 1023]), \
                mock.patch.object(server, "retrieve", return_value={"mode": "vector", "hits": [], "total": 0, "query": {}, "took_ms": 1}):
            status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture",
                                                          "query": "query", "mode": "vector"})
        FakeVectorElasticsearch.on_private_search = None
        self.assertEqual(status, 200, result)
        self.assertEqual(result["private_knowledge"]["state"], "stale")
        self.assertEqual(result["private_knowledge"]["results"], [])


if __name__ == "__main__":
    unittest.main()
