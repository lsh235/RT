"""Independent HTTP + live-Elasticsearch acceptance checks.

Run directly with `ES_RAG_RUN_LIVE=1` and `ES_RAG_ACCEPTANCE_ES_URL` set to an
isolated disposable Elasticsearch service. The test creates and deletes only
its unique fixture indices; the configured source index is queried read-only.
"""

from __future__ import annotations

import hashlib
import copy
import http.cookiejar
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))
ES_URL = os.environ.get("ES_RAG_ACCEPTANCE_ES_URL", "http://127.0.0.1:9200").rstrip("/")
SOURCE_INDEX = os.environ.get("ES_RAG_ACCEPTANCE_SOURCE_INDEX", "jira-grpc-issues-9-5-5")
CONNECTION = {"url": ES_URL, "auth": {"type": "none"}}
APP_PYTHON = os.environ.get("ES_RAG_ACCEPTANCE_PYTHON", str(ROOT / ".venv/bin/python"))
APP_CWD = os.environ.get("ES_RAG_ACCEPTANCE_APP_CWD", str(ROOT))


def request(url: str, method: str = "GET", body: object | None = None, timeout: float = 12,
            *, opener=None, headers: dict[str, str] | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={**({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})},
        method=method,
    )
    try:
        with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {"error": raw.decode("utf-8", errors="replace")}
        return exc.code, parsed


def es_request(path: str, method: str = "GET", body: object | None = None):
    status, result = request(f"{ES_URL}/{path.lstrip('/')}", method, body)
    if status >= 400:
        raise RuntimeError(f"Elasticsearch {status} on {path}: {result}")
    return result


