"""Cycle 38 private knowledge API and SQLite acceptance tests."""
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
from contextlib import ExitStack
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from es_rag_tuner import auth, concepts, knowledge, server


PASSWORD = "Cycle38-offline-acceptance-password-001!"


class Client:
    def __init__(self, base: str, username: str, password: str = PASSWORD):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        status, session = self.request("/api/auth/session")
        if status != 200 or not session.get("csrf_token"):
            raise AssertionError(f"session bootstrap failed: {status}")
        status, result = self.request("/api/auth/login", {"username": username, "password": password}, csrf=session["csrf_token"])
        if status != 200 or not result.get("authenticated"):
            raise AssertionError(f"login failed: {status}")
        self.csrf = result["csrf_token"]

    def request(self, path: str, payload: dict | None = None, *, csrf: str | None = None, origin: str | None = None):
        headers = {}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers.update({"Content-Type": "application/json", "Origin": origin or self.base,
                            "X-CSRF-Token": self.csrf if csrf is None and hasattr(self, "csrf") else (csrf or "")})
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST" if payload is not None else "GET")
        try:
            with self.opener.open(request, timeout=8) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"raw": raw.decode("utf-8", errors="replace")}
            return exc.code, body

    def post(self, path: str, payload: dict):
        return self.request(path, payload)


