"""Explicit, bounded retrieval-context bundles for external profile consumers."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable


class ContextBundleError(ValueError):
    """Raised when input identity, token counting, or bounds are unsafe."""


_MAX_RESULTS = 1000
_MAX_ENTRIES = 100
_MAX_TOKENS = 32_000
_MAX_SNIPPET_CHARS = 600

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*[:=]\s*(?:bearer|basic)\s+[^\s,;]+"),
    re.compile(r"(?i)\bauthorization\s*[:=]\s*(?:apikey|api[- ]?key)\s+[^\s,;]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|secret)\s*[:=]\s*[^\s,;]+"),
)
_LOCAL_PATH = re.compile(r"(?i)(?:/(?:home|users|private|tmp|root|var|opt|etc|mnt|workspace|workspaces|srv)/[^\s,;\"']+|[A-Z]:\\Users\\[^\s,;\"']+)")
_URL_CREDENTIAL = re.compile(r"(?i)(https?://)[^/@\s]+@")
_URL_QUERY_OR_FRAGMENT = re.compile(r"(?i)https?://[^\s?#]+[?#][^\s]+")


def _safe_text(value: str) -> str:
    text = value
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = _URL_CREDENTIAL.sub(r"\1[REDACTED]@", text)
    text = _URL_QUERY_OR_FRAGMENT.sub("[REDACTED_URL]", text)
    return _LOCAL_PATH.sub("[LOCAL_PATH]", text)


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_context_bundle(
    search_result: dict[str, Any],
    *,
    token_counter: Callable[[str], int] | None,
    counter_name: str | None,
    max_tokens: int = 4096,
    max_entries: int = 20,
    max_snippet_chars: int = 600,
) -> dict[str, Any]:
    """Build a local handoff artifact from bounded ``search_profile`` hits only.

    The injected counter receives the canonical JSON text of each complete
    context entry. Entries are added whole and in first-seen result order.
    Exact ``(index, document_id)`` duplicates keep the earliest output slot;
    if a duplicate has a better (lower) rank, its snippet and provenance win.
    """
    if not callable(token_counter) or not isinstance(counter_name, str) or not counter_name.strip() or len(counter_name.strip()) > 128:
        raise ContextBundleError("A callable token counter and non-empty counter_name are required.")
    if _safe_text(counter_name.strip()) != counter_name.strip():
        raise ContextBundleError("counter_name must not contain credentials or local paths.")
    bounds = (("max_tokens", max_tokens, 1, _MAX_TOKENS),
              ("max_entries", max_entries, 1, _MAX_ENTRIES),
              ("max_snippet_chars", max_snippet_chars, 1, _MAX_SNIPPET_CHARS))
    for name, value, low, high in bounds:
        if isinstance(value, bool) or not isinstance(value, int) or value < low or value > high:
            raise ContextBundleError(f"{name} must be an integer between {low} and {high}.")
    if not isinstance(search_result, dict):
        raise ContextBundleError("search_result must be an object returned by search_profile.")
    query = search_result.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ContextBundleError("search result query identity is required.")
    result_index = search_result.get("index")
    if not isinstance(result_index, str) or not result_index.strip() or len(result_index) > 255:
        raise ContextBundleError("search result index identity is required.")
    profile_fingerprint = search_result.get("profile_fingerprint")
    if not isinstance(profile_fingerprint, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", profile_fingerprint):
        raise ContextBundleError("search result profile_fingerprint identity is required.")
    hits = search_result.get("hits")
    if not isinstance(hits, list) or len(hits) > _MAX_RESULTS:
        raise ContextBundleError(f"search result hits must be a list with at most {_MAX_RESULTS} entries.")

    # Whitelist data from search hits. Never pass through source, connection,
    # headers, or arbitrary nested metadata from the caller's object.
    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for position, hit in enumerate(hits, 1):
        if not isinstance(hit, dict):
            raise ContextBundleError(f"hit {position} must be an object.")
        index, document_id = hit.get("_index"), hit.get("_id")
        if not isinstance(index, str) or not index.strip() or not isinstance(document_id, str) or not document_id.strip():
            raise ContextBundleError(f"hit {position} is missing exact (index, document_id) identity.")
        if len(index) > 255 or len(document_id) > 512:
            raise ContextBundleError(f"hit {position} identity exceeds the supported size bound.")
        if _safe_text(index) != index or _safe_text(document_id) != document_id:
            raise ContextBundleError(f"hit {position} identity contains sensitive path or credential material.")
        rank = hit.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ContextBundleError(f"hit {position} is missing a positive integer rank.")
        snippet = hit.get("snippet")
        if not isinstance(snippet, str) or len(snippet) > max_snippet_chars:
            raise ContextBundleError(f"hit {position} snippet is missing or exceeds max_snippet_chars.")
        identity = (index, document_id)
        provenance = {
            "query": _safe_text(query.strip()),
            "profile_fingerprint": profile_fingerprint,
            "rank": rank,
            "result_position": position,
        }
        source_sha256 = hit.get("source_sha256")
        if isinstance(source_sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", source_sha256):
            provenance["source_sha256"] = source_sha256.lower()
        entry = {
            "index": index,
            "document_id": document_id,
            "rank": rank,
            "snippet": _safe_text(snippet),
            "provenance": provenance,
        }
        prior = deduplicated.get(identity)
        if prior is None:
            deduplicated[identity] = entry
            order.append(identity)
        elif rank < prior["rank"]:
            deduplicated[identity] = entry

    included: list[dict[str, Any]] = []
    token_total = 0
    omitted_count = 0
    for identity in order:
        entry = deduplicated[identity]
        if len(included) >= max_entries:
            omitted_count += 1
            continue
        entry_text = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        try:
            count = token_counter(entry_text)
        except Exception as exc:
            raise ContextBundleError("token counter failed; no bundle was produced.") from exc
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ContextBundleError("token counter must return a non-negative integer.")
        if token_total + count <= max_tokens:
            included.append(entry)
            token_total += count
        else:
            omitted_count += 1

    deduplicated_count = len(hits) - len(order)
    bundle: dict[str, Any] = {
        "format": "es-rag-context-bundle-v1",
        "index": _safe_text(result_index.strip()),
        "query": _safe_text(query.strip()),
        "profile_fingerprint": profile_fingerprint,
        "token_counter": {"name": counter_name.strip(), "included_tokens": token_total, "budget_tokens": max_tokens},
        "entries": included,
        "candidate_count": len(hits),
        "deduplicated_count": deduplicated_count,
        "included_count": len(included),
        "omitted_count": omitted_count,
        "limits": {"max_tokens": max_tokens, "max_entries": max_entries, "max_snippet_chars": max_snippet_chars},
        "limitations": [
            "This artifact contains selected search snippets and document identities only; it is not an answer or relevance judgment.",
            "Token counts use only the named caller-supplied counter and do not represent another model's tokenization.",
            "Review user queries, snippets, document IDs, and index names before sharing.",
            "Absent and explicitly unjudged documents remain unknown; they are not labeled irrelevant.",
        ],
    }
    bundle["content_fingerprint"] = _json_hash(bundle)
    return bundle
