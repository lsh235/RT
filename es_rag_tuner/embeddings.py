"""Local embedding support for Elasticsearch dense_vector fields."""

from __future__ import annotations

import importlib.util
import math
import os
import threading
from pathlib import Path
from typing import Any

from .es_client import ElasticsearchError


MODEL_NAME = "intfloat/multilingual-e5-large"
MODEL_DIMENSIONS = 1024
_MODEL: Any = None
_MODEL_LOCK = threading.Lock()


def cache_path() -> Path:
    configured = os.environ.get("ES_RAG_MODEL_CACHE", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".cache" / "es-rag-workbench" / "fastembed"


def runtime_status() -> dict[str, Any]:
    installed = importlib.util.find_spec("fastembed") is not None
    root = cache_path()
    cached = False
    if root.exists():
        try:
            cached = next(root.rglob("model.onnx"), None) is not None
        except OSError:
            cached = False
    return {
        "runtime_installed": installed,
        "model_name": MODEL_NAME,
        "dimensions": MODEL_DIMENSIONS,
        "model_cached": cached,
        "cache_path": str(root),
        "install_command": ".venv/bin/python -m pip install -e '.[semantic]'",
    }


def _model(*, local_files_only: bool = False) -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    if importlib.util.find_spec("fastembed") is None:
        raise ElasticsearchError(
            "FastEmbed 임베딩 런타임이 없습니다. 프로젝트 가상환경에서 "
            "`.venv/bin/python -m pip install -e '.[semantic]'`를 실행하세요."
        )
    with _MODEL_LOCK:
        if _MODEL is None:
            try:
                from fastembed import TextEmbedding

                root = cache_path()
                root.mkdir(parents=True, exist_ok=True)
                _MODEL = TextEmbedding(
                    model_name=MODEL_NAME,
                    cache_dir=str(root),
                    threads=max(1, min(4, os.cpu_count() or 1)),
                    local_files_only=local_files_only,
                )
            except Exception as exc:
                raise ElasticsearchError(f"임베딩 모델을 불러오지 못했습니다: {exc}") from None
    return _MODEL


def _normalize(vector: Any) -> list[float]:
    values = vector.tolist() if hasattr(vector, "tolist") else list(vector)
    values = [float(value) for value in values]
    if len(values) != MODEL_DIMENSIONS:
        raise ElasticsearchError(
            f"임베딩 차원이 {len(values)}입니다. 매핑과 모델은 {MODEL_DIMENSIONS}차원이어야 합니다."
        )
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ElasticsearchError("임베딩 모델이 영벡터를 반환했습니다.")
    return [value / norm for value in values]


def embed_texts(texts: list[str], role: str, *, local_files_only: bool = False) -> list[list[float]]:
    if role not in {"query", "passage"}:
        raise ValueError("role must be 'query' or 'passage'")
    if not texts:
        return []
    model = _model(local_files_only=local_files_only)
    inputs = [format_embedding_input(text, role) for text in texts]
    try:
        return [_normalize(vector) for vector in model.embed(inputs, batch_size=32)]
    except ElasticsearchError:
        raise
    except Exception as exc:
        raise ElasticsearchError(f"텍스트 임베딩 생성에 실패했습니다: {exc}") from None


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


def format_embedding_input(text: str, role: str) -> str:
    """Format text exactly as sent to the E5 embedder for the given role."""
    if role not in {"query", "passage"}:
        raise ValueError("role must be 'query' or 'passage'")
    return f"{role}: {text.strip()}"


def passage_input(source: dict[str, Any]) -> dict[str, str]:
    """Describe the exact passage input and source, without loading the model."""
    text = document_text(source).strip()
    if not text:
        return {"text": "", "source": "empty"}
    origin = "rag_chunk_text" if str(source.get("rag_chunk_text", "")).strip() else "structured_fields"
    return {"text": format_embedding_input(text, "passage"), "source": origin}
