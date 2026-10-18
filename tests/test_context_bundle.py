"""Synthetic unit coverage for external profile context artifacts."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from es_rag_tuner.context_bundle import ContextBundleError, build_context_bundle


PROFILE = "a" * 64


def hit(index="idx-a", doc_id="doc-1", rank=1, snippet="bounded snippet", **extra):
    return {"_index": index, "_id": doc_id, "rank": rank, "snippet": snippet, **extra}


def result(hits=None, **extra):
    return {"index": "idx-a", "query": "sample query", "profile_fingerprint": PROFILE,
            "total": len(hits or []), "hits": hits or [], **extra}


def count_whitespace(text: str) -> int:
    return len(text.split())


def make_bundle(value, *, max_tokens=4096, max_entries=20, counter=count_whitespace):
    return build_context_bundle(value, token_counter=counter, counter_name="test-whitespace-v1",
                                max_tokens=max_tokens, max_entries=max_entries)


def test_exact_identity_deduplicates_and_keeps_first_slot_with_best_rank_provenance():
    response = result([
        hit("idx-a", "same", 5, "first result", source_sha256="A" * 64),
        hit("idx-b", "same", 1, "different concrete index"),
        hit("idx-a", "same", 2, "better exact match", source_sha256="B" * 64),
        hit("idx-a", "other", 3, "other document"),
    ])
    bundle = make_bundle(response)
    assert [(entry["index"], entry["document_id"]) for entry in bundle["entries"]] == [
        ("idx-a", "same"), ("idx-b", "same"), ("idx-a", "other"),
    ]
    assert bundle["entries"][0]["rank"] == 2
    assert bundle["entries"][0]["snippet"] == "better exact match"
    assert bundle["entries"][0]["provenance"]["result_position"] == 3
    assert bundle["entries"][0]["provenance"]["source_sha256"] == "b" * 64
    assert bundle["deduplicated_count"] == 1
    assert bundle["included_count"] == 3
    assert bundle["omitted_count"] == 0


def test_whole_entry_budget_boundary_and_entry_count_are_strict():
    response = result([hit("idx", "one", 1, "one"), hit("idx", "two", 2, "two"), hit("idx", "three", 3, "three")])
    # Each full serialized entry is counted as exactly one by this injected
    # deterministic caller counter, so only complete entries can be included.
    bundle = build_context_bundle(response, token_counter=lambda _: 2, counter_name="fixed-entry-count-v1",
                                 max_tokens=4, max_entries=3)
    assert bundle["included_count"] == 2
    assert bundle["omitted_count"] == 1
    assert bundle["token_counter"]["included_tokens"] == 4
    assert bundle["token_counter"]["budget_tokens"] == 4
    assert len(bundle["entries"]) == 2
    by_count = build_context_bundle(response, token_counter=lambda _: 1, counter_name="fixed-entry-count-v1",
                                    max_tokens=10, max_entries=2)
    assert by_count["included_count"] == 2 and by_count["omitted_count"] == 1


def test_required_counter_and_identity_fail_closed():
    with pytest.raises(ContextBundleError, match="token counter"):
        build_context_bundle(result([hit()]), token_counter=None, counter_name=None)
    with pytest.raises(ContextBundleError, match="counter_name"):
        build_context_bundle(result([hit()]), token_counter=count_whitespace, counter_name="")
    for malformed in (
        result([{"_id": "doc", "rank": 1, "snippet": "text"}]),
        result([{"_index": "idx", "rank": 1, "snippet": "text"}]),
        {"query": "q", "hits": [hit()]},
        {"query": "q", "profile_fingerprint": PROFILE, "hits": [hit()]},
    ):
        with pytest.raises(ContextBundleError):
            make_bundle(malformed)


def test_strict_bounds_snippet_and_counter_output_are_enforced():
    response = result([hit(snippet="x" * 601)])
    with pytest.raises(ContextBundleError, match="snippet"):
        make_bundle(response)
    for kwargs in ({"max_tokens": 0}, {"max_tokens": 32_001}, {"max_entries": 101},
                   {"max_entries": True}, {"max_snippet_chars": 601}):
        with pytest.raises(ContextBundleError):
            build_context_bundle(result([hit()]), token_counter=count_whitespace,
                                 counter_name="valid-counter", **kwargs)
    with pytest.raises(ContextBundleError, match="non-negative integer"):
        build_context_bundle(result([hit()]), token_counter=lambda _: -1, counter_name="negative-v1")
    with pytest.raises(ContextBundleError, match="counter failed"):
        build_context_bundle(result([hit()]), token_counter=lambda _: (_ for _ in ()).throw(RuntimeError()),
                             counter_name="raising-v1")


def test_fingerprint_is_stable_and_artifact_whitelists_privacy_safe_fields():
    response = result([
        hit("idx", "doc", snippet="Authorization: Bearer ABCDEFGHIJKLMNOP secret=superSecret /home/person/private.txt"),
        hit("idx", "second", snippet="safe", source={"body": "FULL-SOURCE-MUST-NOT-APPEAR"},
            authorization="ApiKey DO-NOT-SERIALIZE", local_path="/home/secret/db.sqlite"),
    ], credentials={"password": "DO-NOT-SERIALIZE"}, headers={"Authorization": "Bearer header-secret"})
    first = make_bundle(response)
    second = make_bundle(response)
    encoded = json.dumps(first, ensure_ascii=False)
    assert first["content_fingerprint"] == second["content_fingerprint"]
    assert "FULL-SOURCE-MUST-NOT-APPEAR" not in encoded
    for secret in ("ABCDEFGHIJKLMN", "superSecret", "/home/person", "DO-NOT-SERIALIZE", "header-secret", "db.sqlite"):
        assert secret not in encoded
    assert "[REDACTED]" in encoded
    assert "[LOCAL_PATH]" in encoded
    assert all("source" not in entry for entry in first["entries"])


def test_sensitive_text_is_redacted_but_whitelisted_snippet_content_remains_inspectable():
    bundle = make_bundle(result([hit(snippet="Title: A useful record. password=hunter2 local /Users/alice/private.txt")]))
    snippet = bundle["entries"][0]["snippet"]
    assert "A useful record" in snippet
    assert "hunter2" not in snippet
    assert "/Users/alice" not in snippet


def test_example_uses_profile_runtime_and_environment_credentials_without_serializing_them(tmp_path, capsys, monkeypatch):
    example_path = Path(__file__).parents[1] / "examples" / "profile_context_handoff.py"
    assert "sys.path.insert" not in example_path.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("profile_context_handoff", example_path)
    example = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(example)
    profile_path = tmp_path / "profile.json"
    profile = {"format": "es-rag-profile-v1", "profile": {"format": "es-rag-profile-v1", "fingerprint": PROFILE}}
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(example_path), str(profile_path), "safe query"])
    monkeypatch.setenv("ES_URL", "http://localhost:9200")
    monkeypatch.setenv("ES_API_KEY", "runtime-secret-value")
    fake_result = result([hit(snippet="safe snippet password=snippet-password Authorization: ApiKey snippet-api-key-value")],
                         query="password=query-password api_key=query-api-key-value")
    with patch.object(example, "search_profile", return_value=fake_result) as search:
        assert example.main() == 0
    search.assert_called_once()
    assert search.call_args.args[0].api_key == "runtime-secret-value"
    assert search.call_args.args[1] == profile["profile"]
    assert search.call_args.args[2] == "safe query"
    output = capsys.readouterr().out
    assert "safe snippet" in output
    assert "runtime-secret-value" not in output
    for secret in ("snippet-password", "snippet-api-key-value", "query-password", "query-api-key-value"):
        assert secret not in output
    assert '"entries"' in output
    assert '"query": "[REDACTED] [REDACTED]"' in output
