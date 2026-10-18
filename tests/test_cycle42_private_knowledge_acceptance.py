"""Cycle 42 private Elasticsearch knowledge acceptance (local fake ES only).

Run with: ./.venv/bin/python -m unittest tests.test_cycle42_private_knowledge_acceptance -v
The fake HTTP server below is a protocol fixture, not a live Elasticsearch test.
"""
from __future__ import annotations

import json
import contextlib
import io
import os
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from es_rag_tuner import ai_coach, auth, concepts, es_client, server


PASSWORD = "Cycle42-offline-acceptance-password-001!"


class FakeElasticsearch(BaseHTTPRequestHandler):
    indexes: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    extra_alias_targets: dict[str, str] = {}
    calls: list[tuple[str, str, object]] = []
    fail_bulk = False
    fail_alias_swap = False
    bulk_canary = ""
    block_bulk = False
    bulk_started: threading.Event | None = None
    release_bulk: threading.Event | None = None
    on_refresh = None
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
            return self._send(200, {"cluster_name": "cycle42-fake", "version": {"number": "mock"}, "tagline": "You Know, for Search"})
        if path.startswith("_cat/indices") and self.command == "GET":
            return self._send(200, [{"index": name} for name in sorted(set(type(self).indexes) | set(type(self).aliases.values()))])
        if path.startswith("_alias/") and self.command == "GET":
            alias = path.split("/", 1)[1]
            target = type(self).aliases.get(alias)
            if not target:
                return self._send(404, {"error": {"reason": "alias missing"}})
            targets = {target, *([type(self).extra_alias_targets[alias]] if alias in type(self).extra_alias_targets else [])}
            return self._send(200, {name: {"aliases": {alias: {}}} for name in targets})
        if self.command == "PUT":
            type(self).indexes[path] = {"mapping": body, "documents": {}}
            return self._send(200, {"acknowledged": True})
        if path == "_bulk" and self.command == "POST":
            if type(self).block_bulk:
                type(self).bulk_started.set()
                type(self).release_bulk.wait(timeout=5)
            lines = [line for line in str(body or "").splitlines() if line]
            items = []
            for index in range(0, len(lines), 2):
                meta = json.loads(lines[index])["index"]
                document = json.loads(lines[index + 1])
                status = 400 if (type(self).fail_bulk or type(self).bulk_canary) and index == 0 else 201
                if status < 300:
                    type(self).indexes.setdefault(meta["_index"], {"documents": {}})["documents"][meta["_id"]] = document
                items.append({"index": {"_id": meta["_id"], "status": status}})
            return self._send(200, {"errors": any(item["index"]["status"] >= 300 for item in items), "items": items,
                                    "error": {"reason": type(self).bulk_canary} if type(self).bulk_canary else {"reason": "injected partial failure"}})
        if path == "_aliases" and self.command == "POST":
            if type(self).fail_alias_swap:
                return self._send(500, {"error": {"reason": "injected alias swap failure"}})
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
            for alias, target in list(type(self).aliases.items()):
                if target == path:
                    type(self).aliases.pop(alias, None)
            return self._send(200, {"acknowledged": True})
        if self.command == "POST" and path.endswith("/_refresh"):
            if type(self).on_refresh:
                type(self).on_refresh()
            return self._send(200, {"_shards": {"successful": 1, "failed": 0}})
        if self.command == "POST" and path.endswith("/_search"):
            target = path.rsplit("/", 1)[0]
            concrete = type(self).aliases.get(target, target)
            docs = type(self).indexes.get(concrete, {}).get("documents", {})
            hits = [{"_id": key, "_score": 0.5, "_source": value} for key, value in docs.items()]
            if target.startswith("esrag-private-") and type(self).on_private_search:
                type(self).on_private_search()
            return self._send(200, {"hits": {"total": {"value": len(docs)}, "hits": hits}})
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
            with self.opener.open(request, timeout=5) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, json.loads(raw) if raw else {}

    def post(self, path, body):
        return self.request(path, body)


