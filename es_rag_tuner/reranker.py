"""Explicitly prepared, local-only cross-encoder reranking."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import math
import threading
import time
from typing import Any

from .es_client import ElasticsearchError


MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
MAX_LENGTH = 512
_lock = threading.Lock()
_model: Any = None


def _runtime_version() -> str | None:
    try:
        return importlib.metadata.version("sentence-transformers")
    except importlib.metadata.PackageNotFoundError:
        return None


def _snapshot(*, local_files_only: bool) -> str | None:
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(repo_id=MODEL, revision=REVISION, local_files_only=local_files_only)
    except Exception:
        return None


def _load(*, local_files_only: bool) -> Any:
    global _model
    with _lock:
        if _model is not None:
            return _model
        if importlib.util.find_spec("sentence_transformers") is None:
            raise ElasticsearchError("Reranker runtime is missing. Install the optional reranker extra.", 503)
        if local_files_only and _snapshot(local_files_only=True) is None:
            raise ElasticsearchError("The pinned reranker model is not cached. Use POST /api/reranker/prepare with consent true.", 503)
        try:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(
                MODEL,
                revision=REVISION,
                device="cpu",
                max_length=MAX_LENGTH,
                local_files_only=local_files_only,
                trust_remote_code=False,
            )
        except Exception:
            raise ElasticsearchError("The pinned reranker could not be loaded. Check the optional runtime and model cache.", 503) from None
        return _model


def status() -> dict[str, Any]:
    runtime = _runtime_version()
    cached = _snapshot(local_files_only=True) is not None if runtime else False
    return {
        "model": MODEL,
        "revision": REVISION,
        "runtime": {"installed": runtime is not None, "version": runtime},
        "cache": {"ready": cached},
        "ready": runtime is not None and cached,
        "loaded": _model is not None,
        "device": "cpu",
        "max_length": MAX_LENGTH,
        "activation": "identity",
        "score_interpretation": "uncalibrated raw model score, not a probability",
    }


def prepare(consent: Any) -> dict[str, Any]:
    if consent is not True:
        raise ElasticsearchError("Explicit consent=true is required before downloading the reranker model.")
    if importlib.util.find_spec("sentence_transformers") is None:
        raise ElasticsearchError("Reranker runtime is missing. Install the optional reranker extra.", 503)
    if _snapshot(local_files_only=True) is None:
        if _snapshot(local_files_only=False) is None:
            raise ElasticsearchError("The pinned reranker download failed. Check network access and retry preparation.", 503) from None
    model = _load(local_files_only=True)
    del model
    return status()


def rerank(query: str, hits: list[dict[str, Any]], size: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not hits:
        return [], {
            "model": MODEL, "revision": REVISION, "runtime": _runtime_version(),
            "max_length": MAX_LENGTH, "activation": "identity", "truncated": False,
            "elapsed_ms": 0, "candidate_count": 0,
            "score_interpretation": "uncalibrated raw model score, not a probability",
        }
    model = _load(local_files_only=True)
    pairs: list[tuple[str, str]] = []
    truncated: list[bool] = []
    tokenizer = model.tokenizer
    try:
        for hit in hits:
            source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
            text = "\n".join(str(source.get(key, "")) for key in (
                "issue_key", "summary", "error_signature", "root_cause", "workaround_or_fix",
                "description", "steps_to_reproduce", "rag_chunk_text",
            ) if source.get(key) is not None)
            if not text:
                text = str(hit.get("_id", ""))
            pairs.append((query, text))
            encoded = tokenizer(query, text, truncation=False, add_special_tokens=True)
            ids = encoded.get("input_ids", [])
            if ids and isinstance(ids[0], list):
                ids = ids[0]
            truncated.append(len(ids) > MAX_LENGTH)
    except Exception:
        raise ElasticsearchError("The local reranker could not prepare candidate text. Check the cached tokenizer.", 503) from None
    started = time.perf_counter()
    try:
        import torch
        scores = model.predict(
            pairs,
            batch_size=16,
            show_progress_bar=False,
            activation_fn=torch.nn.Identity(),
            apply_softmax=False,
        )
        values = [float(value) for value in scores]
        if len(values) != len(hits) or not all(math.isfinite(value) for value in values):
            raise ValueError("invalid model score output")
    except Exception:
        raise ElasticsearchError("The local reranker inference failed. Check the model cache and runtime.", 503) from None
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    ranked = []
    for original_rank, (hit, score, was_truncated) in enumerate(zip(hits, values, truncated), start=1):
        hit["reranker"] = {"before_rank": original_rank, "score": score, "truncated": was_truncated}
        ranked.append((original_rank, hit))
    ranked.sort(key=lambda item: (-item[1]["reranker"]["score"], item[0]))
    for after_rank, (_, hit) in enumerate(ranked, start=1):
        hit["reranker"]["after_rank"] = after_rank
    return [hit for _, hit in ranked[:size]], {
        "model": MODEL,
        "revision": REVISION,
        "runtime": _runtime_version(),
        "device": "cpu",
        "max_length": MAX_LENGTH,
        "activation": "identity",
        "truncated": any(truncated),
        "elapsed_ms": elapsed_ms,
        "candidate_count": len(hits),
        "score_interpretation": "uncalibrated raw model score, not a probability",
    }