def source_fingerprint(index: str) -> dict[str, object]:
    """Stable count + full small corpus or bounded sample, locally sorted by ID."""
    count = es_request(f"{index}/_count")["count"]
    sample = es_request(f"{index}/_search", "POST", {
        "size": min(int(count), 1000),
        "track_total_hits": True,
        "query": {"match_all": {}},
        "sort": ["_shard_doc"],
        "_source": True,
    })["hits"]["hits"]
    sample.sort(key=lambda hit: str(hit.get("_id", "")))
    hashes = [
        (hit["_id"], hashlib.sha256(json.dumps(
            hit.get("_source", {}), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest())
        for hit in sample
    ]
    return {"count": count, "sample_ids_and_source_sha256": hashes}


def field_texts(source: object, path: str) -> list[str]:
    """Resolve a dotted mapping path through object arrays for excerpt checks."""
    parts = path.split(".")
    def walk(value: object, offset: int) -> list[str]:
        if offset == len(parts):
            if isinstance(value, str):
                return [value]
            if isinstance(value, list):
                return [item for item in value if isinstance(item, str)]
            return []
        if isinstance(value, list):
            return [text for item in value for text in walk(item, offset)]
        if isinstance(value, dict):
            return walk(value.get(parts[offset]), offset + 1)
        return []
    return walk(source, 0)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LiveConceptAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("ES_RAG_RUN_LIVE") != "1":
            raise unittest.SkipTest("NOT RUN: set ES_RAG_RUN_LIVE=1 and ES_RAG_ACCEPTANCE_ES_URL to select live Elasticsearch acceptance")
        if not os.environ.get("ES_RAG_ACCEPTANCE_ES_URL"):
            raise unittest.SkipTest("NOT RUN: live suite selected but ES_RAG_ACCEPTANCE_ES_URL is unset")
        try:
            status, root = request(ES_URL + "/")
        except Exception as exc:
            raise unittest.SkipTest(f"Live Elasticsearch unavailable at configured URL: {exc}")
        if status != 200 or "version" not in root:
            raise unittest.SkipTest(f"Configured endpoint is not Elasticsearch: HTTP {status}")
        cls.es_version = root["version"].get("number", "unknown")
        cls.source_before = None
        try:
            if es_request(f"{SOURCE_INDEX}/_count").get("count") is not None:
                cls.source_before = source_fingerprint(SOURCE_INDEX)
        except Exception:
            # The fixture workflow is still meaningful when a deployment has no
            # preselected reference corpus; report that source proof as NOT RUN.
            pass

        cls.fixture_index = f"concept-accept-{uuid.uuid4().hex[:12]}"
        es_request(cls.fixture_index, "PUT", {"mappings": {"properties": {
            "title": {"type": "text"},
            "body": {"type": "text"},
            "project": {"type": "keyword"},
            "comments": {"type": "nested", "properties": {
                "text": {"type": "text"}, "author": {"type": "keyword"}
            }},
        }}})
        docs = [
            ("Doc-A", {"title": "Deadline exceeded during request recovery", "body":
                "Timeout retry resumed the failed request after its deadline expired.",
                "project": "alpha", "comments": [{"text": "Recovery worked after jittered delay", "author": "one"}]}),
            ("doc-a", {"title": "Retry after temporary transport failure", "body":
                "A transient transport failure is retried with jittered exponential backoff.", "project": "alpha",
                "comments": [{"text": "Nested resilience marker; request recovered", "author": "two"}]}),
            ("excluded", {"title": "Connect timeout disables retry", "body":
                "A connect timeout is terminal and no backoff is attempted.", "project": "beta", "comments": []}),
            ("pin-only", {"title": "Unrelated documentation about billing", "body":
                "Invoice reconciliation and account statements.", "project": "gamma", "comments": []}),
            ("unjudged", {"title": "Deadline monitoring", "body":
                "A monitor records elapsed time but says nothing about recovery.", "project": "alpha",
                "comments": [{"text": "alpha", "author": "one"}, {"text": "beta", "author": "two"}]}),
            ("description-only", {"title": "Connection signal", "body":
                "Connection watchdog sentinel marker.", "project": "alpha", "comments": []}),
        ]
        bulk = "".join(
            json.dumps({"index": {"_index": cls.fixture_index, "_id": doc_id}}) + "\n" +
            json.dumps(source) + "\n" for doc_id, source in docs
        )
        try:
            data = bulk.encode()
            req = urllib.request.Request(
                ES_URL + "/_bulk?refresh=true", data=data,
                headers={"Content-Type": "application/x-ndjson"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                bulk_result = json.loads(response.read())
            if bulk_result.get("errors"):
                raise RuntimeError("Elasticsearch fixture bulk indexing returned errors")
            cls.fixture_before = source_fingerprint(cls.fixture_index)
        except Exception:
            es_request(cls.fixture_index, "DELETE")
            raise

        cls.temp = tempfile.TemporaryDirectory(prefix="es-rag-concept-accept-")
        cls.db_path = Path(cls.temp.name) / "concepts.sqlite3"
        cls.server_log = Path(cls.temp.name) / "server.log"
        cls.log_handle = cls.server_log.open("w+")
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = os.environ.copy()
        env["ES_RAG_CONCEPT_DB"] = str(cls.db_path)
        password = "temporary-live-test-password-9284"
        bootstrap = subprocess.run(
            [APP_PYTHON, "-m", "es_rag_tuner.server", "auth", "bootstrap-admin"],
            cwd=APP_CWD, env=env,
            input=f"live-acceptance\nLive Acceptance\n{password}\n{password}\n",
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
        )
        if bootstrap.returncode != 0:
            cls.log_handle.close()
            cls._cleanup_setup_failure()
            raise RuntimeError(f"temporary admin bootstrap failed: {bootstrap.stdout}")
        cls.server = subprocess.Popen(
            [APP_PYTHON, "-m", "es_rag_tuner.server", "--host", "127.0.0.1", "--port", str(cls.port)],
            cwd=APP_CWD, env=env, stdout=cls.log_handle, stderr=subprocess.STDOUT,
        )
        for _ in range(100):
            if cls.server.poll() is not None:
                cls.log_handle.flush()
                cls.log_handle.seek(0)
                detail = cls.log_handle.read()
                cls._cleanup_setup_failure()
                raise RuntimeError(f"workbench process exited with {cls.server.returncode}: {detail}")
            try:
                status, _ = request(cls.base + "/api/health", timeout=1)
                if status == 200:
                    break
            except Exception:
                time.sleep(0.1)
        else:
            cls._cleanup_setup_failure()
            raise RuntimeError("workbench did not become healthy within 10 seconds")

        cls.cookies = http.cookiejar.CookieJar()
        cls.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.cookies))
        status, login_state = request(cls.base + "/api/auth/session", opener=cls.opener)
        if status != 200 or not login_state.get("csrf_token") or not login_state.get("configured"):
            cls._cleanup_setup_failure()
            raise RuntimeError(f"temporary login bootstrap failed: HTTP {status} {login_state}")
        status, logged_in = request(
            cls.base + "/api/auth/login", "POST",
            {"username": "live-acceptance", "password": password}, opener=cls.opener,
            headers={"Origin": cls.base, "X-CSRF-Token": login_state["csrf_token"]},
        )
        if status != 200 or not logged_in.get("authenticated") or not logged_in.get("csrf_token"):
            cls._cleanup_setup_failure()
            raise RuntimeError(f"temporary authenticated session failed: HTTP {status} {logged_in}")
        cls.csrf_token = logged_in["csrf_token"]

        cls.concept = {
            "id": "acceptance-timeout-recovery",
            "name": "Timeout recovery",
            "description": "Connection watchdog sentinel marker",
            "aliases": ["timeout retry"],
            "related": [{"term": "jittered exponential backoff", "relation": "mechanism", "weight": 10}],
            "excluded_terms": ["connect timeout"],
            "corpus": {"index": cls.fixture_index, "title_field": "title",
                "text_fields": ["title", "body", "comments.text"], "filter_fields": ["project"]},
            "settings": {"size": 6, "candidate_size": 6, "mode": "bm25", "concept_weight": 1.0,
                "related_weight": 0.01, "field_boosts": {"title": 2, "body": 1, "comments.text": 1}, "rank_constant": 60},
            "queries": [
                {"id": "train-recovery", "query": "request recovery after deadline", "split": "train"},
                {"id": "validation-backoff", "query": "jittered exponential backoff", "split": "validation"},
            ],
        }

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait(timeout=5)
        if hasattr(cls, "fixture_index"):
            es_request(cls.fixture_index, "DELETE")
        if getattr(cls, "source_before", None) is not None:
            after = source_fingerprint(SOURCE_INDEX)
            if after != cls.source_before:
                raise AssertionError(f"configured source index changed: {SOURCE_INDEX}")
        if getattr(cls, "log_handle", None) and not cls.log_handle.closed:
            cls.log_handle.close()
        cls.temp.cleanup()

    @classmethod
    def _cleanup_setup_failure(cls):
        if hasattr(cls, "server") and cls.server.poll() is None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait(timeout=5)
        if getattr(cls, "log_handle", None) and not cls.log_handle.closed:
            cls.log_handle.close()
        if getattr(cls, "temp", None):
            cls.temp.cleanup()
        if getattr(cls, "fixture_index", None):
            try:
                es_request(cls.fixture_index, "DELETE")
            except Exception as exc:
                raise RuntimeError(f"failed to clean disposable index {cls.fixture_index}") from exc

    def setUp(self):
        self.concept = copy.deepcopy(type(self).concept)
        self.concept["id"] = f"{self.concept['id']}-{uuid.uuid4().hex[:8]}"

    def post(self, route: str, body: dict[str, object], expect: int = 200):
        status, payload = request(self.base + route, "POST", body, opener=self.opener,
            headers={"Origin": self.base, "X-CSRF-Token": self.csrf_token})
        self.assertEqual(status, expect, f"{route} returned {status}: {payload}")
        return payload

    def save_concept(self):
        return self.post("/api/concepts/save", {"concept": self.concept})["concept"]

    def preview(self, query: str = "request recovery after deadline", query_id: str = "train-recovery"):
        return self.post("/api/concepts/preview", {
            "connection": CONNECTION, "concept": self.concept, "query": query, "query_id": query_id,
        })

    def test_schema_and_source_read_only(self):
        before = source_fingerprint(SOURCE_INDEX) if self.source_before is not None else None
        schema = self.post("/api/corpus/schema", {"connection": CONNECTION, "index": self.fixture_index})
        fields = {field["name"]: field for field in schema["fields"]}
        self.assertEqual(fields["title"]["type"], "text")
        self.assertTrue(fields["title"]["searchable"])
        self.assertTrue(fields["comments.text"]["nested"])
        self.assertEqual(source_fingerprint(self.fixture_index), self.fixture_before)
        if before is not None:
            self.assertEqual(source_fingerprint(SOURCE_INDEX), before)

    def test_quickstart_and_saved_query_identity(self):
        quick = self.post("/api/concepts/quickstart", {
            "connection": CONNECTION, "index": self.fixture_index,
            "query": "deadline recovery",
        })
        fields = {field["name"]: field for field in quick["fields"]}
        self.assertIn("title", quick["suggested_text_fields"])
        self.assertIn("body", quick["suggested_text_fields"])
        self.assertEqual(quick["suggested_title_field"], "title")
        self.assertIn("project", quick["suggested_filter_fields"])
        self.assertTrue(quick["sample_documents"])
        self.assertIn("title", fields)
        self.assertEqual(quick["index"], self.fixture_index)

        self.save_concept()
        first = self.post("/api/concepts/ensure-query", {
            "concept_id": self.concept["id"],
            "query": "new ad hoc novice query",
            "split": "train",
        })
        repeated = self.post("/api/concepts/ensure-query", {
            "concept_id": self.concept["id"],
            "query": "new ad hoc novice query",
            "split": "train",
        })
        rewritten = self.post("/api/concepts/ensure-query", {
            "concept_id": self.concept["id"],
            "query": "new ad hoc novice query rewritten",
            "split": "train",
        })
        self.assertEqual(first["query_id"], repeated["query_id"])
        self.assertNotEqual(first["query_id"], rewritten["query_id"])

    def test_quickstart_sample_keeps_late_keyword_title_with_many_text_fields(self):
        # A no-query sample must return the title even when it falls outside
        # the first 20 alphabetically ordered mapped text fields.
        index = f"concept-agent-nested-{uuid.uuid4().hex[:10]}"
        properties = {f"a{number:02d}": {"type": "text"} for number in range(24)}
        properties["title"] = {"type": "keyword"}
        es_request(index, "PUT", {"mappings": {"properties": properties}})
        es_request(index + "/_doc/title-sample?refresh=true", "PUT", {
            **{f"a{number:02d}": f"ordinary field {number}" for number in range(24)},
            "title": "The late mapped title must be visible",
        })
        try:
            quick = self.post("/api/concepts/quickstart", {
                "connection": CONNECTION, "index": index,
            })
            self.assertEqual(quick["suggested_title_field"], "title", quick)
            self.assertIn("title", quick["suggested_text_fields"], quick)
            self.assertTrue(quick["sample_documents"], quick)
            self.assertEqual(quick["sample_documents"][0]["source"]["title"][0],
                "The late mapped title must be visible", quick["sample_documents"][0])
        finally:
            es_request(index, "DELETE")

    def test_host_document_scope_nested_sample_and_ad_hoc_query_identity(self):
        from unittest.mock import patch

        from es_rag_tuner import ai_coach, concepts
        from es_rag_tuner.es_client import Connection as ESConnection

        connection = ESConnection.from_payload(CONNECTION)
        concept = copy.deepcopy(self.concept)
        concept["filters"] = [{"field": "project", "value": "alpha"}]
        concept["excluded_terms"] = []
        concept = concepts.validate_concept(concept)
        concepts._validate_search_fields(connection, concept)
        session = {"concept": concept, "corpus": {
            "index": self.fixture_index,
            "text_fields": list(concept["corpus"]["text_fields"]),
            "filter_fields": list(concept["corpus"]["filter_fields"]),
        }}
        context = {"concept": concept, "query": "request recovery after deadline", "query_id": "train-recovery"}
        deadline = time.monotonic() + 30

        fetched, count = ai_coach._host_tool("get_document", {
            "document_index": self.fixture_index, "document_id": "Doc-A",
        }, connection, session, context, deadline)
        self.assertEqual(count, 1)
        self.assertEqual(fetched["_id"], "Doc-A")
        self.assertIn("Deadline exceeded during request recovery", fetched["selected_source_fields"]["title"][0]["text"])
        self.assertIn("Timeout retry resumed", fetched["selected_source_fields"]["body"][0]["text"])

        diagnosed, count = ai_coach._host_tool("diagnose_document", {
            "query": "connect timeout", "document_index": self.fixture_index, "document_id": "excluded",
        }, connection, session, context, deadline)
        self.assertEqual(count, 1)
        self.assertEqual(diagnosed["classification"], "filtered_out")

        nested_index = f"concept-agent-nested-{uuid.uuid4().hex[:10]}"
        es_request(nested_index, "PUT", {"mappings": {"properties": {
            "comments": {"type": "nested", "properties": {"text": {"type": "text"}}},
        }}})
        es_request(nested_index + "/_doc/nested-sample?refresh=true", "PUT", {
            "comments": [{"text": "Nested sample source remains original."}],
        })
        try:
            nested_concept = copy.deepcopy(concept)
            nested_concept["corpus"] = {"index": nested_index, "title_field": "", "text_fields": ["comments.text"], "filter_fields": []}
            nested_concept["filters"] = []
            nested_concept["settings"]["field_boosts"] = {"comments.text": 1}
            nested_concept = concepts.validate_concept(nested_concept)
            concepts._validate_search_fields(connection, nested_concept)
            nested_session = {"concept": nested_concept, "corpus": {
                "index": nested_index, "text_fields": ["comments.text"], "filter_fields": [],
            }}
            nested_context = {"concept": nested_concept}
            sampled, _ = ai_coach._host_tool("sample_documents", {}, connection, nested_session, nested_context, deadline)
            sampled_values = [
                entry["text"]
                for document in sampled["documents"]
                for entry in document.get("source", {}).get("comments.text", [])
            ]
            self.assertIn("Nested sample source remains original.", sampled_values, sampled)
        finally:
            es_request(nested_index, "DELETE")

        alternate_context = {**context, "query_id": "train-recovery"}
        with patch("es_rag_tuner.ai_coach.concepts.preview", return_value={
            "baseline": {"total": 0, "hits": []}, "candidate": {"total": 0, "hits": []},
        }) as preview:
            ai_coach._host_tool("preview_search", {"query": "billing reconciliation"}, connection, session, alternate_context, deadline)
        self.assertEqual(preview.call_args.kwargs["query"], "billing reconciliation")
        self.assertEqual(preview.call_args.kwargs["query_id"], "")

    def test_nested_text_and_nested_filter_are_executed(self):
        concept = copy.deepcopy(self.concept)
        concept["id"] = f"{concept['id']}-nested"
        concept["name"] = "Nested retrieval"
        concept["description"] = ""
        concept["aliases"] = ["nested resilience marker"]
        concept["related"] = []
        concept["excluded_terms"] = []
        concept["corpus"] = {"index": self.fixture_index, "title_field": "",
            "text_fields": ["comments.text"], "filter_fields": ["comments.author"]}
        concept["settings"]["field_boosts"] = {"comments.text": 1}
        concept["queries"] = [{"id": "nested-q", "query": "unseen nested concept", "split": "train"}]
        self.post("/api/concepts/save", {"concept": concept})
        result = self.post("/api/concepts/preview", {
            "connection": CONNECTION, "concept": concept, "query_id": "nested-q",
            "filters": [{"field": "comments.author", "value": "two"}],
        })
        hits = result["candidate"]["hits"]
        self.assertEqual([hit["_id"] for hit in hits], ["doc-a"])
        self.assertIn("nested resilience marker", hits[0]["snippet"].lower())
        self.assertIn("nested resilience marker", field_texts(hits[0]["source"], "comments.text")[0].lower())
        self.assertTrue(result["candidate"]["query"]["bool"].get("filter"))

    def test_saved_query_preview_evidence_and_label_survive_restart(self):
        self.save_concept()
        preview = self.preview()
        self.assertIn("baseline", preview)
        self.assertIn("candidate", preview)
        all_candidate = preview["candidate"]["hits"]
        self.assertTrue(all_candidate)
        excluded_ids = {hit["_id"] for hit in all_candidate}
        self.assertNotIn("excluded", excluded_ids)
        for hit in all_candidate:
            self.assertTrue(hit["snippet"])
            self.assertIn(hit["_index"], (self.fixture_index,))
            self.assertIsInstance(hit["evidence"], list)
            for ev in hit["evidence"]:
                self.assertIn(ev.get("kind"), {"concept", "definition", "alias", "related"})
                self.assertEqual(ev.get("basis"), "lexical")
                self.assertEqual(ev.get("status"), "candidate")
                text = json.dumps(ev, ensure_ascii=False).lower()
                self.assertNotIn("confirmed", text)
                self.assertNotIn("caused by", text)
            for excerpt in hit["snippet"].split(" … "):
                original_values = [value for field in self.concept["corpus"]["text_fields"]
                                   for value in field_texts(hit["source"], field)]
                clean_excerpt = excerpt.strip().strip("… ")
                self.assertTrue(any(clean_excerpt in original for original in original_values),
                                f"snippet is not a literal source-field excerpt: {excerpt!r}")
            for ev in hit["evidence"]:
                original_values = field_texts(hit["source"], ev["source_field"])
                clean_evidence = ev["snippet"].strip().strip("… ")
                self.assertTrue(any(clean_evidence in original for original in original_values),
                                f"evidence excerpt is not from {ev['source_field']}: {ev['snippet']!r}")
        by_id = {hit["_id"]: hit for hit in all_candidate}
        self.assertIn("Doc-A", by_id, f"candidate IDs: {sorted(by_id)}")
        self.assertIn("doc-a", by_id, f"candidate IDs: {sorted(by_id)}")
        self.assertTrue(any(ev["kind"] == "alias" and ev["term"] == "timeout retry"
                            for ev in by_id["Doc-A"]["evidence"]))
        self.assertTrue(any(ev["kind"] == "related" and ev["term"] == "jittered exponential backoff"
                            for ev in by_id["doc-a"]["evidence"]))
        # The alias occurs late in body, after the title. Evidence excerpt must
        # include it and remain a literal substring of the original body value.
        late_body = by_id["Doc-A"]["snippet"]
        self.assertIn("timeout retry", late_body.lower())
        self.assertTrue(any("timeout retry" in value.lower() and value in late_body
                            for value in field_texts(by_id["Doc-A"]["source"], "body")))
        self.assertNotIn("description-only", {hit["_id"] for hit in preview["baseline"]["hits"]})
        self.assertIn("description-only", {hit["_id"] for hit in all_candidate})
        self.assertLessEqual(len(all_candidate), self.concept["settings"]["candidate_size"])
        # A related mechanism is only lexical candidate evidence; it must not be
        # worded as an asserted factual relationship in response strings.
        payload_text = json.dumps(preview, ensure_ascii=False).lower()
        self.assertNotIn("confirmed relationship", payload_text)

        grade = self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "train-recovery",
            "document_index": self.fixture_index, "document_id": "Doc-A", "rating": 3,
            "pinned": False, "reason": "Recovery evidence in body",
        })["judgment"]
        self.assertEqual(grade["rating"], 3)
        self.assertEqual(grade["document_id"], "Doc-A")
        explicit_null = self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "train-recovery",
            "document_index": self.fixture_index, "document_id": "unjudged", "rating": None,
            "pinned": False,
        })["judgment"]
        self.assertIsNone(explicit_null["rating"])
        zero = self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "train-recovery",
            "document_index": self.fixture_index, "document_id": "excluded", "rating": 0,
            "pinned": False,
        })["judgment"]
        self.assertEqual(zero["rating"], 0)
        self.assertNotEqual(explicit_null["rating"], zero["rating"])
        # Exact case-sensitive IDs and cross-query labels must not collide.
        lower = self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "train-recovery",
            "document_index": self.fixture_index, "document_id": "doc-a", "rating": 2,
            "pinned": False,
        })["judgment"]
        val = self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "validation-backoff",
            "document_index": self.fixture_index, "document_id": "Doc-A", "rating": 1,
            "pinned": False,
        })["judgment"]
        self.assertEqual(lower["document_id"], "doc-a")
        self.assertEqual(val["query_id"], "validation-backoff")

        marker = "CONCEPT_ACCEPTANCE_SECRET_SENTINEL"
        secret_probe = {**CONNECTION, "auth": {"type": "none", "username": "local-only", "password": marker}}
        secret_preview = self.post("/api/concepts/preview", {
            "connection": secret_probe, "concept": self.concept, "query_id": "train-recovery",
        })
        self.assertNotIn(marker, json.dumps(secret_preview, ensure_ascii=False))
        self.assertNotIn(marker.encode(), self.db_path.read_bytes())

        # A saved query ID cannot be silently paired with unrelated ad-hoc text.
        self.post("/api/concepts/preview", {
            "connection": CONNECTION, "concept": self.concept, "query_id": "train-recovery",
            "query": "unrelated invoice ledger",
        }, expect=400)

        # Restart the process against the same SQLite file and ensure both the
        # concept and graded states are returned in the next preview.
        self.restart_server()
        concepts = self.post("/api/concepts/list", {})["concepts"]
        self.assertTrue(any(item["id"] == self.concept["id"] for item in concepts))
        reloaded = self.preview()
        judgments = {hit["_id"]: hit.get("judgment") for hit in reloaded["candidate"]["hits"]}
        self.assertEqual(judgments["Doc-A"]["rating"], 3)

    def test_evidence_phrases_do_not_cross_nested_array_children(self):
        concept = copy.deepcopy(self.concept)
        concept["aliases"] = ["alpha beta"]
        concept["related"] = []
        concept["excluded_terms"] = []
        preview = self.post("/api/concepts/preview", {
            "connection": CONNECTION, "concept": concept, "query": "deadline monitoring",
        })
        candidate = next(hit for hit in preview["candidate"]["hits"] if hit["_id"] == "unjudged")
        false_phrase = [ev for ev in candidate["evidence"]
                        if ev["kind"] == "alias" and ev["term"].casefold() == "alpha beta"]
        self.assertEqual(false_phrase, [], "separate nested values must not be joined into a phrase match")
        for ev in candidate["evidence"]:
            original_values = field_texts(candidate["source"], ev["source_field"])
            excerpt = ev["snippet"].strip().strip("… ")
            self.assertTrue(any(excerpt in scalar for scalar in original_values),
                            f"evidence combined separate source scalars: {ev!r}")

    def restart_server(self):
        self.server.terminate()
        self.server.wait(timeout=5)
        env = os.environ.copy()
        env["ES_RAG_CONCEPT_DB"] = str(self.db_path)
        self.server = subprocess.Popen(
            [APP_PYTHON, "-m", "es_rag_tuner.server", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=APP_CWD, env=env, stdout=type(self).log_handle, stderr=subprocess.STDOUT,
        )
        type(self).server = self.server
        for _ in range(100):
            if self.server.poll() is not None:
                self.fail(f"workbench restart exited with {self.server.returncode}")
            try:
                if request(self.base + "/api/health", timeout=1)[0] == 200:
                    status, session = request(self.base + "/api/auth/session", opener=self.opener)
                    if status != 200 or not session.get("authenticated") or not session.get("csrf_token"):
                        self.fail(f"workbench restart lost authenticated session: HTTP {status} {session}")
                    type(self).csrf_token = session["csrf_token"]
                    return
            except Exception:
                time.sleep(0.1)
        self.fail("workbench restart did not become healthy")

    def test_missing_wanted_document_can_be_fetched_and_judged(self):
        self.save_concept()
        fetched = self.post("/api/concepts/document", {
            "connection": CONNECTION, "index": self.fixture_index, "document_id": "pin-only",
        })
        self.assertEqual(fetched["document_id"], "pin-only")
        self.assertEqual(fetched["source"]["title"], "Unrelated documentation about billing")
        judged = self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "train-recovery",
            "document_index": self.fixture_index, "document_id": "pin-only", "rating": 3,
            "pinned": True,
        })["judgment"]
        self.assertEqual(judged["document_id"], "pin-only")
        self.assertTrue(judged["pinned"])
        preview = self.preview()
        pinned = [hit for hit in preview["candidate"]["hits"] if hit["_id"] == "pin-only"]
        self.assertEqual(len(pinned), 1)
        self.assertTrue(pinned[0]["pinned"])
        self.assertIsNone(pinned[0]["organic_rank"])
        pin_row = next(row for row in preview["comparison"] if row["document_id"] == "pin-only")
        self.assertIsNone(pin_row.get("baseline_rank"))
        self.assertIsNone(pin_row.get("candidate_rank"))

    def test_metadata_filter_is_compiled_and_applied(self):
        self.save_concept()
        result = self.post("/api/concepts/preview", {
            "connection": CONNECTION, "concept": self.concept,
            "query_id": "train-recovery", "filters": [{"field": "project", "value": "alpha"}],
        })
        for result_set in (result["baseline"], result["candidate"]):
            self.assertTrue(result_set["query"]["bool"].get("filter"))
            self.assertTrue(all(hit["source"]["project"] == "alpha" for hit in result_set["hits"]))

    def test_saved_filter_scope_is_reused_by_preview_tuning_and_run_snapshot(self):
        # Filters are part of a reusable retrieval profile, not transient UI state.
        self.concept["filters"] = [{"field": "project", "value": "alpha"}]
        self.save_concept()
        loaded = self.post("/api/concepts/list", {})["concepts"]
        persisted = next(item for item in loaded if item["id"] == self.concept["id"])
        self.assertEqual(persisted.get("filters"), self.concept["filters"])

        preview = self.preview()
        for result_set in (preview["baseline"], preview["candidate"]):
            self.assertTrue(result_set["query"]["bool"].get("filter"))
            self.assertTrue(all(hit["source"]["project"] == "alpha" for hit in result_set["hits"]))
        self.assertNotIn("excluded", {hit["_id"] for hit in preview["baseline"]["hits"]})
        self.assertNotIn("pin-only", {hit["_id"] for hit in preview["candidate"]["hits"]})

        for docid, rating in (("Doc-A", 0), ("doc-a", 3)):
            self.post("/api/concepts/judge", {
                "concept_id": self.concept["id"], "query_id": "train-recovery",
                "document_index": self.fixture_index, "document_id": docid,
                "rating": rating, "pinned": False,
            })
        tuned = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": persisted, "passes": 1,
        })
        for split in ("train",):
            for variant in ("baseline", "tuned"):
                rows = tuned["output_snapshot"][split][variant]["train-recovery"]
                self.assertTrue(all(row["index"] == self.fixture_index for row in rows))
                self.assertFalse({row["id"] for row in rows} & {"excluded", "pin-only"})
        run_rows = self.post("/api/concepts/runs", {"concept_id": self.concept["id"]})["runs"]
        run = next(row for row in run_rows if row["run_id"] == tuned["run_id"])
        snapshot = run["input_snapshot"]["concept"]
        self.assertEqual(snapshot.get("filters"), self.concept["filters"])
        self.assertEqual(run.get("effective_filters"), self.concept["filters"])
        self.assertEqual(run["settings"], tuned["settings"])

    def test_saved_experiment_run_export_is_complete_private_and_read_only(self):
        """A saved run export is exact, bounded, and independent of live ES."""
        self.concept["queries"] = [self.concept["queries"][0]]
        self.concept["queries"][0]["query"] = "run-export recovery sentinel"
        self.save_concept()

        # Three states must survive export distinctly: positive, explicit grade
        # zero, and an explicitly unjudged row. The source sentinel proves the
        # export carries ranking evidence without embedding fetched source text.
        for document_id, rating, reason in (
            ("Doc-A", 3, "password=run-export-credential-sentinel positive judgment"),
            ("excluded", 0, "explicit grade zero"),
            ("doc-a", None, "left unjudged"),
        ):
            self.post("/api/concepts/judge", {
                "concept_id": self.concept["id"], "query_id": "train-recovery",
                "document_index": self.fixture_index, "document_id": document_id,
                "rating": rating, "pinned": False, "reason": reason,
            })

        preview = self.preview("run-export recovery sentinel", "train-recovery")
        tuned = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": self.concept, "passes": 1,
        })
        self.assertIsNone(tuned["validation"])
        self.assertIn("validation_unavailable", tuned["warning_codes"])

        before = source_fingerprint(self.fixture_index)
        # This route intentionally takes identity only. It must export the
        # immutable saved run without asking Elasticsearch for a connection.
        artifact = self.post("/api/concepts/runs/export", {
            "concept_id": self.concept["id"], "run_id": tuned["run_id"],
        })
        self.assertEqual(source_fingerprint(self.fixture_index), before)

        self.assertEqual(artifact.get("format"), "es-rag-experiment-run")
        self.assertEqual(artifact.get("version"), 1)
        self.assertTrue(artifact.get("exported_at"))
        run = artifact.get("run")
        self.assertIsInstance(run, dict)
        self.assertEqual(run.get("run_id"), tuned["run_id"])
        self.assertEqual(run.get("concept_id"), self.concept["id"])
        self.assertEqual(run.get("kind"), "tune")

        completeness = artifact.get("completeness")
        self.assertIsInstance(completeness, dict)
        self.assertFalse(completeness.get("truncated"))
        self.assertEqual(completeness.get("judgment_count"), 3)

        input_snapshot = run["input_snapshot"]
        self.assertEqual(input_snapshot["concept"]["id"], self.concept["id"])
        self.assertEqual(input_snapshot["concept"]["queries"], self.concept["queries"])
        judgments = input_snapshot["judgments"]
        by_document = {row["document_id"]: row for row in judgments}
        self.assertEqual(set(by_document), {"Doc-A", "excluded", "doc-a"})
        self.assertEqual(by_document["Doc-A"]["rating"], 3)
        self.assertEqual(by_document["excluded"]["rating"], 0)
        self.assertIsNone(by_document["doc-a"]["rating"])
        self.assertEqual(by_document["doc-a"]["reason"], "left unjudged")

        # Preserve split metrics, aggregate metrics, and per-query evidence.
        self.assertIsNone(run["validation"])
        self.assertIn("train", run)
        for variant in ("baseline", "tuned"):
            aggregate = run["train"][variant]
            self.assertIn("ndcg_at_k", aggregate)
            self.assertIn("judged_coverage_at_k", aggregate)
            self.assertEqual(aggregate["query_count"], 1)
            self.assertEqual(aggregate["queries"][0]["query_id"], "train-recovery")
            self.assertIn("ndcg_at_k", aggregate["queries"][0])

        reproducibility = run["reproducibility"]
        for key in ("index", "mapping_fingerprint", "query_fingerprint",
                    "concept_fingerprint", "filters_fingerprint",
                    "judgment_fingerprint", "settings_fingerprint", "algorithm"):
            self.assertTrue(reproducibility.get(key), key)
        self.assertIsNotNone(run["output_snapshot"]["train"]["baseline"]["train-recovery"])
        self.assertIsNotNone(run["output_snapshot"]["train"]["tuned"]["train-recovery"])

        def count_output_rows(value):
            if isinstance(value, dict):
                return sum(count_output_rows(item) for item in value.values())
            if isinstance(value, list):
                return len(value)
            return 0

        self.assertEqual(completeness.get("output_entry_count"),
                         count_output_rows(run["output_snapshot"]))

        rendered = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
        for forbidden in (
            str(self.db_path), "Timeout retry resumed the failed request after its deadline expired.",
            "run-export-credential-sentinel",
        ):
            self.assertNotIn(forbidden.lower(), rendered.lower())
        self.assertIn("password=[REDACTED]", rendered)
        def collect_keys(value):
            if isinstance(value, dict):
                return set(value) | set().union(*(collect_keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(collect_keys(item) for item in value)) if value else set()
            return set()

        private_key_fragments = ("credential", "password", "token", "apikey", "secret",
                                 "provider", "account", "username", "databasepath", "dbpath")
        self.assertFalse(any(any(fragment in str(key).lower().replace("_", "")
                                  for fragment in private_key_fragments)
                             for key in collect_keys(artifact)))
        self.assertTrue(any("validation_unavailable" in text.lower()
                            or "validation evidence is unavailable" in text.lower()
                            or "validation judgments are unavailable" in text.lower()
                            for text in artifact.get("limitations", [])))
        self.assertTrue(any("review" in text.lower() and "sharing" in text.lower()
                            for text in artifact.get("limitations", [])), artifact.get("limitations"))

        all_runs = self.post("/api/concepts/runs", {})["runs"]
        unrelated_ids = {row["run_id"] for row in all_runs if row["run_id"] != tuned["run_id"]}
        self.assertTrue(unrelated_ids)
        self.assertIn(preview["run_id"], unrelated_ids)
        self.assertTrue(all(run_id not in rendered for run_id in unrelated_ids))

        preview_artifact = self.post("/api/concepts/runs/export", {
            "concept_id": self.concept["id"], "run_id": preview["run_id"],
        })
        self.assertEqual(preview_artifact.get("format"), "es-rag-experiment-run")
        self.assertEqual(preview_artifact.get("version"), 1)
        self.assertEqual(preview_artifact["run"]["run_id"], preview["run_id"])
        self.assertEqual(preview_artifact["run"]["kind"], "preview")
        self.assertEqual(preview_artifact["run"]["query"], "run-export recovery sentinel")
        preview_rows = preview_artifact["run"]["output_snapshot"]["baseline"]
        self.assertTrue(preview_rows)
        self.assertTrue(all(row["index"] == self.fixture_index and row.get("source_sha256")
                            for row in preview_rows))
        candidate_rows = preview_artifact["run"]["output_snapshot"]["candidate"]
        self.assertTrue(candidate_rows)
        self.assertTrue(all(row.get("id") and row.get("index") == self.fixture_index
                            and (row.get("rank") is not None or row.get("organic_rank") is not None)
                            for row in candidate_rows))
        for row in preview_rows + candidate_rows:
            self.assertNotIn("source", row)
        self.assertFalse(preview_artifact["completeness"]["truncated"])
        self.assertNotIn(tuned["run_id"], json.dumps(preview_artifact))
        self.assertEqual(source_fingerprint(self.fixture_index), before)

        # A run id cannot be exported through another concept's identity.
        self.post("/api/concepts/runs/export", {
            "concept_id": self.concept["id"] + "-foreign",
            "run_id": tuned["run_id"],
        }, expect=404)

    def test_two_saved_preview_runs_export_exact_comparison_context(self):
        """Two previews from one concept retain separate complete snapshots."""
        self.concept["queries"] = [self.concept["queries"][0]]
        saved_concept = self.save_concept()
        first = self.preview("request recovery after deadline", "train-recovery")
        second = self.preview("request recovery after deadline", "train-recovery")
        self.assertNotEqual(first["run_id"], second["run_id"])

        artifacts = [self.post("/api/concepts/runs/export", {
            "concept_id": self.concept["id"], "run_id": run["run_id"],
        }) for run in (first, second)]
        for preview, artifact in zip((first, second), artifacts):
            self.assertEqual(artifact["format"], "es-rag-experiment-run")
            self.assertEqual(artifact["version"], 1)
            self.assertFalse(artifact["completeness"]["truncated"])
            run = artifact["run"]
            self.assertEqual(run["run_id"], preview["run_id"])
            self.assertEqual(run["concept_id"], self.concept["id"])
            self.assertEqual(run["kind"], "preview")
            self.assertEqual(run["query"], "request recovery after deadline")
            self.assertEqual(run["input_snapshot"]["concept"], saved_concept)
            self.assertEqual(run["settings"], saved_concept["settings"])
            self.assertEqual(run["reproducibility"]["index"], self.fixture_index)
            self.assertTrue(run["reproducibility"]["index_identity"]["available"])
            for fingerprint in ("query_fingerprint", "mapping_fingerprint", "filters_fingerprint"):
                self.assertTrue(run["reproducibility"].get(fingerprint), fingerprint)
            for side in ("baseline", "candidate"):
                rows = run["output_snapshot"][side]
                self.assertTrue(rows)
                self.assertTrue(all(row.get("index") == self.fixture_index and row.get("id")
                                    and row.get("source_sha256") for row in rows))
                self.assertTrue(all("source" not in row and "judgment" not in row for row in rows))
            self.assertTrue(all(row.get("rank") is not None
                                for row in run["output_snapshot"]["baseline"]))
            self.assertTrue(all(row.get("organic_rank") is not None or row.get("pinned")
                                for row in run["output_snapshot"]["candidate"]))

        a, b = (artifact["run"] for artifact in artifacts)
        self.assertEqual(a["reproducibility"]["query_fingerprint"],
                         b["reproducibility"]["query_fingerprint"])
        self.assertEqual(a["reproducibility"]["mapping_fingerprint"],
                         b["reproducibility"]["mapping_fingerprint"])
        self.assertEqual(a["reproducibility"]["filters_fingerprint"],
                         b["reproducibility"]["filters_fingerprint"])
        self.assertEqual(a["reproducibility"]["index_identity"],
                         b["reproducibility"]["index_identity"])
        for key in ("baseline",):
            project = lambda rows: [(row["index"], row["id"], row["rank"], row["source_sha256"])
                                     for row in rows]
            self.assertEqual(project(a["output_snapshot"][key]),
                             project(b["output_snapshot"][key]))

    def test_versioned_export_matches_python_raw_search_and_mustache(self):
        """The external handoff must preserve the saved nested filter scope."""
        from es_rag_tuner.profile_runtime import search_profile

        concept = copy.deepcopy(self.concept)
        concept["name"] = "Nested exported profile"
        concept["description"] = ""
        concept["aliases"] = ["nested resilience marker"]
        concept["related"] = []
        concept["excluded_terms"] = []
        concept["corpus"] = {
            "index": self.fixture_index,
            "title_field": "",
            "text_fields": ["comments.text"],
            "filter_fields": ["comments.author"],
        }
        concept["settings"]["field_boosts"] = {"comments.text": 1}
        concept["settings"]["size"] = 6
        concept["settings"]["candidate_size"] = 6
        concept["filters"] = [{"field": "comments.author", "value": "two"}]
        saved = self.post("/api/concepts/save", {"concept": concept})["concept"]
        first_version = self.post("/api/concepts/versions", {"concept_id": saved["id"]})["versions"][0]

        # Save a later edit so restoring an older immutable version is tested.
        revised = copy.deepcopy(saved)
        revised["description"] = "later edit"
        self.post("/api/concepts/save", {"concept": revised})
        restored = self.post("/api/concepts/restore", {
            "concept_id": saved["id"], "version_id": first_version["version_id"],
        })
        self.assertEqual(restored["restored_from"], first_version["version_id"])
        self.assertEqual(restored["concept"]["filters"], concept["filters"])
        self.assertEqual(restored["concept"]["description"], "")

        exported = self.post("/api/concepts/export", {
            "connection": CONNECTION, "concept_id": saved["id"],
        })
        self.assertEqual(exported["format"], "es-rag-profile-v1")
        profile = exported["profile"]
        self.assertEqual(profile["concept"]["filters"], concept["filters"])
        self.assertEqual(profile["version_number"], restored["version_number"])
        payload = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("password", payload.lower())
        self.assertNotIn("CONCEPT_ACCEPTANCE_SECRET_SENTINEL", payload)

        query_text = "unseen nested concept"
        python_result = search_profile(CONNECTION, profile, query_text)
        python_ids = [(hit["_index"], hit["_id"]) for hit in python_result["hits"]]
        self.assertTrue(python_result["effective_filters"])
        self.assertEqual([doc_id for _, doc_id in python_ids], ["doc-a"])

        # The emitted ordinary Search API body uses the same nested clauses and
        # saved filters. Replace only its documented query marker for execution.
        def replace_marker(value):
            if isinstance(value, dict):
                return {key: replace_marker(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace_marker(item) for item in value]
            if value == "__ES_RAG_RUNTIME_QUERY__":
                return query_text
            return value

        raw_body = replace_marker(copy.deepcopy(exported["runtime"]["example_search_body"]))
        self.assertTrue(raw_body["query"]["bool"].get("filter"))
        self.assertIn('"nested"', json.dumps(raw_body["query"]))
        raw_hits = es_request(f"{self.fixture_index}/_search", "POST", raw_body)["hits"]["hits"]
        raw_ids = [(hit["_index"], hit["_id"]) for hit in raw_hits]
        self.assertEqual(raw_ids, python_ids)

        # Exercise the emitted Mustache source through Elasticsearch's renderer
        # and execute the rendered body against the same immutable fixture.
        rendered = es_request("_render/template", "POST", {
            "source": exported["runtime"]["search_template"]["source"],
            "params": {"query": query_text},
        })
        rendered_body = rendered.get("template_output")
        if isinstance(rendered_body, str):
            rendered_body = json.loads(rendered_body)
        self.assertIsInstance(rendered_body, dict, rendered)
        self.assertTrue(rendered_body["query"]["bool"].get("filter"))
        self.assertIn('"nested"', json.dumps(rendered_body["query"]))
        rendered_hits = es_request(f"{self.fixture_index}/_search", "POST", rendered_body)["hits"]["hits"]
        rendered_ids = [(hit["_index"], hit["_id"]) for hit in rendered_hits]
        self.assertEqual(rendered_ids, python_ids)

        # User query text is data in a Mustache template. JSON punctuation,
        # backslashes, braces, and line breaks must round-trip without making
        # the request invalid or changing the query value.
        special_query = 'quoted "phrase" \\path\n{literal braces}'
        special_render = es_request("_render/template", "POST", {
            "source": exported["runtime"]["search_template"]["source"],
            "params": {"query": special_query},
        })["template_output"]
        query_values = []
        def collect_queries(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "query" and isinstance(item, str):
                        query_values.append(item)
                    collect_queries(item)
            elif isinstance(value, list):
                for item in value:
                    collect_queries(item)
        collect_queries(special_render)
        self.assertIn(special_query, query_values)

    def test_candidate_pool_is_distinct_from_display_size(self):
        concept = copy.deepcopy(self.concept)
        concept["settings"]["size"] = 1
        concept["settings"]["candidate_size"] = 6
        self.post("/api/concepts/save", {"concept": concept})
        result = self.post("/api/concepts/preview", {
            "connection": CONNECTION, "concept": concept, "query_id": "train-recovery",
        })
        self.assertEqual(len(result["candidate"]["hits"]), 1)
        self.assertGreater(result["candidate"]["pool_count"], len(result["candidate"]["hits"]))

    def test_tuning_separates_train_validation_and_excludes_pins(self):
        self.save_concept()
        judgments = [
            ("train-recovery", "Doc-A", 0, False),
            ("train-recovery", "doc-a", 3, False),
            ("train-recovery", "excluded", 0, False),
            ("train-recovery", "pin-only", 3, True),
            ("validation-backoff", "Doc-A", 3, False),
            ("validation-backoff", "excluded", 0, False),
        ]
        for qid, docid, rating, pinned in judgments:
            self.post("/api/concepts/judge", {
                "concept_id": self.concept["id"], "query_id": qid,
                "document_index": self.fixture_index, "document_id": docid,
                "rating": rating, "pinned": pinned,
            })
        first = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": self.concept, "passes": 1,
        })
        self.assertGreater(first["judged_count"], 0)
        self.assertGreaterEqual(first["pinned_count"], 1)
        self.assertIn("baseline", first)
        self.assertIn("tuned", first)
        self.assertEqual(first["baseline"], first["train"]["baseline"])
        self.assertEqual(first["tuned"], first["train"]["tuned"])
        self.assertEqual(first["baseline"]["query_count"], first["tuned"]["query_count"])
        self.assertGreater(first["train"]["tuned"]["ndcg_at_k"], first["train"]["baseline"]["ndcg_at_k"])
        self.assertEqual(first.get("explicit_unjudged_count"), 0)
        self.assertGreater(first.get("unjudged_retrieved_count", 0), 0)
        self.assertIn("unjudged documents are omitted", first["train"]["baseline"]["ndcg_policy"])
        self.assertIsNotNone(first["validation"])
        self.assertIn("baseline", first["validation"])
        self.assertIn("tuned", first["validation"])
        self.assertEqual(first["validation"]["baseline"]["query_count"], first["validation"]["tuned"]["query_count"])

        second = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": self.concept, "passes": 1,
        })
        self.assertEqual(first["settings"], second["settings"])
        self.assertEqual(first["train"], second["train"])
        self.assertEqual(first["validation"], second["validation"])

        # Held-out labels are scoring-only: reverse them and prove they cannot
        # alter chosen train settings or train metrics.
        self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "validation-backoff",
            "document_index": self.fixture_index, "document_id": "Doc-A", "rating": 0,
            "pinned": False,
        })
        self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "validation-backoff",
            "document_index": self.fixture_index, "document_id": "excluded", "rating": 3,
            "pinned": False,
        })
        changed_validation = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": self.concept, "passes": 1,
        })
        self.assertEqual(first["settings"], changed_validation["settings"])
        self.assertEqual(first["train"], changed_validation["train"])

        # A pin with high user rating must never create a metric gain by itself.
        for qid, docid, rating, _ in judgments:
            if docid == "pin-only":
                self.post("/api/concepts/judge", {
                    "concept_id": self.concept["id"], "query_id": qid,
                    "document_index": self.fixture_index, "document_id": docid,
                    "rating": rating, "pinned": False,
                })
        no_pin = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": self.concept, "passes": 1,
        })
        self.assertEqual(first["baseline"], no_pin["baseline"])
        self.assertEqual(first["tuned"], no_pin["tuned"])
        self.assertEqual(first["train"], no_pin["train"])

    def test_validation_absence_is_explicitly_training_only(self):
        self.save_concept()
        for docid, rating in (("Doc-A", 3), ("excluded", 0)):
            self.post("/api/concepts/judge", {
                "concept_id": self.concept["id"], "query_id": "train-recovery",
                "document_index": self.fixture_index, "document_id": docid,
                "rating": rating, "pinned": False,
            })
        concept = dict(self.concept)
        concept["queries"] = [self.concept["queries"][0]]
        result = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": concept, "passes": 1,
        })
        self.assertIsNone(result["validation"])
        self.assertTrue(any("generalization" in str(w).lower() or "training-only" in str(w).lower()
                            for w in result.get("warnings", [])))

    def test_tune_rejects_when_no_train_grades_exist(self):
        self.save_concept()
        self.post("/api/concepts/judge", {
            "concept_id": self.concept["id"], "query_id": "validation-backoff",
            "document_index": self.fixture_index, "document_id": "Doc-A", "rating": 3,
            "pinned": False,
        })
        result = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": self.concept, "passes": 1,
        }, expect=400)
        self.assertIn("train split", str(result.get("error", "")))

    def test_tune_rejects_negative_only_training_grades(self):
        self.save_concept()
        for docid in ("Doc-A", "excluded"):
            self.post("/api/concepts/judge", {
                "concept_id": self.concept["id"], "query_id": "train-recovery",
                "document_index": self.fixture_index, "document_id": docid,
                "rating": 0, "pinned": False,
            })
        result = self.post("/api/concepts/tune", {
            "connection": CONNECTION, "concept": self.concept, "passes": 1,
        }, expect=400)
        self.assertRegex(str(result.get("error", "")), r"positive|relevant|관련|양성|양수")

    def test_fractional_and_nonfinite_values_are_rejected(self):
        fractional_size = copy.deepcopy(self.concept)
        fractional_size["id"] = f"{self.concept['id']}-fractional-size"
        fractional_size["settings"]["size"] = 1.5
        self.post("/api/concepts/save", {"concept": fractional_size}, expect=400)
        fractional_weight = copy.deepcopy(self.concept)
        fractional_weight["id"] = f"{self.concept['id']}-fractional-rating"
        self.post("/api/concepts/save", {"concept": fractional_weight})
        self.post("/api/concepts/judge", {
            "concept_id": fractional_weight["id"], "query_id": "train-recovery",
            "document_index": self.fixture_index, "document_id": "Doc-A", "rating": 1.5,
            "pinned": False,
        }, expect=400)
        nonfinite = copy.deepcopy(self.concept)
        nonfinite["related"][0]["weight"] = float("nan")
        self.post("/api/concepts/save", {"concept": nonfinite}, expect=400)


if __name__ == "__main__":
    unittest.main(verbosity=2)


if __name__ == "__main__":
    if os.environ.get("ES_RAG_RUN_LIVE") != "1":
        raise SystemExit("NOT RUN: select this suite explicitly with ES_RAG_RUN_LIVE=1 and ES_RAG_ACCEPTANCE_ES_URL")
    unittest.main(verbosity=2)