class Cycle42PrivateKnowledgeAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.app_port = sock.getsockname()[1]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.es_port = sock.getsockname()[1]
        cls.temp = tempfile.TemporaryDirectory(prefix="cycle42-private-es-")
        cls.env = mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(Path(cls.temp.name) / "shared.sqlite3"),
                                               "ES_RAG_ACCEPTANCE_ES_URL": f"http://127.0.0.1:{cls.es_port}"})
        cls.env.start()
        cls.es = ThreadingHTTPServer(("127.0.0.1", cls.es_port), FakeElasticsearch)
        cls.es_thread = threading.Thread(target=cls.es.serve_forever, daemon=True)
        cls.es_thread.start()
        cls.app = ThreadingHTTPServer(("127.0.0.1", cls.app_port), server.WorkbenchHandler)
        cls.app_thread = threading.Thread(target=cls.app.serve_forever, daemon=True)
        cls.app_thread.start()
        cls.base = f"http://127.0.0.1:{cls.app_port}"
        cls.admin = auth.bootstrap_admin("cycle42-admin", "Cycle 42 Admin", PASSWORD)

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown(); cls.app.server_close(); cls.app_thread.join(timeout=5)
        cls.es.shutdown(); cls.es.server_close(); cls.es_thread.join(timeout=5)
        cls.env.stop(); cls.temp.cleanup()

    def setUp(self):
        FakeElasticsearch.indexes = {}
        FakeElasticsearch.aliases = {}
        FakeElasticsearch.extra_alias_targets = {}
        FakeElasticsearch.calls = []
        FakeElasticsearch.fail_bulk = False
        FakeElasticsearch.fail_alias_swap = False
        FakeElasticsearch.bulk_canary = ""
        FakeElasticsearch.block_bulk = False
        FakeElasticsearch.bulk_started = None
        FakeElasticsearch.release_bulk = None
        FakeElasticsearch.on_refresh = None
        FakeElasticsearch.on_private_search = None
        self.admin = Client(self.base, "cycle42-admin")
        self.users = []
        self.clients = []
        self.addCleanup(self.cleanup_users)

    def cleanup_users(self):
        for path in self.users:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)

    def new_user(self):
        user = auth.create_account("cycle42-user-" + uuid.uuid4().hex[:8], "Cycle 42 User", PASSWORD)
        self.users.append(auth.state_database_path(user["id"]))
        client = Client(self.base, user["username"])
        self.clients.append(client)
        return user, client

    @property
    def connection(self):
        return {"url": f"http://127.0.0.1:{self.es_port}"}

    @staticmethod
    def concept(index):
        return {"id": "cycle42-fixture-concept", "name": "Fixture", "description": "Fixture concept",
                "aliases": [], "related": [], "excluded_terms": [],
                "corpus": {"index": index, "title_field": "", "text_fields": ["body"], "filter_fields": []},
                "filters": [], "settings": {"mode": "bm25", "size": 2, "candidate_size": 10},
                "queries": [{"id": "q1", "query": "fixture query", "split": "train"}]}

    def save(self, client, title="Private guide", content="ownneedle private procedure"):
        status, result = client.post("/api/knowledge/save", {"title": title, "content": content})
        self.assertEqual(status, 200, result)
        return result["document"]["document_id"]

    def test_auth_owner_identity_and_forged_payload_fields_are_ignored(self):
        user, client = self.new_user()
        self.save(client)
        status, synced = client.post("/api/knowledge/es-sync", {"connection": self.connection,
                                                                "owner_id": "forged-admin-id",
                                                                "account_id": "forged-admin-id",
                                                                "index": "esrag-private-" + "f" * 32})
        self.assertEqual(status, 200, synced)
        expected = "esrag-private-" + user["id"].replace("-", "")
        self.assertEqual(synced["alias"], expected)
        targets = [index for _, index, _ in FakeElasticsearch.calls if index.startswith(expected + "-g")]
        self.assertTrue(targets)
        self.assertFalse(any("f" * 32 in index for _, index, _ in FakeElasticsearch.calls))
        self.assertEqual(FakeElasticsearch.aliases[expected], targets[0])

    def test_foreign_private_index_denied_before_es_network_and_listing_is_filtered(self):
        owner_a, a = self.new_user(); owner_b, b = self.new_user()
        self.save(a); self.save(b)
        self.assertEqual(a.post("/api/knowledge/es-sync", {"connection": self.connection})[0], 200)
        self.assertEqual(b.post("/api/knowledge/es-sync", {"connection": self.connection})[0], 200)
        foreign = "esrag-private-" + owner_b["id"].replace("-", "")
        before = len(FakeElasticsearch.calls)
        for path, body in (("/api/document", {"connection": self.connection, "index": foreign, "id": "x"}),
                           ("/api/explain", {"connection": self.connection, "index": foreign, "id": "x", "query": "q"}),
                           ("/api/search", {"connection": self.connection, "index": foreign, "query": "q", "mode": "bm25"}),
                           ("/api/search", {"connection": self.connection, "index": foreign, "query": "q", "mode": "vector"}),
                           ("/api/search", {"connection": self.connection, "index": foreign, "query": "q", "mode": "hybrid"})):
            status, _ = a.post(path, body)
            if path == "/api/search" and body.get("mode") in {"vector", "hybrid"}:
                self.assertEqual(status, 403, f"foreign alias must be forbidden before shared-vector fallback: {path} {body['mode']}")
                continue
            self.assertIn(status, (400, 403), path)
        self.assertEqual(len(FakeElasticsearch.calls), before, "foreign private path reached ES")
        # Diagnostic and AI retrieval use the same owner-bound ES transport guard.
        status, _ = a.post("/api/concepts/diagnose", {"connection": self.connection,
                                                        "concept": self.concept(foreign), "query": "fixture query",
                                                        "document_index": foreign, "document_id": "x"})
        self.assertIn(status, (400, 403))
        self.assertEqual(len(FakeElasticsearch.calls), before, "diagnostic foreign path reached ES")
        with concepts.owner_scope(owner_a["id"]):
            with self.assertRaises(es_client.ElasticsearchError):
                ai_coach._host_tool("get_schema", {}, es_client.Connection(self.connection["url"]),
                                    {"corpus": {"index": foreign, "text_fields": ["body"], "filter_fields": []},
                                     "concept": self.concept(foreign)}, {"concept": self.concept(foreign)}, 10**12)
        self.assertEqual(len(FakeElasticsearch.calls), before, "AI foreign path reached ES")
        # Exercise the same inventory helper under an authenticated owner scope.
        with concepts.owner_scope(owner_a["id"]):
            visible = {row.get("index") for row in es_client.list_indices(es_client.Connection(self.connection["url"]))}
        self.assertTrue(any(name and name.startswith("esrag-private-" + owner_a["id"].replace("-", "") + "-g") for name in visible))
        self.assertFalse(any(name and name.startswith(foreign) for name in visible))

    def test_transport_boundary_rejects_private_prefix_lists_wildcards_and_indexless_search(self):
        owner, _ = self.new_user()
        foreign_owner, _ = self.new_user()
        foreign_alias = "esrag-private-" + foreign_owner["id"].replace("-", "")
        paths = ("_search", f"%65srag-private-{foreign_owner['id'].replace('-', '')}/_search", "*/_search", "_all/_search", f"esrag-private-*/_search", f"shared-fixture,{foreign_alias}/_search",
                 f"{foreign_alias}-unexpected-suffix/_search")
        before = len(FakeElasticsearch.calls)
        with concepts.owner_scope(owner["id"]):
            for path in paths:
                with self.subTest(path=path):
                    with self.assertRaises(es_client.ElasticsearchError):
                        es_client.request(es_client.Connection(self.connection["url"]), "POST", path, {})
        self.assertEqual(len(FakeElasticsearch.calls), before, "unsafe private/global request reached ES")

    def test_generic_index_and_mutation_apis_cannot_target_own_private_namespace(self):
        owner, client = self.new_user()
        alias = "esrag-private-" + owner["id"].replace("-", "")
        before = len(FakeElasticsearch.calls)
        for path in ("/api/vectorize", "/api/sample-import", "/api/sample-info", "/api/mapping"):
            status, _ = client.post(path, {"connection": self.connection, "index": alias})
            self.assertIn(status, (400, 403), path)
        self.assertEqual(len(FakeElasticsearch.calls), before, "generic API reached the private index")
        # Reserved namespace-looking content is still ordinary query text.
        status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture",
                                                     "query": alias, "mode": "bm25"})
        self.assertEqual(status, 200, result)
        self.assertIn("private_knowledge", result)

    def test_owner_gets_own_private_bm25_hit_without_foreign_marker_and_shared_lane_remains(self):
        owner_a, a = self.new_user()
        owner_b, b = self.new_user()
        self.save(a, title="A private", content="sharedquery accountAMarker")
        self.save(b, title="B private", content="sharedquery accountBMarker")
        self.assertEqual(a.post("/api/knowledge/es-sync", {"connection": self.connection})[0], 200)
        self.assertEqual(b.post("/api/knowledge/es-sync", {"connection": self.connection})[0], 200)
        shared = {"mode": "bm25", "hits": [{"_id": "shared", "_score": 7, "_source": {"summary": "shared lane"}}], "total": 1, "query": {"rank_constant": 60}, "took_ms": 1}
        with mock.patch.object(server, "retrieve", return_value=shared):
            status, result = a.post("/api/search", {"connection": self.connection, "index": "shared-fixture", "query": "sharedquery", "mode": "bm25"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["hits"], shared["hits"])
        own_sources = [hit["_source"] for hit in result["private_knowledge"]["results"]]
        self.assertTrue(any("accountAMarker" in source["rag_chunk_text"] for source in own_sources))
        self.assertFalse(any("accountBMarker" in source["rag_chunk_text"] for source in own_sources))
        self.assertNotEqual(result["hits"][0]["_score"], own_sources[0].get("_score"))

    def test_status_get_requires_auth_and_local_crud_marks_sync_stale(self):
        try:
            with urllib.request.urlopen(self.base + "/api/knowledge/es-status", timeout=5) as response:
                anonymous_status = response.status
        except urllib.error.HTTPError as exc:
            anonymous_status = exc.code
        self.assertEqual(anonymous_status, 401)
        user, client = self.new_user()
        document_id = self.save(client)
        expected = "esrag-private-" + user["id"].replace("-", "")
        status, state = client.request("/api/knowledge/es-status")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["alias"], expected)
        self.assertEqual(state["state"], "stale")
        self.assertEqual(client.post("/api/knowledge/es-sync", {"connection": self.connection})[0], 200)
        status, state = client.request("/api/knowledge/es-status")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["state"], "in_sync")
        self.assertEqual(client.post("/api/knowledge/save", {"document_id": document_id, "title": "edited", "content": "changedneedle"})[0], 200)
        self.assertEqual(client.request("/api/knowledge/es-status")[1]["state"], "stale")
        self.assertEqual(client.post("/api/knowledge/es-sync", {"connection": self.connection})[0], 200)
        self.assertEqual(client.post("/api/knowledge/delete", {"document_id": document_id})[0], 200)
        self.assertEqual(client.request("/api/knowledge/es-status")[1]["state"], "stale")

    def test_first_use_empty_library_reports_not_synced_without_sync_prompt_or_private_hits(self):
        _, client = self.new_user()
        status, state = client.request("/api/knowledge/es-status")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["state"], "not_synced")
        self.assertEqual(state["local_documents"], 0)
        self.assertEqual(state["local_chunks"], 0)

        shared = {"mode": "bm25", "hits": [{"_id": "shared", "_score": 7,
                                                   "_source": {"summary": "shared lane"}}],
                  "total": 1, "query": {"rank_constant": 60}, "took_ms": 1}
        before_private_search = len([call for call in FakeElasticsearch.calls if call[1].endswith("/_search")])
        with mock.patch.object(server, "retrieve", return_value=shared):
            status, result = client.post("/api/search", {"connection": self.connection,
                                                          "index": "shared-fixture",
                                                          "query": "empty-library", "mode": "bm25"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["hits"], shared["hits"])
        self.assertEqual(result["private_knowledge"]["state"], "empty")
        self.assertEqual(result["private_knowledge"]["results"], [])
        self.assertEqual(len([call for call in FakeElasticsearch.calls if call[1].endswith("/_search")]),
                         before_private_search, "empty library should not query a private ES generation")

    def test_bulk_and_alias_swap_failures_keep_previous_generation_and_retry(self):
        _, client = self.new_user(); self.save(client, content="firstgeneration")
        status, first = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, first)
        alias = first["alias"]; prior = FakeElasticsearch.aliases[alias]
        private_targets = [path for _, path, _ in FakeElasticsearch.calls if path.startswith(alias + "-g")]
        refresh_index = next(i for i, path in enumerate(private_targets) if path.endswith("/_refresh"))
        visible_index = next(i for i, path in enumerate(private_targets) if path.endswith("/_search"))
        # _aliases is a global endpoint and therefore appears outside the target prefix.
        alias_index = next(i for i, (_, path, _) in enumerate(FakeElasticsearch.calls) if path == "_aliases")
        refresh_global = next(i for i, (_, path, _) in enumerate(FakeElasticsearch.calls) if path == private_targets[refresh_index])
        visible_global = next(i for i, (_, path, _) in enumerate(FakeElasticsearch.calls) if path == private_targets[visible_index])
        self.assertLess(refresh_global, visible_global)
        self.assertLess(visible_global, alias_index, "generation alias was published before refresh and visibility verification")
        self.save(client, content="secondgeneration")
        FakeElasticsearch.fail_bulk = True
        status, _ = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 503)
        self.assertEqual(FakeElasticsearch.aliases[alias], prior)
        FakeElasticsearch.fail_bulk = False
        FakeElasticsearch.fail_alias_swap = True
        status, _ = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 503)
        self.assertEqual(FakeElasticsearch.aliases[alias], prior)
        FakeElasticsearch.fail_alias_swap = False
        status, retried = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, retried)
        self.assertNotEqual(FakeElasticsearch.aliases[alias], prior)

    def test_local_change_during_staging_does_not_publish_generation_or_mark_synced(self):
        owner, client = self.new_user()
        self.save(client, content="before-race-content")
        status, first = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, first)
        alias = first["alias"]
        prior = FakeElasticsearch.aliases[alias]
        self.save(client, content="race-candidate-content")
        db_path = auth.state_database_path(owner["id"])
        fired = {"value": False}

        def mutate_while_staged():
            if fired["value"]:
                return
            fired["value"] = True
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE knowledge_documents SET content=?", ("changed-during-stage",))
                db.execute("UPDATE knowledge_chunks SET content=?", ("changed-during-stage",))

        FakeElasticsearch.on_refresh = mutate_while_staged
        status, _ = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        FakeElasticsearch.on_refresh = None
        self.assertTrue(fired["value"])
        self.assertEqual(status, 503)
        self.assertEqual(FakeElasticsearch.aliases[alias], prior)
        state_status, state = client.request("/api/knowledge/es-status")
        self.assertEqual(state_status, 200)
        self.assertNotEqual(state["state"], "in_sync")

    def test_local_change_during_private_search_discards_hits_and_keeps_shared_lane(self):
        owner, client = self.new_user()
        self.save(client, content="searchrace private marker")
        self.assertEqual(client.post("/api/knowledge/es-sync", {"connection": self.connection})[0], 200)
        db_path = auth.state_database_path(owner["id"])
        fired = {"value": False}

        def mutate_during_search():
            if fired["value"]:
                return
            fired["value"] = True
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE knowledge_documents SET content=?", ("changed while search in flight",))
                db.execute("UPDATE knowledge_chunks SET content=?", ("changed while search in flight",))

        FakeElasticsearch.on_private_search = mutate_during_search
        shared = {"mode": "bm25", "hits": [{"_id": "shared-hit", "_score": 4}], "total": 1, "query": {"rank_constant": 60}, "took_ms": 1}
        with mock.patch.object(server, "retrieve", return_value=shared):
            status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture", "query": "searchrace", "mode": "bm25"})
        FakeElasticsearch.on_private_search = None
        self.assertEqual(status, 200, result)
        self.assertTrue(fired["value"])
        self.assertEqual(result["hits"], shared["hits"])
        self.assertEqual(result["private_knowledge"]["state"], "stale")
        self.assertEqual(result["private_knowledge"]["results"], [])
        self.assertNotIn("searchrace private marker", json.dumps(result))

    def test_unexpected_or_multi_target_alias_fails_closed_for_private_lane(self):
        _, client = self.new_user()
        self.save(client, content="private lane match")
        status, synced = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, synced)
        alias = synced["alias"]
        expected = FakeElasticsearch.aliases[alias]
        for wrong in (f"{alias}-g999", f"{alias}-g998"):
            FakeElasticsearch.aliases[alias] = wrong
            FakeElasticsearch.extra_alias_targets.pop(alias, None)
            response_status, result = client.post("/api/search", {"connection": self.connection,
                                                                    "index": "shared-fixture", "query": "private lane", "mode": "bm25"})
            self.assertEqual(response_status, 200, result)
            self.assertEqual(result["private_knowledge"]["state"], "stale")
            self.assertEqual(result["private_knowledge"]["results"], [])
            self.assertFalse(any(path == f"{alias}/_search" for _, path, _ in FakeElasticsearch.calls))
        FakeElasticsearch.aliases[alias] = expected
        FakeElasticsearch.extra_alias_targets[alias] = f"{alias}-g997"
        response_status, result = client.post("/api/search", {"connection": self.connection,
                                                                "index": "shared-fixture", "query": "private lane", "mode": "bm25"})
        self.assertEqual(response_status, 200, result)
        self.assertEqual(result["private_knowledge"]["state"], "stale")
        self.assertEqual(result["private_knowledge"]["results"], [])

    def test_sync_preserves_unexpected_or_multi_target_alias_and_allows_retry(self):
        _, client = self.new_user()
        self.save(client, content="syncguard private marker")
        status, synced = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, synced)
        alias = synced["alias"]
        original = FakeElasticsearch.aliases[alias]

        # A future generation is not part of this account's committed history.
        FakeElasticsearch.aliases[alias] = f"{alias}-g999"
        status, _ = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 503)
        self.assertEqual(FakeElasticsearch.aliases[alias], f"{alias}-g999")

        # Restoring the known prior target allows a retry to advance generation.
        FakeElasticsearch.aliases[alias] = original
        status, retry = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, retry)
        current = FakeElasticsearch.aliases[alias]

        # A multi-target alias is ambiguous and must not be replaced either.
        FakeElasticsearch.extra_alias_targets[alias] = f"{alias}-g{int(current.rsplit('-g', 1)[1]) - 1}"
        before = dict(FakeElasticsearch.aliases)
        extra = dict(FakeElasticsearch.extra_alias_targets)
        status, _ = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 503)
        self.assertEqual(FakeElasticsearch.aliases, before)
        self.assertEqual(FakeElasticsearch.extra_alias_targets, extra)

        FakeElasticsearch.extra_alias_targets.pop(alias)
        status, retry = client.post("/api/knowledge/es-sync", {"connection": self.connection})
        self.assertEqual(status, 200, retry)
        self.assertTrue(FakeElasticsearch.aliases[alias].startswith(alias + "-g"))

    def test_private_content_canary_is_absent_from_sync_error_status_and_logs(self):
        canary = "C42_PRIVATE_CANARY_9b75e78a"
        _, client = self.new_user()
        self.save(client, content="ordinary text " + canary)
        FakeElasticsearch.bulk_canary = canary
        logs = []
        with mock.patch.object(server.WorkbenchHandler, "log_message", side_effect=lambda fmt, *args: logs.append(fmt % args)):
            status, body = client.post("/api/knowledge/es-sync", {"connection": self.connection})
            state_status, state = client.request("/api/knowledge/es-status")
        self.assertEqual(status, 503)
        self.assertEqual(state_status, 200)
        self.assertNotIn(canary, json.dumps(body))
        self.assertNotIn(canary, json.dumps(state))
        self.assertNotIn(canary, "\n".join(logs))

    def test_overlapping_account_syncs_reject_or_serialize_without_generation_collision(self):
        user, client_a = self.new_user()
        client_b = Client(self.base, user["username"])
        self.save(client_a, content="concurrency fixture")
        FakeElasticsearch.block_bulk = True
        FakeElasticsearch.bulk_started = threading.Event()
        FakeElasticsearch.release_bulk = threading.Event()
        responses = []

        def sync(client):
            responses.append(client.post("/api/knowledge/es-sync", {"connection": self.connection}))

        first = threading.Thread(target=sync, args=(client_a,))
        second = threading.Thread(target=sync, args=(client_b,))
        first.start()
        self.assertTrue(FakeElasticsearch.bulk_started.wait(timeout=5), "first sync did not reach fake bulk endpoint")
        second.start()
        time.sleep(0.1)
        FakeElasticsearch.release_bulk.set()
        first.join(timeout=8); second.join(timeout=8)
        FakeElasticsearch.block_bulk = False
        self.assertFalse(first.is_alive() or second.is_alive(), "overlapping sync requests did not finish")
        statuses = sorted(status for status, _ in responses)
        self.assertIn(statuses, ([200, 409], [200, 503], [200, 200]))
        targets = [path for method, path, _ in FakeElasticsearch.calls if method == "PUT" and path.startswith("esrag-private-")]
        self.assertEqual(len(targets), len(set(targets)), "two syncs targeted the same generation")

    def test_private_lane_is_bm25_only_and_shared_lane_remains_present(self):
        _, client = self.new_user(); self.save(client)
        status, result = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture", "query": "ownneedle", "mode": "bm25"})
        self.assertEqual(status, 200, result)
        self.assertIn("hits", result)
        self.assertIn("private_knowledge", result)
        self.assertEqual(result["private_knowledge"]["state"], "stale")
        self.assertEqual(result["private_knowledge"]["results"], [])
        shared_lane = {"query": "ownneedle", "hits": [{"_id": "shared-hit", "_score": 1.25}]}
        for mode in ("vector", "hybrid"):
            with mock.patch.object(server, "retrieve", return_value=shared_lane) as shared_retrieve:
                status, unsupported = client.post("/api/search", {"connection": self.connection, "index": "shared-fixture", "query": "ownneedle", "mode": mode})
            self.assertEqual(status, 200, unsupported)
            self.assertEqual(unsupported["hits"], shared_lane["hits"])
            self.assertIn(unsupported["private_knowledge"]["state"], ("not_indexed", "stale"))
            self.assertEqual(unsupported["private_knowledge"]["results"], [])
            shared_retrieve.assert_called_once()

    def test_private_status_error_does_not_break_shared_vector_or_hybrid_results(self):
        _, client = self.new_user()
        shared_lane = {"query": "q", "hits": [{"_id": "shared-hit", "_score": 3}], "total": 1}
        for error in (es_client.ElasticsearchError("forbidden private alias", 403),
                      es_client.ElasticsearchError("simulated private alias network failure")):
            for mode in ("vector", "hybrid"):
                with mock.patch.object(server, "retrieve", return_value=shared_lane), \
                     mock.patch("es_rag_tuner.knowledge.es_status", side_effect=error):
                    status, result = client.post("/api/search", {"connection": self.connection,
                                                                   "index": "shared-fixture", "query": "q", "mode": mode})
                self.assertEqual(status, 200, result)
                self.assertEqual(result["hits"], shared_lane["hits"])
                self.assertIn(result["private_knowledge"]["state"], ("unavailable", "unsupported_mode"))


if __name__ == "__main__":
    unittest.main()
