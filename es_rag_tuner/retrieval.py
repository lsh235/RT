"""BM25, dense-vector, and reciprocal-rank-fused search helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from . import embeddings
from .es_client import (
    Connection,
    ElasticsearchError,
    build_search_query,
    request,
    validate_index,
)


FILTER_FIELDS = {
    "issue_key", "issue_type", "status", "priority", "resolution", "components",
    "labels", "language", "affected_versions", "fix_versions", "project.key",
}


def vector_mapping_targets(
    connection: Connection,
    index: str,
    *,
    require_dimensions: bool = True,
) -> tuple[dict[str, Any], set[str]]:
    """Validate every concrete mapping behind an index name or alias.

    Returns one validated mapping for existing callers and the concrete target
    names used to validate hit identity. Similarity defaults to cosine for
    float vectors. Index options are compared as declared: omitted server
    defaults match other omitted defaults, while explicit options must agree.
    """
    index = validate_index(index)
    response = request(connection, "GET", f"{quote(index, safe='')}/_mapping")
    if not isinstance(response, dict) or not response:
        raise ElasticsearchError("선택한 인덱스 또는 alias의 구체 인덱스 매핑을 확인할 수 없습니다.")

    concrete: dict[str, dict[str, Any]] = {}
    for concrete_index, value in response.items():
        if not isinstance(concrete_index, str) or not isinstance(value, dict):
            raise ElasticsearchError("선택한 인덱스 또는 alias의 concrete 매핑 응답 형식이 올바르지 않습니다.")
        mappings = value.get("mappings")
        properties = mappings.get("properties") if isinstance(mappings, dict) else None
        mapping = properties.get("rag_embedding") if isinstance(properties, dict) else None
        if not isinstance(mapping, dict) or mapping.get("type") != "dense_vector":
            raise ElasticsearchError(
                f"{concrete_index}에는 dense_vector 형식의 rag_embedding 필드가 없습니다. "
                "alias의 모든 대상에 호환되는 벡터 매핑을 적용하세요."
            )

        dimensions = mapping.get("dims")
        if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions <= 0:
            raise ElasticsearchError(f"{concrete_index}의 rag_embedding dims 매핑이 올바르지 않습니다.")
        if require_dimensions and dimensions != embeddings.MODEL_DIMENSIONS:
            raise ElasticsearchError(
                f"{concrete_index}의 rag_embedding은 {dimensions}차원입니다. 현재 로컬 모델 "
                f"{embeddings.MODEL_NAME}은 {embeddings.MODEL_DIMENSIONS}차원이므로 차원을 맞추세요."
            )
        if mapping.get("index", True) is not True:
            raise ElasticsearchError(f"{concrete_index}의 rag_embedding은 index가 비활성화되어 있습니다. index:true로 설정하세요.")
        element_type = mapping.get("element_type", "float")
        if element_type != "float":
            raise ElasticsearchError(
                f"{concrete_index}의 rag_embedding element_type은 {element_type!r}입니다. "
                "현재 질의 임베딩은 float이므로 element_type:float 매핑을 사용하세요."
            )
        similarity = mapping.get("similarity", "cosine")
        if not isinstance(similarity, str) or similarity not in {"cosine", "dot_product", "l2_norm", "max_inner_product"}:
            raise ElasticsearchError(f"{concrete_index}의 rag_embedding similarity 값 {similarity!r}을 지원하지 않습니다.")
        index_options = mapping.get("index_options")
        if index_options is not None and not isinstance(index_options, dict):
            raise ElasticsearchError(f"{concrete_index}의 rag_embedding index_options 매핑이 올바르지 않습니다.")
        concrete[concrete_index] = mapping

    if not concrete:
        raise ElasticsearchError("선택한 인덱스 또는 alias에서 구체 인덱스 매핑을 찾지 못했습니다.")
    first_name = sorted(concrete)[0]
    first = concrete[first_name]
    first_semantics = (
        first["dims"], first.get("element_type", "float"),
        first.get("similarity", "cosine"), first.get("index_options"),
    )
    for concrete_index, mapping in sorted(concrete.items()):
        semantics = (
            mapping["dims"], mapping.get("element_type", "float"),
            mapping.get("similarity", "cosine"), mapping.get("index_options"),
        )
        if semantics != first_semantics:
            raise ElasticsearchError(
                "alias 대상의 rag_embedding 설정이 서로 다릅니다. 모든 구체 인덱스에서 dims, "
                "element_type, similarity 및 index_options를 동일하게 맞추세요 "
                f"({first_name}, {concrete_index})."
            )
    return first, set(concrete)


def vector_mapping(connection: Connection, index: str, *, require_dimensions: bool = True) -> dict[str, Any]:
    mapping, _ = vector_mapping_targets(connection, index, require_dimensions=require_dimensions)
    return mapping


def count_vectors(connection: Connection, index: str) -> int:
    query = {"query": {"exists": {"field": "rag_embedding"}}}
    result = request(connection, "POST", f"{quote(validate_index(index), safe='')}/_count", query)
    return int(result.get("count", 0))


def _filters(filters: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in filters or []:
        field = str(item.get("field", "")).strip()
        value = str(item.get("value", "")).strip()
        if not value:
            continue
        if field not in FILTER_FIELDS:
            raise ElasticsearchError(f"필터를 지원하지 않는 필드입니다: {field}")
        result.append({"term": {field: value}})
    return result


def _hits(response: dict[str, Any]) -> list[dict[str, Any]]:
    return response.get("hits", {}).get("hits", [])


def _lexical_search(
    connection: Connection,
    index: str,
    query_text: str,
    size: int,
    boosts: dict[str, float],
    filters: list[dict[str, str]] | None,
    source_fields: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    query = build_search_query(query_text, boosts, filters)
    body = {
        "size": size,
        "track_total_hits": True,
        "_source": source_fields,
        "query": query,
        "highlight": {
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "fields": {
                "summary": {}, "error_signature": {}, "root_cause": {},
                "workaround_or_fix": {}, "description": {}, "rag_chunk_text": {},
            },
        },
    }
    result = request(connection, "POST", f"{quote(validate_index(index), safe='')}/_search", body)
    return result, {"query": query, "body": body}


def _vector_search(
    connection: Connection,
    index: str,
    query_text: str,
    size: int,
    filters: list[dict[str, str]] | None,
    source_fields: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    vector_mapping(connection, index)
    vectors = count_vectors(connection, index)
    if vectors == 0:
        raise ElasticsearchError("이 인덱스에 임베딩이 없습니다. 먼저 ‘임베딩 생성’을 실행하세요.")
    query_vector = embeddings.embed_texts([query_text], "query")[0]
    filter_clauses = _filters(filters)
    knn: dict[str, Any] = {
        "field": "rag_embedding",
        "query_vector": query_vector,
        "k": size,
        "num_candidates": min(10000, max(50, size * 10)),
    }
    if filter_clauses:
        knn["filter"] = {"bool": {"filter": filter_clauses}}
    body = {"size": size, "track_total_hits": True, "_source": source_fields, "knn": knn}
    result = request(connection, "POST", f"{quote(validate_index(index), safe='')}/_search", body)
    inspection = {
        "field": "rag_embedding",
        "k": size,
        "num_candidates": knn["num_candidates"],
        "filter": knn.get("filter"),
        "model": embeddings.MODEL_NAME,
        "dimensions": embeddings.MODEL_DIMENSIONS,
    }
    return result, inspection


def _rrf(
    lexical_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    rank_constant: int,
    size: int,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for source_name, hits in (("bm25", lexical_hits), ("vector", vector_hits)):
        for rank, hit in enumerate(hits, start=1):
            document_index = str(hit.get("_index") or "")
            document_id = str(hit.get("_id", ""))
            identity = (document_index, document_id)
            entry = merged.get(identity)
            if entry is None:
                entry = {**hit, "retrieval_scores": {"bm25": None, "vector": None}, "_rrf_score": 0.0}
                merged[identity] = entry
            entry["retrieval_scores"][source_name] = hit.get("_score")
            entry["_rrf_score"] += 1.0 / (rank_constant + rank)
            if source_name == "bm25":
                # Keep comment inner hits and lexical highlights when present.
                entry["_source"] = hit.get("_source", entry.get("_source", {}))
                if hit.get("inner_hits"):
                    entry["inner_hits"] = hit["inner_hits"]
                if hit.get("highlight"):
                    entry["highlight"] = hit["highlight"]
    ordered = sorted(merged.values(), key=lambda hit: hit["_rrf_score"], reverse=True)[:size]
    for hit in ordered:
        hit["_score"] = hit.pop("_rrf_score")
    return ordered


def search(
    connection: Connection,
    index: str,
    query_text: str,
    size: int,
    boosts: dict[str, float],
    filters: list[dict[str, str]] | None = None,
    *,
    mode: str = "bm25",
    rank_constant: int = 60,
    source_fields: list[str] | None = None,
) -> dict[str, Any]:
    index = validate_index(index)
    if mode not in {"bm25", "vector", "hybrid"}:
        raise ElasticsearchError("검색 방식은 bm25, vector, hybrid 중 하나여야 합니다.")
    rank_constant = max(1, min(200, int(rank_constant)))
    source_fields = source_fields or ["issue_key", "summary", "status", "priority", "components", "error_signature", "root_cause", "workaround_or_fix", "description", "steps_to_reproduce", "comments", "rag_chunk_text", "source_url"]

    lexical_result: dict[str, Any] | None = None
    vector_result: dict[str, Any] | None = None
    lexical_info: dict[str, Any] | None = None
    vector_info: dict[str, Any] | None = None
    if mode in {"bm25", "hybrid"}:
        lexical_result, lexical_info = _lexical_search(
            connection, index, query_text, size, boosts, filters, source_fields
        )
    if mode in {"vector", "hybrid"}:
        vector_result, vector_info = _vector_search(
            connection, index, query_text, size, filters, source_fields
        )

    if mode == "bm25":
        result = lexical_result or {}
        hits = _hits(result)
        total = result.get("hits", {}).get("total", {}).get("value", len(hits))
        took = int(result.get("took", 0) or 0)
    elif mode == "vector":
        result = vector_result or {}
        hits = _hits(result)
        total = result.get("hits", {}).get("total", {}).get("value", len(hits))
        took = int(result.get("took", 0) or 0)
    else:
        left = lexical_result or {}
        right = vector_result or {}
        left_hits = _hits(left)
        right_hits = _hits(right)
        hits = _rrf(left_hits, right_hits, rank_constant, size)
        total = len({(str(hit.get("_index") or ""), str(hit.get("_id", ""))) for hit in left_hits + right_hits})
        took = int(left.get("took", 0) or 0) + int(right.get("took", 0) or 0)

    return {
        "query": {
            "mode": mode,
            "lexical": lexical_info["query"] if lexical_info else None,
            "knn": vector_info,
            "rank_constant": rank_constant if mode == "hybrid" else None,
        },
        "mode": mode,
        "took_ms": took,
        "total": total,
        "hits": hits,
        "vector_count": count_vectors(connection, index) if mode in {"vector", "hybrid"} else None,
    }
