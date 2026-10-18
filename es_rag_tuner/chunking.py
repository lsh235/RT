"""Deterministic bounded chunking for account-local source text.

Paragraph mode prefers the end of a paragraph (a run ending in a blank line)
within the size bound. A paragraph longer than the bound is split at the
largest legal source offset, so no source characters are dropped.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import token_preview

DEFAULT_POLICY = {"strategy": "character", "size": 1800, "overlap": 200}
MAX_SIZE = 100_000
# Match the document byte ceiling for ASCII source; knowledge.py independently
# enforces UTF-8 byte size so multibyte input cannot exceed the storage limit.
MAX_SOURCE_CHARS = 1024 * 1024
MAX_CHUNKS = 10_000


def normalize_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("policy must be an object")
    strategy = value.get("strategy", "character")
    size = value.get("size", 1800)
    overlap = value.get("overlap", 200)
    if not isinstance(strategy, str) or strategy not in {"character", "paragraph", "token"}:
        raise ValueError("strategy must be character, paragraph, or token")
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_SIZE:
        raise ValueError(f"size must be an integer from 1 to {MAX_SIZE}")
    if isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0 or overlap >= size:
        raise ValueError("overlap must be an integer greater than or equal to zero and smaller than size")
    if strategy == "token" and size > token_preview.MAX_TOKENS:
        raise ValueError(f"token size must not exceed the pinned model context of {token_preview.MAX_TOKENS}")
    return {"strategy": strategy, "size": size, "overlap": overlap}


def policy_fingerprint(policy: Any) -> str:
    normalized = normalize_policy(policy)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def tokenizer_info() -> dict[str, Any]:
    """Return pinned tokenizer identity and local readiness without downloading."""
    current = token_preview.status()
    return {
        "available": bool(current.get("available")),
        "model": token_preview.MODEL,
        "repository": token_preview.REPOSITORY,
        "revision": token_preview.REVISION,
        "context_tokens": token_preview.MAX_TOKENS,
        "reason": (
            "Pinned tokenizer assets are unavailable. Prepare the tokenizer explicitly before token chunking."
            if not current.get("available") else None
        ),
    }


def _tokenizer(tokenizer: Any) -> tuple[Any, bool]:
    if tokenizer is not None:
        return tokenizer, True
    try:
        if not tokenizer_info()["available"]:
            return None, False
        encoder = token_preview._TokenizerAdapter(token_preview._load_tokenizer())
    except Exception:
        # Exact token counts are optional for character/paragraph mode. A
        # stale, unreadable, or incomplete local cache must not block saves.
        return None, False
    return encoder, True


def _encode(tokenizer: Any, text: str) -> Any:
    # The pinned adapter provides full, untruncated counts and source offsets.
    try:
        return tokenizer.encode(text, truncation=False, max_length=None)
    except TypeError:
        return tokenizer.encode(text)


def _exact_count(tokenizer: Any, text: str) -> int:
    return len(_encode(tokenizer, text).ids)


def _paragraph_boundaries(text: str) -> list[int]:
    import re
    return sorted({match.end() for match in re.finditer(r"(?:\r?\n)[ \t]*(?:\r?\n)+", text) if match.end() > 0} | {len(text)})


def _ranges(text: str, size: int, overlap: int, strategy: str) -> list[tuple[int, int]]:
    if not text:
        return []
    boundaries = _paragraph_boundaries(text) if strategy == "paragraph" else []
    result: list[tuple[int, int]] = []
    start = 0
    previous_end = 0
    while start < len(text):
        limit = min(len(text), start + size)
        # A paragraph endpoint consumed by the previous chunk cannot be chosen
        # again while the next chunk starts in its overlap suffix.
        end = max((point for point in boundaries if previous_end < point <= limit), default=limit)
        if end <= start:
            end = limit
        result.append((start, end))
        if len(result) > MAX_CHUNKS:
            raise ValueError("source produces too many chunks")
        if end == len(text):
            break
        previous_end = end
        start = end - overlap
    return result


def _token_ranges(text: str, size: int, overlap: int, tokenizer: Any) -> list[tuple[int, int, int]]:
    if not text:
        return []
    enc = _encode(tokenizer, text)
    offsets = [tuple(map(int, pair)) for pair in enc.offsets if tuple(pair) != (0, 0)]
    if not offsets:
        raise ValueError("tokenizer returned no source offsets")
    spans: list[tuple[int, int, int]] = []
    index = 0
    source_start = 0
    while index < len(offsets):
        # Include the tokenizer's special tokens in the bound, then count each
        # exact source slice again because boundaries can alter tokenization.
        end_index = min(len(offsets), index + size)
        end = offsets[end_index - 1][1]
        start = source_start
        while end > start and _exact_count(tokenizer, text[start:end]) > size:
            end_index -= 1
            if end_index <= index:
                raise ValueError("size is too small for this tokenizer's special tokens")
            end = offsets[end_index - 1][1]
        count = _exact_count(tokenizer, text[start:end])
        spans.append((start, end, count))
        if len(spans) > MAX_CHUNKS:
            raise ValueError("source produces too many chunks")
        if end >= len(text):
            break
        # Start at the first of the requested overlapping token offsets.
        next_index = max(index + 1, end_index - overlap)
        next_start = min(end, offsets[next_index][0]) if next_index < len(offsets) else end
        if next_start <= start:
            raise ValueError("tokenizer offsets do not advance")
        source_start = next_start
        index = next_index
    # Extend the last slice over trailing whitespace/source not covered by token offsets.
    if spans[-1][1] < len(text):
        start, _, _ = spans[-1]
        spans[-1] = (start, len(text), _exact_count(tokenizer, text[start:]))
        if spans[-1][2] > size:
            raise ValueError("trailing source text exceeds token size bound")
    return spans


def split_text(text: str, policy: Any, *, tokenizer: Any = None) -> list[dict[str, Any]]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if len(text) > MAX_SOURCE_CHARS:
        raise ValueError(f"text exceeds {MAX_SOURCE_CHARS} codepoints")
    if not text.strip():
        raise ValueError("text must not be empty or whitespace-only")
    normalized = normalize_policy(policy)
    if normalized["strategy"] == "token":
        encoder, ready = _tokenizer(tokenizer)
        if not ready or encoder is None:
            raise RuntimeError(
                "pinned tokenizer unavailable: verify or explicitly prepare the pinned tokenizer assets before token chunking"
            )
        ranges_with_counts = _token_ranges(text, normalized["size"], normalized["overlap"], encoder)
        return [
            {"ordinal": i, "start_offset": start, "end_offset": end,
             "content": text[start:end], "token_count": count}
            for i, (start, end, count) in enumerate(ranges_with_counts)
        ]
    encoder, ready = _tokenizer(tokenizer)
    ranges = _ranges(text, normalized["size"], normalized["overlap"], normalized["strategy"])
    output = []
    for i, (start, end) in enumerate(ranges):
        count = _exact_count(encoder, text[start:end]) if ready and encoder is not None else None
        output.append({"ordinal": i, "start_offset": start, "end_offset": end,
                       "content": text[start:end], "token_count": count})
    return output
