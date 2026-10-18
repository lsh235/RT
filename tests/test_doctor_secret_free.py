import io
import json
import os
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from unittest import mock

import pytest

from es_rag_tuner import doctor


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_success_report_redacts_url_parts_but_keeps_estimates():
    markers = ["userinfo-user-marker", "userinfo-pass-marker", "query-secret-marker", "fragment-secret-marker", "sensitive-path-marker", "api-key-secret-marker"]
    url = "https://userinfo-user-marker:userinfo-pass-marker@example.test:9443/sensitive-path-marker/proxy?token=query-secret-marker#fragment-secret-marker"
    captured = {}
    payload = {
        "name": "synthetic-node", "cluster_name": "synthetic-cluster",
        "version": {"number": "8.12.1", "build_flavor": "default", "distribution": "elasticsearch"},
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        return FakeResponse(payload)

    output = io.StringIO()
    with mock.patch.dict(os.environ, {"ES_API_KEY": markers[-1]}, clear=True), mock.patch.object(urllib.request, "urlopen", fake_urlopen), redirect_stdout(output):
        doctor.main(["--url", url])
    report = json.loads(output.getvalue())
    assert report["ok"] is True
    assert report["url"] == "https://example.test:9443"
    assert report["version"] == "8.12.1"
    assert report["distribution"] == "Elasticsearch"
    assert report["feature_support_estimate"] == {"dense_vector": "likely", "knn_query": "likely"}
    assert captured["url"] == "https://example.test:9443/sensitive-path-marker/proxy/"
    assert captured["authorization"] == f"ApiKey {markers[-1]}"
    for marker in markers:
        assert marker not in output.getvalue()


def test_failure_report_suppresses_secret_bearing_transport_exception():
    markers = ["failure-user-marker", "failure-pass-marker", "failure-query-marker", "failure-fragment-marker", "failure-path-marker", "failure-auth-marker", "exception-secret-marker"]
    url = "https://failure-user-marker:failure-pass-marker@example.test/failure-path-marker?token=failure-query-marker#failure-fragment-marker"
    transport_message = "https://failure-user-marker:failure-pass-marker@example.test/failure-path-marker?token=failure-query-marker Authorization: Bearer failure-auth-marker failure-fragment-marker exception-secret-marker"
    output = io.StringIO()
    with mock.patch.dict(os.environ, {"ES_API_KEY": "failure-auth-marker"}, clear=True), mock.patch.object(urllib.request, "urlopen", side_effect=urllib.error.URLError(transport_message)), redirect_stdout(output):
        with pytest.raises(SystemExit) as exit_info:
            doctor.main(["--url", url])
    assert exit_info.value.code == 1
    report = json.loads(output.getvalue())
    assert report == {"ok": False, "error": "Elasticsearch transport request failed", "url": "https://example.test"}
    for marker in markers:
        assert marker not in output.getvalue()


def test_invalid_url_output_does_not_echo_malformed_input():
    marker = "invalid-url-secret-marker"
    output = io.StringIO()
    with redirect_stdout(output):
        with pytest.raises(SystemExit):
            doctor.main(["--url", f"https://user:{marker}@[broken"])
    assert marker not in output.getvalue()
    assert "<redacted>" in output.getvalue()
