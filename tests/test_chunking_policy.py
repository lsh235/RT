from __future__ import annotations

from types import SimpleNamespace

import pytest

from es_rag_tuner import chunking, token_preview


class CodepointTokenizer:
    """Test-only deterministic tokenizer: one fake token per Python codepoint."""
    def encode(self, text, *, truncation=False, max_length=None):
        offsets = [(i, i + 1) for i in range(len(text))]
        ids = list(range(len(text)))
        if truncation and max_length is not None:
            offsets, ids = offsets[:max_length], ids[:max_length]
        return SimpleNamespace(ids=ids, offsets=offsets)


@pytest.mark.parametrize("strategy", ["character", "paragraph"])
def test_character_and_paragraph_chunks_have_exact_source_offsets(strategy):
    source = "α😀 first paragraph\n\nsecond paragraph\nthird"
    policy = {"strategy": strategy, "size": 14, "overlap": 3}
    chunks = chunking.split_text(source, policy, tokenizer=CodepointTokenizer())
    assert chunks
    assert chunks[0]["start_offset"] == 0
    assert chunks[-1]["end_offset"] == len(source)
    for ordinal, chunk in enumerate(chunks):
        assert chunk["ordinal"] == ordinal
        assert chunk["content"] == source[chunk["start_offset"]:chunk["end_offset"]]
        assert len(chunk["content"]) <= policy["size"]
        assert chunk["token_count"] == len(chunk["content"])
    for left, right in zip(chunks, chunks[1:]):
        assert right["start_offset"] == left["end_offset"] - policy["overlap"]


def test_paragraph_mode_packs_boundaries_and_splits_oversized_paragraph_deterministically():
    source = "short\n\n" + "x" * 17 + "\n\nend"
    policy = {"strategy": "paragraph", "size": 8, "overlap": 2}
    chunks = chunking.split_text(source, policy, tokenizer=CodepointTokenizer())
    assert [chunk["start_offset"] for chunk in chunks] == [0, 5, 11, 17, 23]
    assert chunks[0]["end_offset"] == 7  # paragraph boundary is preferred within the first bound
    assert all(source[c["start_offset"]:c["end_offset"]] == c["content"] for c in chunks)
    assert "".join(c["content"] if i == 0 else c["content"][2:] for i, c in enumerate(chunks)) == source


@pytest.mark.parametrize("policy", [
    None, [], {"strategy": "word"}, {"size": True}, {"size": 0},
    {"size": 1, "overlap": 1}, {"size": 4, "overlap": -1},
    {"size": 4, "overlap": 1.2},
])
def test_invalid_policy_rejected(policy):
    with pytest.raises(ValueError):
        chunking.normalize_policy(policy)


def test_empty_source_and_non_string_are_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        chunking.split_text("", {"strategy": "character", "size": 4, "overlap": 0})
    with pytest.raises(TypeError):
        chunking.split_text(None, {"strategy": "character", "size": 4, "overlap": 0})


def test_oversized_source_and_token_policy_beyond_model_context_are_rejected():
    with pytest.raises(ValueError, match="exceeds"):
        chunking.split_text("x" * (chunking.MAX_SOURCE_CHARS + 1), {"strategy": "character", "size": 4, "overlap": 0})
    with pytest.raises(ValueError, match="model context"):
        chunking.normalize_policy({"strategy": "token", "size": token_preview.MAX_TOKENS + 1, "overlap": 0})


def test_ascii_source_at_document_byte_ceiling_is_accepted():
    source = "x" * chunking.MAX_SOURCE_CHARS
    chunks = chunking.split_text(source, {"strategy": "character", "size": chunking.MAX_SIZE, "overlap": 0})
    assert len(chunks) == (len(source) + chunking.MAX_SIZE - 1) // chunking.MAX_SIZE
    assert chunks[0]["start_offset"] == 0
    assert chunks[-1]["end_offset"] == len(source)
    assert all(source[c["start_offset"]:c["end_offset"]] == c["content"] for c in chunks)


def test_policy_fingerprint_and_chunks_are_deterministic():
    first = {"strategy": "character", "size": 7, "overlap": 2}
    reordered = {"overlap": 2, "size": 7, "strategy": "character"}
    assert chunking.policy_fingerprint(first) == chunking.policy_fingerprint(reordered)
    assert chunking.policy_fingerprint(first) != chunking.policy_fingerprint({**first, "size": 8})
    assert chunking.split_text("abcdefghij", first, tokenizer=CodepointTokenizer()) == chunking.split_text("abcdefghij", reordered, tokenizer=CodepointTokenizer())


def test_non_token_count_is_null_when_pinned_tokenizer_is_unavailable(monkeypatch):
    monkeypatch.setattr(token_preview, "status", lambda: {"available": False, "reason": "cache absent"})
    chunks = chunking.split_text("abcdef", {"strategy": "character", "size": 4, "overlap": 1})
    assert all(chunk["token_count"] is None for chunk in chunks)
    assert chunking.tokenizer_info()["available"] is False
    assert chunking.tokenizer_info()["model"] == token_preview.MODEL
    assert chunking.tokenizer_info()["revision"] == token_preview.REVISION


def test_token_strategy_fails_closed_without_pinned_tokenizer(monkeypatch):
    monkeypatch.setattr(token_preview, "status", lambda: {"available": False, "reason": "cache absent"})
    with pytest.raises(RuntimeError, match="pinned tokenizer unavailable"):
        chunking.split_text("some text", {"strategy": "token", "size": 8, "overlap": 1})


def test_optional_tokenizer_load_failure_keeps_non_token_chunking_available(monkeypatch):
    monkeypatch.setattr(token_preview, "status", lambda: {"available": True})
    monkeypatch.setattr(token_preview, "_load_tokenizer", lambda: (_ for _ in ()).throw(ValueError("bad cache")))
    for strategy in ("character", "paragraph"):
        chunks = chunking.split_text("abc\n\ndef", {"strategy": strategy, "size": 5, "overlap": 1})
        assert chunks
        assert all(chunk["token_count"] is None for chunk in chunks)


def test_token_strategy_fails_closed_when_available_tokenizer_cannot_load(monkeypatch):
    monkeypatch.setattr(token_preview, "status", lambda: {"available": True})
    monkeypatch.setattr(token_preview, "_load_tokenizer", lambda: (_ for _ in ()).throw(ValueError("bad cache")))
    with pytest.raises(RuntimeError, match="pinned tokenizer unavailable"):
        chunking.split_text("some text", {"strategy": "token", "size": 8, "overlap": 1})


def test_token_strategy_with_test_injection_has_exact_ranges_and_counts():
    source = "abcdefghij"
    policy = {"strategy": "token", "size": 4, "overlap": 1}
    chunks = chunking.split_text(source, policy, tokenizer=CodepointTokenizer())
    assert [c["content"] for c in chunks] == ["abcd", "defg", "ghij"]
    assert [c["token_count"] for c in chunks] == [4, 4, 4]
    assert all(source[c["start_offset"]:c["end_offset"]] == c["content"] for c in chunks)
