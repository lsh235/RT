"""Focused tests for the developer CLI and non-mutating Elasticsearch doctor."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from es_rag_tuner.doctor import _feature_estimates, inspect_cluster, main


class DoctorTests(unittest.TestCase):
    def test_build_flavor_and_plugin_dependent_estimates(self):
        self.assertEqual(
            _feature_estimates("Elasticsearch", "default", "9.5.5"),
            {"dense_vector": "likely", "knn_query": "likely"},
        )
        self.assertEqual(
            _feature_estimates("Elasticsearch", "oss", "7.10.2"),
            {"dense_vector": "unsupported", "knn_query": "unknown"},
        )
        self.assertEqual(
            _feature_estimates("OpenSearch", "unknown", "2.17.1"),
            {"dense_vector": "unsupported", "knn_query": "unknown"},
        )
        self.assertEqual(
            _feature_estimates("Elasticsearch-compatible", "unknown", "not-a-version"),
            {"dense_vector": "unknown", "knn_query": "unknown"},
        )

    def test_payload_classification_does_not_treat_elasticsearch_tagline_as_distribution(self):
        payloads = [
            (
                {"tagline": "You Know, for Search", "version": {"number": "7.10.2", "build_flavor": "oss"}},
                "Elasticsearch", {"dense_vector": "unsupported", "knn_query": "unknown"},
            ),
            (
                {"tagline": "You Know, for Search", "version": {"number": "9.5.5", "build_flavor": "default"}},
                "Elasticsearch", {"dense_vector": "likely", "knn_query": "likely"},
            ),
            (
                {"tagline": "The OpenSearch Project: https://opensearch.org/", "version": {"number": "2.17.1"}},
                "OpenSearch", {"dense_vector": "unsupported", "knn_query": "unknown"},
            ),
        ]

        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return json.dumps(self.payload).encode()

        for payload, product, estimates in payloads:
            with self.subTest(product=product, version=payload["version"]["number"]):
                with patch("es_rag_tuner.doctor.urllib.request.urlopen", return_value=Response(payload)):
                    result = inspect_cluster("http://example.test:9200")
                self.assertEqual(result["distribution"], product)
                self.assertEqual(result["feature_support_estimate"], estimates)
                if product == "OpenSearch":
                    self.assertIn("plugin-dependent", result["feature_support_note"])

    def test_inspection_uses_only_root_get_and_redacts_url_credentials(self):
        payload = {"name": "node-a", "cluster_name": "test", "tagline": "You Know, for Search", "version": {"number": "9.5.5", "build_flavor": "default"}}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return json.dumps(payload).encode()

        with patch("es_rag_tuner.doctor.urllib.request.urlopen", return_value=Response()) as opener:
            result = inspect_cluster("http://private-user:private-pass@example.test:9200/custom?secret=discard")
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://example.test:9200/custom/")
        self.assertEqual(result["url"], "http://example.test:9200/custom")
        self.assertNotIn("private", json.dumps(result))
        self.assertIn("estimate", result["feature_support_note"])

    def test_cli_reports_connection_failure_with_nonzero_exit(self):
        stdout = io.StringIO()
        with patch("es_rag_tuner.doctor.inspect_cluster", side_effect=OSError("unreachable")), patch("sys.stdout", stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["--url", "https://user:secret@example.test:9243"])
        self.assertEqual(raised.exception.code, 1)
        self.assertNotIn("secret", stdout.getvalue())
        self.assertIn('"ok": false', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
