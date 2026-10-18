"""HTTP acceptance for aggregate tune-label readiness without Elasticsearch.

Run with: ./.venv/bin/python -m unittest discover -s tests -p 'test_concept_tune_readiness.py' -v
The server uses a disposable SQLite database and a dynamically allocated loopback port.
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
from pathlib import Path
from http.server import ThreadingHTTPServer
from es_rag_tuner import server
try:
    from tests.cycle37_auth_test_support import AuthenticatedClient, api_request, install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import AuthenticatedClient, api_request, install_auth_fixture


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


class TuneReadinessAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), server.WorkbenchHandler)
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
            "id": "readiness-" + uuid.uuid4().hex[:12],
            "name": "Readiness fixture",
            "corpus": {"index": "synthetic-index", "text_fields": ["body"]},
            "queries": queries or [
                {"id": "train-current", "query": "current train query", "split": "train"},
                {"id": "train-other", "query": "other train query", "split": "train"},
                {"id": "validation", "query": "validation query", "split": "validation"},
            ],
        }

    def save(self, concept: dict) -> None:
        self.post("/api/concepts/save", {"concept": concept})

    def judge(self, concept: dict, query_id: str, doc: str, rating: int | None, *, pinned: bool = False, reason: str = "private reason sentinel"):
        return self.post("/api/concepts/judge", {
            "concept_id": concept["id"], "query_id": query_id,
            "document_index": "synthetic-index", "document_id": doc,
            "rating": rating, "pinned": pinned, "reason": reason,
        })

    def readiness(self, concept: dict):
        return self.post("/api/concepts/tune/readiness", {"concept": concept})

    def expected_counts(self, concept: dict, *, training_graded: int = 0,
                        training_positive: int = 0, validation_graded: int = 0,
                        validation_positive: int = 0, stale: int = 0,
                        training_graded_queries: int = 0, training_positive_queries: int = 0,
                        validation_graded_queries: int = 0, validation_positive_queries: int = 0) -> dict:
        queries = concept.get("queries", [])
        training_queries = sum(query.get("split") == "train" for query in queries)
        validation_queries = sum(query.get("split") == "validation" for query in queries)
        return {
            "training_graded": training_graded,
            "training_positive": training_positive,
            "validation_graded": validation_graded,
            "validation_positive": validation_positive,
            "stale": stale,
            "training_queries": training_queries,
            "validation_queries": validation_queries,
            "training_graded_queries": training_graded_queries,
            "training_positive_queries": training_positive_queries,
            "validation_graded_queries": validation_graded_queries,
            "validation_positive_queries": validation_positive_queries,
            # Legacy fixtures have no group labels, so each query is one
            # implicit group. Explicit multi-variant grouping is covered by
            # the Cycle 11 acceptance suite.
            "training_information_need_groups": training_queries,
            "training_graded_information_need_groups": training_graded_queries,
            "training_positive_information_need_groups": training_positive_queries,
            "validation_information_need_groups": validation_queries,
            "validation_graded_information_need_groups": validation_graded_queries,
            "validation_positive_information_need_groups": validation_positive_queries,
        }

    def db_snapshot(self):
        with sqlite3.connect(self.db_path) as db:
            result = {}
            for table in ("concepts", "concept_versions", "judgments", "runs"):
                result[table] = db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            return result

    def new_secondary_store_client(self):
        username = "readiness-user-" + uuid.uuid4().hex[:10]
        status, created = self.test_api.post("/api/admin/accounts/create", {
            "username": username, "display_name": "Readiness User",
            "password": "Cycle37-secondary-test-password-001!",
        })
        self.assertEqual(status, 201, created)
        client = AuthenticatedClient(self.base, created["account"], "Cycle37-secondary-test-password-001!")
        from es_rag_tuner import auth
        state_path = auth.state_database_path(created["account"]["id"])
        return state_path, client

    def test_train_positive_outside_current_preview_is_eligible(self):
        concept = self.concept()
        self.save(concept)
        self.judge(concept, "train-other", "positive-elsewhere", 2)

        result = self.readiness(concept)

        self.assertEqual(result, {
            "eligible": True,
            "reason_code": "train_positive_available",
            "counts": self.expected_counts(concept, training_graded=1, training_positive=1,
                                            training_graded_queries=1, training_positive_queries=1),
            "scope": "label_readiness_only",
        })

    def test_validation_only_positive_is_ineligible(self):
        concept = self.concept()
        self.save(concept)
        self.judge(concept, "validation", "validation-positive", 3)

        result = self.readiness(concept)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_code"], "train_positive_required")
        self.assertEqual(result["counts"], self.expected_counts(
            concept, validation_graded=1, validation_positive=1,
            validation_graded_queries=1, validation_positive_queries=1,
        ))

    def test_stale_train_positive_is_excluded_and_counted(self):
        saved = self.concept([{"id": "train-current", "query": "old training query", "split": "train"}])
        self.save(saved)
        self.judge(saved, "train-current", "stale-positive", 1)
        edited = json.loads(json.dumps(saved))
        edited["queries"][0]["query"] = "edited training query"

        result = self.readiness(edited)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_code"], "train_positive_required")
        self.assertEqual(result["counts"], self.expected_counts(edited, stale=1))

    def test_grade_zero_only_and_pin_only_do_not_qualify(self):
        concept = self.concept()
        self.save(concept)
        self.judge(concept, "train-current", "zero-grade", 0)
        self.judge(concept, "train-other", "pin-only", None, pinned=True)

        result = self.readiness(concept)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["counts"], self.expected_counts(
            concept, training_graded=1, training_graded_queries=1,
        ))

    def test_positive_rating_remains_valid_when_pinned(self):
        concept = self.concept()
        self.save(concept)
        self.judge(concept, "train-current", "pinned-positive", 1, pinned=True)

        result = self.readiness(concept)

        self.assertTrue(result["eligible"])
        self.assertEqual(result["counts"]["training_graded"], 1)
        self.assertEqual(result["counts"]["training_positive"], 1)

    def test_counts_match_split_and_exclude_stale_rows(self):
        saved = self.concept()
        saved["queries"].append({"id": "train-stale", "query": "stale train query", "split": "train"})
        self.save(saved)
        self.judge(saved, "train-current", "train-zero", 0)
        self.judge(saved, "train-other", "train-positive", 3)
        self.judge(saved, "validation", "validation-zero", 0)
        self.judge(saved, "validation", "validation-positive", 1)
        self.judge(saved, "train-stale", "stale-positive", 2)
        edited = json.loads(json.dumps(saved))
        edited["queries"][-1]["query"] = "changed stale query"

        result = self.readiness(edited)

        self.assertTrue(result["eligible"])
        self.assertEqual(result["counts"], self.expected_counts(
            edited, training_graded=2, training_positive=1,
            validation_graded=2, validation_positive=1, stale=1,
            training_graded_queries=2, training_positive_queries=1,
            validation_graded_queries=1, validation_positive_queries=1,
        ))

    def test_query_coverage_counts_are_distinct_and_include_unlabeled_queries(self):
        concept = self.concept([
            {"id": "train-a", "query": "train A", "split": "train"},
            {"id": "train-b", "query": "train B", "split": "train"},
            {"id": "train-unlabeled", "query": "unlabeled train", "split": "train"},
            {"id": "validation-a", "query": "validation A", "split": "validation"},
            {"id": "validation-unlabeled", "query": "unlabeled validation", "split": "validation"},
        ])
        self.save(concept)
        self.judge(concept, "train-a", "train-a-positive-1", 1)
        self.judge(concept, "train-b", "train-b-positive-1", 2)
        self.judge(concept, "train-b", "train-b-positive-2", 3)
        self.judge(concept, "train-b", "train-b-zero", 0)
        self.judge(concept, "validation-a", "validation-positive-1", 1)
        self.judge(concept, "validation-a", "validation-positive-2", 3, pinned=True)
        self.judge(concept, "validation-a", "validation-zero", 0)

        result = self.readiness(concept)

        self.assertTrue(result["eligible"])
        self.assertEqual(result["counts"], self.expected_counts(
            concept, training_graded=4, training_positive=3,
            validation_graded=3, validation_positive=2,
            training_graded_queries=2, training_positive_queries=2,
            validation_graded_queries=1, validation_positive_queries=1,
        ))

    def test_legacy_schema_without_query_fingerprint_is_read_only_stale(self):
        concept = self.concept([{"id": "legacy-train", "query": "legacy train query", "split": "train"}])
        self.save(concept)
        self.judge(concept, "legacy-train", "legacy-positive", 2)
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE judgments_legacy (
                    concept_id TEXT NOT NULL, query_id TEXT NOT NULL, document_index TEXT NOT NULL,
                    document_id TEXT NOT NULL, rating INTEGER, pinned INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
                    PRIMARY KEY (concept_id, query_id, document_index, document_id)
                );
                INSERT INTO judgments_legacy
                    (concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at)
                SELECT concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at
                FROM judgments;
                DROP TABLE judgments;
                ALTER TABLE judgments_legacy RENAME TO judgments;
            """)
        before = self.db_snapshot()

        result = self.readiness(concept)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_code"], "train_positive_required")
        self.assertEqual(result["counts"], self.expected_counts(concept, stale=1))
        self.assertEqual(before, self.db_snapshot())

    def test_missing_database_and_missing_judgment_table_are_unavailable_read_only(self):
        concept = self.concept()
        with tempfile.TemporaryDirectory(prefix="es-rag-readiness-store-state-") as temp:
            missing_db, missing_client = self.new_secondary_store_client()
            status, payload = missing_client.post("/api/concepts/tune/readiness", {"concept": concept})
            self.assertEqual(status, 503)
            self.assertIn("error", payload)
            self.assertFalse(missing_db.exists())

            no_judgments, no_judgments_client = self.new_secondary_store_client()
            with sqlite3.connect(no_judgments) as db:
                db.execute("CREATE TABLE concepts (id TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at TEXT NOT NULL)")
            original_bytes = no_judgments.read_bytes()
            status, payload = no_judgments_client.post("/api/concepts/tune/readiness", {"concept": concept})
            self.assertEqual(status, 503)
            self.assertIn("error", payload)
            self.assertEqual(no_judgments.read_bytes(), original_bytes)

    def test_initialized_empty_judgments_table_is_confirmed_zero_not_unavailable(self):
        concept = self.concept()
        with tempfile.TemporaryDirectory(prefix="es-rag-readiness-empty-store-") as temp:
            db_path, client = self.new_secondary_store_client()
            with sqlite3.connect(db_path) as db:
                db.execute("""
                    CREATE TABLE judgments (
                        concept_id TEXT NOT NULL, query_id TEXT NOT NULL,
                        document_index TEXT NOT NULL, document_id TEXT NOT NULL,
                        rating INTEGER, pinned INTEGER NOT NULL DEFAULT 0,
                        reason TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
                        query_fingerprint TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (concept_id, query_id, document_index, document_id)
                    )
                """)
            original_bytes = db_path.read_bytes()
            status, result = client.post("/api/concepts/tune/readiness", {"concept": concept})

            self.assertEqual(status, 200, result)
            self.assertEqual(result, {
                "eligible": False,
                "reason_code": "train_positive_required",
                "counts": self.expected_counts(concept),
                "scope": "label_readiness_only",
            })
            self.assertEqual(db_path.read_bytes(), original_bytes)
            self.assertFalse(list(db_path.parent.glob(db_path.name + "-*")))

    def test_malformed_judgments_table_is_unavailable_without_mutation(self):
        concept = self.concept()
        with tempfile.TemporaryDirectory(prefix="es-rag-readiness-malformed-store-") as temp:
            db_path, client = self.new_secondary_store_client()
            with sqlite3.connect(db_path) as db:
                db.execute("""
                    CREATE TABLE judgments (
                        concept_id TEXT NOT NULL, document_index TEXT NOT NULL,
                        document_id TEXT NOT NULL, rating INTEGER,
                        pinned INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    )
                """)
                db.execute(
                    "INSERT INTO judgments VALUES(?,?,?,?,?,?,?)",
                    (concept["id"], "synthetic-index", "malformed-positive", 3, 0, "", "synthetic-time"),
                )
            original_bytes = db_path.read_bytes()
            status, payload = client.post("/api/concepts/tune/readiness", {"concept": concept})

            self.assertEqual(status, 503)
            self.assertIn("error", payload)
            self.assertEqual(db_path.read_bytes(), original_bytes)
            self.assertFalse(list(db_path.parent.glob(db_path.name + "-*")))

    def test_aggregate_only_and_request_does_not_mutate_database(self):
        concept = self.concept()
        self.save(concept)
        self.judge(concept, "train-other", "private-document-id", 2, reason="private reason sentinel")
        before = self.db_snapshot()

        result = self.readiness(concept)
        repeated = self.readiness(concept)

        self.assertEqual(before, self.db_snapshot())
        self.assertEqual(result, repeated)
        serialized = json.dumps(result)
        for private in ("private-document-id", "private reason sentinel", concept["id"], "connection", "credential"):
            self.assertNotIn(private, serialized)
        self.assertEqual(set(result), {"eligible", "reason_code", "counts", "scope"})
        self.assertEqual(set(result["counts"]), set(self.expected_counts(concept)))


if __name__ == "__main__":
    unittest.main()
