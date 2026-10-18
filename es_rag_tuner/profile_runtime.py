"""Credential-free profile runtime helper for external Python consumers."""

from __future__ import annotations

from typing import Any

from . import concepts
from .es_client import Connection, ElasticsearchError


def search_profile(
    connection: Connection | dict[str, Any],
    profile: dict[str, Any],
    query: str,
    *,
    filters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a saved BM25 concept profile using the same query builder as preview.

    ``profile`` is the ``profile`` object returned by
    :func:`es_rag_tuner.concepts.export_profile`. Connection credentials are
    supplied at call time and are never read from the profile.
    """
    if not isinstance(profile, dict) or profile.get("format") != "es-rag-profile-v1":
        raise ElasticsearchError("지원하지 않는 검색 프로필 형식입니다.")
    concept = concepts.validate_concept(profile.get("concept"))
    query = str(query).strip()
    if not query or len(query) > concepts.MAX_TEXT:
        raise ElasticsearchError("검색어는 1~4000자여야 합니다.")
    if isinstance(connection, dict):
        connection = Connection.from_payload(connection)
    if not isinstance(connection, Connection):
        raise ElasticsearchError("connection은 Connection 또는 연결 설정 object여야 합니다.")
    concepts._validate_search_fields(connection, concept)
    effective = concept["filters"] if filters is None else filters
    if not isinstance(effective, list) or len(effective) > concepts.MAX_FIELDS:
        raise ElasticsearchError("filters는 허용된 크기의 배열이어야 합니다.")
    for item in effective:
        if not isinstance(item, dict) or item.get("field") not in concept["corpus"]["filter_fields"]:
            raise ElasticsearchError("filters에는 concept에 지정한 filter_fields만 사용할 수 있습니다.")
    effective = concepts._normalize_filters(concept, effective)
    result = concepts._hits(
        connection,
        concept["corpus"]["index"],
        query,
        concept["settings"]["size"],
        concept,
        expanded=True,
        filters=effective,
    )
    return {
        "index": concept["corpus"]["index"],
        "query": query,
        "version_id": profile.get("version_id"),
        "profile_fingerprint": profile.get("fingerprint"),
        "effective_filters": effective,
        "total": result["total"],
        "hits": result["hits"],
    }
