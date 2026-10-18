import json
import os
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from es_rag_tuner.es_client import Connection
from examples import benchmark_profile_runtime as benchmark


def test_concurrency_choices_are_bounded_and_results_are_aggregate_only():
    profile = {"format": "es-rag-profile-v1", "secret": "profile-secret-marker"}
    connection = Connection("https://host-secret-marker.example", "api_key", api_key="credential-secret-marker")
    query = "raw-query-secret-marker"
    for concurrency in (1, 2, 4):
        active = 0
        peak = 0
        call_count = 0
        lock = threading.Lock()

        def fake_search(_connection, _profile, _query):
            nonlocal active, peak, call_count
            with lock:
                active += 1
                call_count += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return {"hits": [{"_index": "private-index", "_id": "doc-secret-marker", "_source": {"text": "snippet-secret-marker"}}]}

        report = benchmark.run_benchmark(profile, connection, query, iterations=8, concurrency=concurrency, search=fake_search)
        assert call_count == 8
        assert peak <= concurrency
        assert report["concurrency"] == concurrency
        assert report["effective_workers"] == concurrency
        assert report["searches_completed"] == 8
        assert report["p50_ms"] >= 0 and report["p95_ms"] >= report["p50_ms"]
        assert report["throughput_per_second"] > 0
        rendered = json.dumps(report)
        for marker in ("host-secret-marker", "credential-secret-marker", "raw-query-secret-marker", "doc-secret-marker", "snippet-secret-marker", "profile-secret-marker"):
            assert marker not in rendered
        assert set(report) == {"concurrency", "effective_workers", "iterations", "searches_completed", "elapsed_seconds", "p50_ms", "p95_ms", "throughput_per_second"}


def test_iteration_cap_and_concurrency_reject_before_search():
    calls = []
    search = lambda *args, **kwargs: calls.append(args) or {"hits": []}
    profile = {"format": "es-rag-profile-v1"}
    connection = Connection("http://example.test")
    for iterations in (0, benchmark.MAX_ITERATIONS + 1, True):
        with pytest.raises(ValueError):
            benchmark.run_benchmark(profile, connection, "query", iterations=iterations, search=search)
    for concurrency in (3, 2.0, True):
        with pytest.raises(ValueError):
            benchmark.run_benchmark(profile, connection, "query", iterations=3, concurrency=concurrency, search=search)
    assert calls == []


def test_cli_prints_only_aggregate_fields(tmp_path, capsys):
    marker_values = ["url-secret-marker", "user-secret-marker", "pass-secret-marker", "api-secret-marker", "query-secret-marker"]
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({"profile": {"format": "es-rag-profile-v1", "label": "profile-secret-marker"}}), encoding="utf-8")
    result = {"concurrency": 2, "effective_workers": 2, "iterations": 5, "searches_completed": 5, "elapsed_seconds": 0.2, "p50_ms": 30.0, "p95_ms": 45.0, "throughput_per_second": 25.0}
    with mock.patch.dict(os.environ, {"ES_URL": f"https://{marker_values[0]}.example", "ES_USERNAME": marker_values[1], "ES_PASSWORD": marker_values[2], "ES_API_KEY": marker_values[3], "ES_BENCHMARK_QUERY": marker_values[4]}, clear=True), mock.patch.object(benchmark, "run_benchmark", return_value=result) as run:
        assert benchmark.main([str(profile_path), "--iterations", "5", "--concurrency", "2"]) == 0
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert report == result
    for marker in (*marker_values, "profile-secret-marker"):
        assert marker not in stdout
    run.assert_called_once()
    assert run.call_args.kwargs["iterations"] == 5
    assert run.call_args.kwargs["concurrency"] == 2


def test_cli_transport_failure_does_not_print_exception_details(tmp_path, capsys):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({"profile": {"format": "es-rag-profile-v1"}}), encoding="utf-8")
    marker = "transport-secret-marker"
    with mock.patch.dict(os.environ, {"ES_URL": "http://example.test", "ES_BENCHMARK_QUERY": "query-secret-marker"}, clear=True), mock.patch.object(benchmark, "run_benchmark", side_effect=RuntimeError(marker)):
        assert benchmark.main([str(profile_path)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert marker not in output.err and "query-secret-marker" not in output.err
    assert output.err == "Benchmark failed; details were suppressed to protect query and connection data.\n"
