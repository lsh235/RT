"""Local, reproducible embedding profiles for Elasticsearch dense vectors."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import hashlib
import json
import math
import os
import threading
from pathlib import Path
from typing import Any

from .es_client import ElasticsearchError


MODEL_NAME = "intfloat/multilingual-e5-large"
MODEL_DIMENSIONS = 1024
DEFAULT_PROFILE_ID = "e5-multilingual-large"
_PROFILES: dict[str, dict[str, Any]] = {
    DEFAULT_PROFILE_ID: {
        "profile_id": DEFAULT_PROFILE_ID,
        "model_name": MODEL_NAME,
        "source_repo": "Qdrant/multilingual-e5-large-onnx",
        "dimensions": MODEL_DIMENSIONS,
        "similarity": "cosine",
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "context_tokens": 512,
        "normalized": True,
        "license": "mit",
        "model_file": "model.onnx",
    },
    "paraphrase-multilingual-minilm-l12": {
        "profile_id": "paraphrase-multilingual-minilm-l12",
        "model_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "source_repo": "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q",
        "dimensions": 384,
        "similarity": "cosine",
        "query_prefix": "",
        "passage_prefix": "",
        "context_tokens": 128,
        "normalized": True,
        "license": "apache-2.0",
        "model_file": "model_optimized.onnx",
    },
}
_MODELS: dict[str, Any] = {}
_LOAD_ERRORS: dict[str, bool] = {}
_MODEL_LOCKS = {profile_id: threading.Lock() for profile_id in _PROFILES}


def _profile_id(profile_id: str | None = None) -> str:
    selected = DEFAULT_PROFILE_ID if profile_id is None else profile_id
    if not isinstance(selected, str) or selected not in _PROFILES:
        raise ValueError(f"Unknown embedding profile: {selected!r}")
    return selected


def _model_cache_root() -> Path:
    configured = os.environ.get("ES_RAG_MODEL_CACHE", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".cache" / "es-rag-workbench" / "fastembed"


def cache_path(profile_id: str | None = None) -> Path:
    """Return the FastEmbed cache root (kept common for legacy E5 cache compatibility)."""
    _profile_id(profile_id)
    return _model_cache_root()


def _fastembed_version() -> str | None:
    try:
        return importlib.metadata.version("fastembed")
    except importlib.metadata.PackageNotFoundError:
        return None


def _cached_artifact(profile_id: str) -> tuple[bool, str | None]:
    profile = _PROFILES[profile_id]
    root = _model_cache_root()
    model_cache = root / f"models--{profile['source_repo'].replace('/', '--')}"
    # FastEmbed's older ONNX models use `onnx_snapshots`; models published
    # through the Hugging Face cache can use the standard `snapshots` tree.
    for snapshot_tree in ("onnx_snapshots", "snapshots"):
        try:
            for snapshot in (model_cache / snapshot_tree).iterdir():
                artifact = snapshot / profile["model_file"]
                tokenizer = snapshot / "tokenizer.json"
                config = snapshot / "config.json"
                if not tokenizer.is_file():
                    # FastEmbed keeps some ONNX graphs in its own snapshot tree
                    # while the tokenizer/config stay in the standard HF tree.
                    tokenizer = model_cache / "snapshots" / snapshot.name / "tokenizer.json"
                    config = model_cache / "snapshots" / snapshot.name / "config.json"
                if snapshot.is_dir() and artifact.is_file() and tokenizer.is_file() and config.is_file():
                    return True, snapshot.name
        except OSError:
            continue
    return False, None


def cached_file_path(profile_id: str, filename: str) -> Path | None:
    """Resolve a file from the cached profile revision without exposing it to the API."""
    selected = _profile_id(profile_id)
    cached, revision = _cached_artifact(selected)
    if not cached or not revision:
        return None
    model_cache = _model_cache_root() / f"models--{_PROFILES[selected]['source_repo'].replace('/', '--')}"
    for snapshot_tree in ("onnx_snapshots", "snapshots"):
        candidate = model_cache / snapshot_tree / revision / filename
        if candidate.is_file():
            return candidate
    return None


def profile_spec(profile_id: str | None = None) -> dict[str, Any]:
    """Return immutable-by-copy model and input settings for a profile."""
    selected = _profile_id(profile_id)
    result = {key: value for key, value in _PROFILES[selected].items() if key != "model_file"}
    result["fastembed_version"] = _fastembed_version()
    return result


def profile_recipe(profile_id: str | None = None) -> dict[str, Any]:
    """Return the settings that identify vectors produced by this profile."""
    selected = _profile_id(profile_id)
    spec = profile_spec(selected)
    cached, revision = _cached_artifact(selected)
    recipe = {
        "profile_id": selected,
        "model_name": spec["model_name"],
        "fastembed_version": spec["fastembed_version"],
        "source_repo": spec["source_repo"],
        "source_revision": revision if cached else None,
        "license": spec["license"],
        "dimensions": spec["dimensions"],
        "similarity": spec["similarity"],
        "query_prefix": spec["query_prefix"],
        "passage_prefix": spec["passage_prefix"],
        "context_tokens": spec["context_tokens"],
        "normalized": spec["normalized"],
    }
    canonical_recipe = json.dumps(recipe, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    recipe["recipe_fingerprint"] = hashlib.sha256(canonical_recipe.encode("utf-8")).hexdigest()
    return recipe


def list_profiles() -> list[dict[str, Any]]:
    return [profile_spec(profile_id) for profile_id in _PROFILES]


def runtime_status(profile_id: str | None = None) -> dict[str, Any]:
    selected = _profile_id(profile_id)
    spec = profile_spec(selected)
    installed = importlib.util.find_spec("fastembed") is not None
    cached, revision = _cached_artifact(selected)
    if not installed:
        state = "dependency_missing"
    elif _LOAD_ERRORS.get(selected):
        state = "loading_failure"
    elif cached:
        state = "cached"
    else:
        state = "model_not_cached"
    return {
        "profile_id": selected,
        "status": state,
        "runtime_installed": installed,
        "model_name": spec["model_name"],
        "dimensions": spec["dimensions"],
        "model_cached": cached,
        "source_revision": revision,
        "license": spec["license"],
        "install_command": ".venv/bin/python -m pip install -e '.[semantic]'",
    }


def _model(profile_id: str, *, local_files_only: bool = False) -> Any:
    if not importlib.util.find_spec("fastembed"):
        _LOAD_ERRORS[profile_id] = False
        raise ElasticsearchError(
            "FastEmbed embedding runtime is not installed. Install the project semantic extra.",
            safe_for_user=False,
        )
    if profile_id in _MODELS:
        return _MODELS[profile_id]
    with _MODEL_LOCKS[profile_id]:
        if profile_id in _MODELS:
            return _MODELS[profile_id]
        try:
            from fastembed import TextEmbedding

            root = _model_cache_root()
            root.mkdir(parents=True, exist_ok=True)
            model = TextEmbedding(
                model_name=_PROFILES[profile_id]["model_name"],
                cache_dir=str(root),
                threads=max(1, min(4, os.cpu_count() or 1)),
                local_files_only=local_files_only,
            )
            _MODELS[profile_id] = model
            _LOAD_ERRORS.pop(profile_id, None)
            return model
        except Exception:
            _LOAD_ERRORS[profile_id] = True
            detail = "local model files are unavailable" if local_files_only else "model could not be loaded"
            raise ElasticsearchError(f"Embedding profile {profile_id!r} {detail}.", safe_for_user=False) from None


def _normalize(vector: Any, profile_id: str) -> list[float]:
    dimensions = _PROFILES[profile_id]["dimensions"]
    values = vector.tolist() if hasattr(vector, "tolist") else list(vector)
    values = [float(value) for value in values]
    if len(values) != dimensions:
        raise ElasticsearchError(f"Embedding dimension {len(values)} does not match profile {profile_id!r} ({dimensions}).")
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ElasticsearchError("Embedding model returned a zero vector.")
    return [value / norm for value in values]


def embed_texts(
    texts: list[str], role: str, *, local_files_only: bool = False, profile_id: str | None = None
) -> list[list[float]]:
    selected = _profile_id(profile_id)
    if role not in {"query", "passage"}:
        raise ValueError("role must be 'query' or 'passage'")
    if not texts:
        return []
    model = _model(selected, local_files_only=local_files_only)
    inputs = [format_embedding_input(text, role, selected) for text in texts]
    try:
        return [_normalize(vector, selected) for vector in model.embed(inputs, batch_size=32)]
    except ElasticsearchError:
        raise
    except Exception:
        raise ElasticsearchError("Text embedding generation failed.", safe_for_user=False) from None


def document_text(source: dict[str, Any]) -> str:
    """Prefer the supplied unified RAG chunk; fall back to structured Jira fields."""
    unified = str(source.get("rag_chunk_text", "")).strip()
    if unified:
        return unified
    parts = []
    for field, label in (
        ("summary", "Summary"),
        ("error_signature", "Error signature"),
        ("description", "Description"),
        ("steps_to_reproduce", "Steps to reproduce"),
        ("root_cause", "Root cause"),
        ("workaround_or_fix", "Workaround or fix"),
    ):
        value = source.get(field)
        if value:
            parts.append(f"{label}: {value}")
    comments = source.get("comments")
    if isinstance(comments, list):
        for comment in comments:
            if isinstance(comment, dict) and comment.get("body"):
                parts.append(f"Comment: {comment['body']}")
    return "\n\n".join(parts)


def format_embedding_input(text: str, role: str, profile_id: str | None = None) -> str:
    selected = _profile_id(profile_id)
    if role not in {"query", "passage"}:
        raise ValueError("role must be 'query' or 'passage'")
    prefix = _PROFILES[selected][f"{role}_prefix"]
    return f"{prefix}{text.strip()}"


def passage_input(source: dict[str, Any]) -> dict[str, str]:
    """Describe the exact default-profile passage input without loading the model."""
    text = document_text(source).strip()
    if not text:
        return {"text": "", "source": "empty"}
    origin = "rag_chunk_text" if str(source.get("rag_chunk_text", "")).strip() else "structured_fields"
    return {"text": format_embedding_input(text, "passage"), "source": origin}
