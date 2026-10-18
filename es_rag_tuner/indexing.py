"""Create missing document embeddings in place without replacing source fields."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from . import embeddings
from .es_client import Connection, ElasticsearchError, count_documents, index_scroll_scope, request, validate_index
from .retrieval import count_vectors, profile_fingerprint, vector_mapping


SOURCE_FIELDS = [
    "rag_chunk_text", "summary", "error_signature", "description",
    "steps_to_reproduce", "root_cause", "workaround_or_fix", "comments",
]


def _missing_count(connection: Connection, index: str) -> int:
    body = {"query": {"bool": {"must_not": [{"exists": {"field": "rag_embedding"}}]}}}
    result = request(connection, "POST", f"{quote(index, safe='')}/_count", body)
    return int(result.get("count", 0))


def _index_batch(connection: Connection, index: str, hits: list[dict[str, Any]], vectors: list[list[float]]) -> None:
    lines: list[str] = []
    for hit, vector in zip(hits, vectors):
        lines.append(json.dumps({"update": {"_index": index, "_id": hit["_id"]}}, separators=(",", ":")))
        lines.append(json.dumps({"doc": {"rag_embedding": vector}}, separators=(",", ":")))
    response = request(
        connection,
        "POST",
        "_bulk?refresh=false",
        "\n".join(lines) + "\n",
        content_type="application/x-ndjson",
        timeout=120,
    )
    if response.get("errors"):
        failed = []
        for item in response.get("items", []):
            result = next(iter(item.values()), {})
            if int(result.get("status", 200)) >= 300:
                failed.append({"id": result.get("_id"), "status": result.get("status"), "error": result.get("error")})
            if len(failed) >= 5:
                break
        raise ElasticsearchError(f"임베딩 bulk 업데이트 중 일부 실패: {json.dumps(failed, ensure_ascii=False)}", safe_for_user=False)


def _record_profile_recipe(connection: Connection, index: str, recipe: dict[str, Any]) -> None:
    """Record vector provenance in mapping metadata while preserving other keys."""
    mapping = request(connection, "GET", f"{quote(index, safe='')}/_mapping")
    fingerprint = profile_fingerprint(recipe)
    for concrete_index, item in mapping.items():
        mappings = item.get("mappings", {}) if isinstance(item, dict) else {}
        old_meta = mappings.get("_meta", {}) if isinstance(mappings, dict) else {}
        meta = dict(old_meta) if isinstance(old_meta, dict) else {}
        meta.update({"embedding_profile_recipe": recipe, "embedding_profile_sha256": fingerprint})
        request(connection, "PUT", f"{quote(concrete_index, safe='')}/_mapping", {"_meta": meta})


def vectorize_index(connection: Connection, index: str, profile_id: str | None = None) -> dict[str, Any]:
    spec = embeddings.profile_spec(profile_id)
    recipe = embeddings.profile_recipe(profile_id)
    index = validate_index(index)
    before = count_vectors(connection, index)
    vector_mapping(connection, index, profile_id=profile_id,
                   allow_untagged_empty_profile=before == 0)
    pending = _missing_count(connection, index)
    if pending == 0:
        return {
            "index": index,
            "document_count": before,
            "vectors_added": 0,
            "vector_count": before,
            "model_name": spec["model_name"],
            "profile_id": spec["profile_id"],
            "recipe": recipe,
            "dimensions": spec["dimensions"],
            "message": "새로 생성할 임베딩이 없습니다. 기존 임베딩은 유지했습니다.",
        }

    # Load the model before opening the scroll context so a first-time model
    # download cannot consume the Elasticsearch scroll keepalive.
    embeddings._model(profile_id or embeddings.DEFAULT_PROFILE_ID)
    # Loading can resolve the previously unknown immutable snapshot revision.
    # Record and return this resolved recipe so the next search fingerprint
    # matches the index metadata exactly.
    recipe = embeddings.profile_recipe(profile_id)
    # Existing tagged vectors were validated above. For an untagged legacy E5
    # index this transition is allowed only through the explicit E5 fallback;
    # record that resolved recipe before adding more vectors.
    _record_profile_recipe(connection, index, recipe)
    query = {
        "size": 1000,
        "track_total_hits": True,
        "_source": SOURCE_FIELDS,
        "query": {"bool": {"must_not": [{"exists": {"field": "rag_embedding"}}]}},
    }
    response = request(connection, "POST", f"{quote(index, safe='')}/_search?scroll=2m", query, timeout=120)
    added = 0
    skipped_empty = 0
    scroll_id = response.get("_scroll_id")
    try:
        while True:
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break
            texts = [embeddings.document_text(hit.get("_source", {})) for hit in hits]
            valid = [(hit, text) for hit, text in zip(hits, texts) if text.strip()]
            skipped_empty += len(hits) - len(valid)
            for start in range(0, len(valid), 32):
                batch = valid[start:start + 32]
                vectors = embeddings.embed_texts([item[1] for item in batch], "passage", profile_id=profile_id)
                _index_batch(connection, index, [item[0] for item in batch], vectors)
                added += len(batch)
            if not scroll_id:
                break
            with index_scroll_scope(index):
                response = request(
                    connection,
                    "POST",
                    "_search/scroll",
                    {"scroll": "2m", "scroll_id": scroll_id},
                    timeout=120,
                )
            scroll_id = response.get("_scroll_id", scroll_id)
    finally:
        if scroll_id:
            try:
                with index_scroll_scope(index):
                    request(connection, "DELETE", "_search/scroll", {"scroll_id": [scroll_id]}, timeout=30)
            except ElasticsearchError:
                pass

    if added == 0:
        raise ElasticsearchError("rag_chunk_text 또는 대체 텍스트 필드가 비어 있어 임베딩을 만들 수 없습니다.")

    request(connection, "POST", f"{quote(index, safe='')}/_refresh")
    after = count_vectors(connection, index)
    return {
        "index": index,
        "document_count": count_documents(connection, index),
        "vectors_added": added,
        "vectors_skipped_empty": skipped_empty,
        "vector_count": after,
        "model_name": spec["model_name"],
        "profile_id": spec["profile_id"],
        "recipe": recipe,
        "dimensions": spec["dimensions"],
        "message": f"{added}개 문서에 {spec['model_name']} 임베딩을 추가했습니다.",
    }
