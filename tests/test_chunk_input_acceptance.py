"""Acceptance tests for the exact passage input shown in the document panel.

These tests use synthetic source dictionaries and stub the one document GET in
the HTTP test. They do not load the embedding model, contact Elasticsearch, or
open a configured/user SQLite database.
"""

from __future__ import annotations

import copy
import json
import socket
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from es_rag_tuner import embeddings
from es_rag_tuner.es_client import ElasticsearchError
from es_rag_tuner.server import WorkbenchHandler
try:
    from tests.cycle37_auth_test_support import install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import install_auth_fixture


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ChunkInputAcceptance(unittest.TestCase):
    def test_nonempty_unified_chunk_is_trimmed_prefixed_exactly_and_preferred(self):
        source = {
            "rag_chunk_text": " \n  unified passage  \n with internal spacing \t ",
            "summary": "must not be appended",
            "comments": [{"author": "hidden author", "body": "must not be appended"}],
        }

        result = embeddings.passage_input(source)

        self.assertEqual(result, {
            "text": "passage: unified passage  \n with internal spacing",
            "source": "rag_chunk_text",
        })

    def test_structured_fallback_uses_document_text_labels_and_comment_bodies(self):
        source = {
            "summary": "Brief summary",
            "error_signature": "TimeoutError",
            "description": "Request timed out",
            "steps_to_reproduce": "Call endpoint",
            "root_cause": "Socket stalled",
            "workaround_or_fix": "Retry request",
            "comments": [
                {"author": "private author", "body": "First comment"},
                {"author": "another private author", "body": "Second comment"},
            ],
        }

        result = embeddings.passage_input(source)

        self.assertEqual(result["source"], "structured_fields")
        self.assertEqual(result["text"], "passage: Summary: Brief summary\n\nError signature: TimeoutError\n\nDescription: Request timed out\n\nSteps to reproduce: Call endpoint\n\nRoot cause: Socket stalled\n\nWorkaround or fix: Retry request\n\nComment: First comment\n\nComment: Second comment")
        self.assertNotIn("private author", result["text"])
        self.assertNotIn("another private author", result["text"])

    def test_empty_source_is_empty_and_marked_unavailable_for_embedding(self):
        self.assertEqual(embeddings.passage_input({
            "rag_chunk_text": " \n\t ",
            "summary": "",
            "comments": [{"author": "ignored", "body": ""}],
        }), {"text": "", "source": "empty"})

    def test_document_http_api_adds_input_without_mutating_source_or_loading_model(self):
        source = {
            "rag_chunk_text": "  <script>alert('synthetic')</script> body  ",
            "summary": "Separate summary",
            "custom_metadata": {"keep": [1, "two"]},
            "comments": [{"author": "synthetic author", "body": "comment body"}],
        }
        original_source = copy.deepcopy(source)
        empty_source = {"summary": "", "rag_chunk_text": " \n \t ", "comments": []}
        observed_calls = []

        def fake_es_request(connection, method, path, body=None):
            observed_calls.append((method, path, body))
            if method != "GET":
                raise AssertionError(f"document input must not write: {method} {path}")
            document_id = path.rsplit("/", 1)[-1]
            documents = {"doc-1": source, "doc-empty": empty_source}
            return {
                "_index": "synthetic-index", "_id": document_id, "found": True,
                "_source": copy.deepcopy(documents[document_id]),
            }

        port = free_port()
        base = f"http://127.0.0.1:{port}"
        httpd = ThreadingHTTPServer(("127.0.0.1", port), WorkbenchHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            client = install_auth_fixture(self, base)
            with patch("es_rag_tuner.server.request", side_effect=fake_es_request), \
                    patch("es_rag_tuner.embeddings._model", side_effect=AssertionError("model must not load")):
                def fetch(document_id: str):
                    status, result = client.post("/api/document", {
                            "connection": {"url": "http://127.0.0.1:9200"},
                            "index": "synthetic-index",
                            "id": document_id,
                        })
                    self.assertEqual(status, 200, result)
                    return result

                result = fetch("doc-1")
                empty_result = fetch("doc-empty")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.assertEqual(observed_calls, [
            ("GET", "synthetic-index/_doc/doc-1", None),
            ("GET", "synthetic-index/_doc/doc-empty", None),
        ])
        self.assertEqual(result["_source"], original_source)
        self.assertEqual(result["embedding_input"], {
            "text": "passage: <script>alert('synthetic')</script> body",
            "source": "rag_chunk_text",
        })
        self.assertEqual(source, original_source)
        self.assertEqual(set(result["embedding_input"]), {"text", "source"})
        self.assertEqual(empty_result["_source"], empty_source)
        self.assertEqual(empty_result["embedding_input"], {"text": "", "source": "empty"})


if __name__ == "__main__":
    unittest.main()