class Cycle38KnowledgeAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cycle38-knowledge-")
        cls.db_path = Path(cls.temp.name) / "state.sqlite3"
        cls.env = mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(cls.db_path), "ES_RAG_ACCEPTANCE_ES_URL": "http://127.0.0.1:1"})
        cls.env.start()
        cls.admin = auth.bootstrap_admin("cycle38-admin-" + uuid.uuid4().hex[:8], "Cycle 38 Admin", PASSWORD)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", port), server.WorkbenchHandler)
        cls.base = f"http://127.0.0.1:{port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.admin_client = Client(cls.base, cls.admin["username"])

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls.env.stop()
        cls.temp.cleanup()

    def setUp(self):
        user = auth.create_account("cycle38-user-" + uuid.uuid4().hex[:8], "Cycle 38 User", PASSWORD)
        self.user = user
        self.user_client = Client(self.base, user["username"])
        # The shared primary admin DB is cleared between tests; its auth tables
        # and ownership marker are deliberately retained.
        admin_db = auth.state_database_path(self.admin["id"])
        with sqlite3.connect(admin_db) as db:
            for trigger in ("fail_chunk_insert", "fail_chunk_delete"):
                db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            db.execute("DELETE FROM knowledge_fts") if _table_exists(db, "knowledge_fts") else None
            db.execute("DELETE FROM knowledge_chunks") if _table_exists(db, "knowledge_chunks") else None
            db.execute("DELETE FROM knowledge_documents") if _table_exists(db, "knowledge_documents") else None
        user_db = auth.state_database_path(user["id"])
        self.addCleanup(lambda: [Path(str(user_db) + suffix).unlink(missing_ok=True) for suffix in ("", "-wal", "-shm")])

    def save(self, client: Client, title="Private notes", content="alpha local knowledge", **extra):
        return client.post("/api/knowledge/save", {"title": title, "content": content, "source_label": "acceptance-fixture", **extra})

    def test_auth_csrf_and_origin_are_required(self):
        anonymous = Client.__new__(Client)
        anonymous.base = self.base
        anonymous.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        status, _ = anonymous.request("/api/knowledge/list", {})
        self.assertEqual(status, 401)
        status, _ = self.admin_client.request("/api/knowledge/list", {}, csrf="wrong-token")
        self.assertEqual(status, 403)
        status, _ = self.admin_client.request("/api/knowledge/list", {}, origin="https://attacker.invalid")
        self.assertNotEqual(status, 200)

    def test_account_isolation_admin_scope_forgery_and_uniform_404(self):
        status, saved = self.save(self.admin_client, "Admin private", "needle admin text")
        self.assertEqual(status, 200)
        admin_id = saved["document"]["document_id"]
        status, user_saved = self.save(self.user_client, "User private", "needle user text")
        self.assertEqual(status, 200)
        user_id = user_saved["document"]["document_id"]
        for client, expected, hidden in ((self.admin_client, admin_id, user_id), (self.user_client, user_id, admin_id)):
            status, listing = client.post("/api/knowledge/list", {"owner_id": self.admin["id"], "account_id": self.admin["id"]})
            self.assertEqual(status, 200)
            ids = {row["document_id"] for row in listing["documents"]}
            self.assertIn(expected, ids)
            self.assertNotIn(hidden, ids)
            status, results = client.post("/api/knowledge/search", {"query": "needle", "owner_id": self.admin["id"]})
            self.assertEqual(status, 200)
            self.assertEqual({row["document_id"] for row in results["results"]}, {expected})
        for path, payload in (("get", {"document_id": admin_id}), ("save", {"document_id": admin_id, "title": "Hijack", "content": "no"}), ("delete", {"document_id": admin_id})):
            foreign_status, foreign_body = self.user_client.post("/api/knowledge/" + path, payload)
            unknown_status, unknown_body = self.user_client.post("/api/knowledge/" + path, {**payload, "document_id": str(uuid.uuid4())})
            self.assertEqual(foreign_status, 404)
            self.assertEqual(foreign_status, unknown_status)
            self.assertEqual(foreign_body, unknown_body)
        status, admin_get = self.admin_client.post("/api/knowledge/get", {"document_id": admin_id})
        self.assertEqual(status, 200)
        self.assertEqual(admin_get["content"], "needle admin text")

    def test_preview_chunk_coverage_unicode_utf8_and_validation(self):
        source = "가🙂" * 1100
        status, preview = self.admin_client.post("/api/knowledge/preview", {"title": " Unicode ", "source_label": " ref ", "content": source})
        self.assertEqual(status, 200)
        chunks = preview["chunks"]
        self.assertEqual("".join(chunk["content"] if i == 0 else chunk["content"][200:] for i, chunk in enumerate(chunks)), source)
        for left, right in zip(chunks, chunks[1:]):
            self.assertEqual(left["end"] - right["start"], 200)
        self.assertTrue(all(len(chunk["content"]) <= 1800 for chunk in chunks))
        self.assertEqual(preview["content_bytes"], len(source.encode("utf-8")))
        for invalid in ({"title": "x", "content": "  "}, {"title": "", "content": "a"}, {"title": "x", "content": "a", "source_label": "s" * 201}):
            status, _ = self.admin_client.post("/api/knowledge/preview", {"source_label": "fixture", **invalid})
            self.assertEqual(status, 400)
        status, body = self.admin_client.post("/api/knowledge/preview", {"title": "secret title", "source_label": "fixture", "content": "x" * (1024 * 1024 + 1)})
        self.assertEqual(status, 400)
        self.assertNotIn("x" * 100, json.dumps(body))

    def test_source_label_is_optional_and_empty_defaults_cleanly(self):
        for payload in ({"title": "No source", "content": "plain text"},
                        {"title": "Empty source", "source_label": "", "content": "plain text"}):
            preview_status, preview = self.admin_client.post("/api/knowledge/preview", payload)
            self.assertEqual(preview_status, 200)
            self.assertEqual(preview["source_label"], "")
            save_status, saved = self.admin_client.post("/api/knowledge/save", payload)
            self.assertEqual(save_status, 200)
            self.assertEqual(saved["document"]["source_label"], "")

    def test_crud_ranking_literal_fts_and_safe_output_without_elasticsearch(self):
        with mock.patch.object(concepts, "request", side_effect=AssertionError("knowledge search must not call Elasticsearch")):
            status, first = self.save(self.admin_client, "General", "common words common words")
            self.assertEqual(status, 200)
            doc_id = first["document"]["document_id"]
            status, second = self.save(self.admin_client, "Exact <img src=x onerror=alert(1)>", "rareword \" OR * MATCH knowledge_fts -- SELECT")
            self.assertEqual(status, 200)
            exact_id = second["document"]["document_id"]
            status, results = self.admin_client.post("/api/knowledge/search", {"query": "rareword OR * MATCH knowledge_fts -- SELECT"})
        self.assertEqual(status, 200)
        self.assertEqual(results["results"][0]["document_id"], exact_id)
        common_status, common_hits = self.admin_client.post("/api/knowledge/search", {"query": "common"})
        self.assertEqual(common_status, 200)
        self.assertEqual(common_hits["results"][0]["document_id"], doc_id)
        self.assertIn("<img", results["results"][0]["title"])
        metadata_status, listing = self.admin_client.post("/api/knowledge/list", {})
        self.assertEqual(metadata_status, 200)
        self.assertNotIn("content", listing["documents"][0])
        edited_status, edited = self.admin_client.post("/api/knowledge/save", {"document_id": doc_id, "title": "Updated", "source_label": "fixture", "content": "newneedle only"})
        self.assertEqual(edited_status, 200)
        self.assertNotEqual(edited["chunks"][0]["id"], first["chunks"][0]["id"])
        status, old_hits = self.admin_client.post("/api/knowledge/search", {"query": "common"})
        self.assertEqual(status, 200)
        self.assertFalse(any(row["document_id"] == doc_id for row in old_hits["results"]))
        status, _ = self.admin_client.post("/api/knowledge/delete", {"document_id": exact_id})
        self.assertEqual(status, 200)
        status, deleted_hits = self.admin_client.post("/api/knowledge/search", {"query": "rareword"})
        self.assertEqual(status, 200)
        self.assertFalse(deleted_hits["results"])

    def test_max_document_boundary_and_safe_api_size_ceiling(self):
        status, body = self.admin_client.post("/api/knowledge/preview", {"title": "boundary", "source_label": "fixture", "content": "a" * (1024 * 1024)})
        self.assertEqual(status, 200)
        status, _ = self.admin_client.post("/api/knowledge/preview", {"title": "over", "source_label": "fixture", "content": "a" * (1024 * 1024 + 1)})
        self.assertEqual(status, 400)
        self.assertLess(len(json.dumps({"title": "boundary", "content": "a" * (1024 * 1024)}).encode()), 2 * 1024 * 1024)

    def test_account_quota_and_document_count_are_enforced(self):
        with mock.patch.object(knowledge, "MAX_DOCUMENTS", 2), mock.patch.object(knowledge, "MAX_ACCOUNT_BYTES", 6):
            self.assertEqual(self.save(self.user_client, "one", "abc")[0], 200)
            self.assertEqual(self.save(self.user_client, "two", "def")[0], 200)
            status, _ = self.save(self.user_client, "three", "x")
            self.assertEqual(status, 413)
            status, _ = self.save(self.user_client, "one updated", "abcdefg", document_id=self.user_client.post("/api/knowledge/list", {})[1]["documents"][0]["document_id"])
            self.assertEqual(status, 413)

    def test_create_update_delete_failures_roll_back_document_chunk_and_fts_rows(self):
        status, saved = self.save(self.admin_client, "Atomic", "beforevalue")
        self.assertEqual(status, 200)
        doc_id = saved["document"]["document_id"]
        db_path = auth.state_database_path(self.admin["id"])
        with sqlite3.connect(db_path) as db:
            db.execute("CREATE TRIGGER fail_chunk_insert BEFORE INSERT ON knowledge_chunks BEGIN SELECT RAISE(ABORT,'injected'); END")
        with mock.patch.object(server, "_problem_text", side_effect=lambda exc: str(exc)):
            status, error = self.admin_client.post("/api/knowledge/save", {"title": "new", "source_label": "fixture", "content": "aftervalue"})
        self.assertEqual(status, 500)
        self.assertNotIn("aftervalue", json.dumps(error))
        with sqlite3.connect(db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT content FROM knowledge_documents WHERE id=?", (doc_id,)).fetchone()[0], "beforevalue")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0], 1)
            db.execute("DROP TRIGGER fail_chunk_insert")
            db.execute("CREATE TRIGGER fail_chunk_insert BEFORE INSERT ON knowledge_chunks BEGIN SELECT RAISE(ABORT,'injected'); END")
        status, _ = self.admin_client.post("/api/knowledge/save", {"document_id": doc_id, "title": "broken", "source_label": "fixture", "content": "new broken"})
        self.assertEqual(status, 500)
        with sqlite3.connect(db_path) as db:
            self.assertEqual(db.execute("SELECT content FROM knowledge_documents WHERE id=?", (doc_id,)).fetchone()[0], "beforevalue")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=?", (doc_id,)).fetchone()[0], 1)
            db.execute("DROP TRIGGER fail_chunk_insert")
            db.execute("CREATE TRIGGER fail_chunk_delete BEFORE DELETE ON knowledge_chunks BEGIN SELECT RAISE(ABORT,'injected'); END")
        status, _ = self.admin_client.post("/api/knowledge/delete", {"document_id": doc_id})
        self.assertEqual(status, 500)
        with sqlite3.connect(db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_documents WHERE id=?", (doc_id,)).fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=?", (doc_id,)).fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_fts WHERE document_id=?", (doc_id,)).fetchone()[0], 1)

    def test_repeatable_schema_init_and_concurrent_first_open(self):
        owner = self.user["id"]
        errors = []
        barrier = threading.Barrier(8)
        def worker(index):
            try:
                barrier.wait()
                with concepts.owner_scope(owner):
                    knowledge.list_documents()
                    knowledge.save_document({"title": f"parallel {index}", "source_label": "parallel", "content": f"uniqueparallel{index}"})
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
        user_db = auth.state_database_path(owner)
        if user_db.exists():
            user_db.unlink()
        with ExitStack() as _:
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=20)
        self.assertEqual(errors, [])
        with sqlite3.connect(user_db) as db:
            self.assertEqual(db.execute("SELECT owner_id FROM state_owner WHERE singleton=1").fetchone()[0], owner)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0], 8)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0], 8)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0], 8)
        with concepts.owner_scope(owner):
            knowledge.list_documents()
            knowledge.list_documents()
        with sqlite3.connect(user_db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0], 8)


def _table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


if __name__ == "__main__":
    unittest.main()
