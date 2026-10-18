"""Benchmark and coordinate-search helpers for the supplied Jira issue set."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .es_client import Connection, ElasticsearchError, request, validate_index


DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_PATH = DATA_DIR / "es_jira_index_mapping_and_tuning.json"
BULK_PATH = DATA_DIR / "grpc_jira_issues_es_bulk.ndjson"
TARGET_RECALL_AT_5 = 0.90
TARGET_MRR_AT_5 = 0.80
K = 5

# The initial values mirror the provided lexical BM25 query template. Code fields
# are separate because the custom analyzer is a distinct retrieval signal.
DEFAULT_PROFILE: dict[str, float] = {
    "error_signature": 4.0,
    "summary": 3.0,
    "summary.code": 3.5,
    "root_cause": 2.5,
    "root_cause.code": 2.5,
    "workaround_or_fix": 2.0,
    "description": 1.0,
    "description.code": 1.0,
    "steps_to_reproduce": 1.0,
    "rag_chunk_text": 1.5,
    "rag_chunk_text.code": 1.5,
    "comments.body": 1.5,
    "comments.body.code": 2.0,
}


def benchmark_queries() -> list[dict[str, Any]]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    queries = data.get("rag_evaluation_ground_truth", [])
    if not queries:
        raise ElasticsearchError("평가 쿼리를 설정 파일에서 찾을 수 없습니다.")
    return queries


def _search_body(query: dict[str, Any], size: int = K, source: Any = True) -> dict[str, Any]:
    return {"size": size, "track_total_hits": False, "_source": source, "query": query}


def _msearch(connection: Connection, index: str, bodies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = validate_index(index)
    lines: list[str] = []
    for body in bodies:
        lines.append("{}")
        lines.append(json.dumps(body, ensure_ascii=False, separators=(",", ":")))
    payload = "\n".join(lines) + "\n"
    result = request(
        connection,
        "POST",
        f"{index}/_msearch",
        payload,
        content_type="application/x-ndjson",
        timeout=90,
    )
    responses = result.get("responses", [])
    if len(responses) != len(bodies):
        raise ElasticsearchError("Elasticsearch _msearch 응답 수가 요청 수와 다릅니다.")
    for response in responses:
        if "error" in response:
            error = response["error"]
            reason = error.get("reason", str(error)) if isinstance(error, dict) else str(error)
            raise ElasticsearchError(f"평가 검색 실패: {reason}", response.get("status"), safe_for_user=False)
    return responses


def _metrics(queries: list[dict[str, Any]], responses: list[dict[str, Any]], k: int = K) -> dict[str, Any]:
    rows = []
    found_total = 0
    expected_total = 0
    reciprocal_ranks = []
    precisions = []
    ndcgs = []
    for query, response in zip(queries, responses):
        expected = {str(value).upper() for value in query.get("expected_issue_keys", [])}
        hits = response.get("hits", {}).get("hits", [])[:k]
        keys = [str(hit.get("_source", {}).get("issue_key", hit.get("_id", ""))).upper() for hit in hits]
        relevant_ranks = [i for i, key in enumerate(keys, 1) if key in expected]
        found = len(set(keys) & expected)
        rr = 1 / relevant_ranks[0] if relevant_ranks else 0.0
        dcg = sum(1 / math.log2(rank + 1) for rank in relevant_ranks)
        ideal_count = min(len(expected), k)
        ideal = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        ndcg = dcg / ideal if ideal else 0.0
        found_total += found
        expected_total += len(expected)
        reciprocal_ranks.append(rr)
        precisions.append(found / k)
        ndcgs.append(ndcg)
        rows.append({
            "query_id": query.get("query_id", query.get("id", "")),
            "query": query.get("query", ""),
            "expected": sorted(expected),
            "found": sorted(set(keys) & expected),
            "ranked": keys,
            "recall_at_5": found / len(expected) if expected else 0.0,
            "precision_at_5": found / k,
            "reciprocal_rank_at_5": rr,
            "ndcg_at_5": ndcg,
        })
    recall = found_total / expected_total if expected_total else 0.0
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
    precision = sum(precisions) / len(precisions) if precisions else 0.0
    ndcg_mean = sum(ndcgs) / len(ndcgs) if ndcgs else 0.0
    score = 0.55 * recall + 0.45 * mrr
    return {
        "k": k,
        "query_count": len(queries),
        "expected_relevant_count": expected_total,
        "retrieved_relevant_count": found_total,
        "recall_at_5": recall,
        "precision_at_5": precision,
        "mrr_at_5": mrr,
        "ndcg_at_5": ndcg_mean,
        "objective_score": score,
        "target": {"recall_at_5": TARGET_RECALL_AT_5, "mrr_at_5": TARGET_MRR_AT_5},
        "target_met": recall >= TARGET_RECALL_AT_5 and mrr >= TARGET_MRR_AT_5,
        "queries": rows,
    }


def _query_for(
    query: dict[str, Any],
    profile: dict[str, float],
    include_inner_hits: bool = False,
) -> dict[str, Any]:
    from .es_client import build_search_query

    return build_search_query(
        str(query.get("query", "")), profile, include_inner_hits=include_inner_hits
    )


def evaluate(
    connection: Connection,
    index: str,
    profile: dict[str, float] | None = None,
    mode: str = "bm25",
    rank_constant: int = 60,
) -> dict[str, Any]:
    queries = benchmark_queries()
    profile = profile or DEFAULT_PROFILE
    if mode == "bm25":
        bodies = [_search_body(_query_for(item, profile), K, ["issue_key"]) for item in queries]
        responses = _msearch(connection, index, bodies)
    elif mode in {"vector", "hybrid"}:
        from .retrieval import search

        responses = []
        for item in queries:
            result = search(
                connection,
                index,
                str(item.get("query", "")),
                K,
                profile,
                mode=mode,
                rank_constant=rank_constant,
                source_fields=["issue_key"],
            )
            responses.append({"hits": {"hits": result["hits"]}})
    else:
        raise ElasticsearchError("평가 검색 방식은 bm25, vector, hybrid 중 하나여야 합니다.")
    return {"profile": profile, "mode": mode, "metrics": _metrics(queries, responses)}


def _evaluate_profiles(
    connection: Connection,
    index: str,
    queries: list[dict[str, Any]],
    profiles: list[dict[str, float]],
    batch_searches: int = 100,
) -> list[dict[str, Any]]:
    # Keep each _msearch request bounded and map results back to (profile, query).
    entries: list[tuple[int, int, dict[str, Any]]] = []
    for profile_index, profile in enumerate(profiles):
        for query_index, item in enumerate(queries):
            entries.append((profile_index, query_index, _search_body(_query_for(item, profile), K, ["issue_key"])))
    all_responses: list[dict[str, Any] | None] = [None] * len(entries)
    for start in range(0, len(entries), batch_searches):
        batch = entries[start:start + batch_searches]
        responses = _msearch(connection, index, [entry[2] for entry in batch])
        for offset, response in enumerate(responses):
            all_responses[start + offset] = response
    grouped: list[list[dict[str, Any]]] = [[] for _ in profiles]
    for entry, response in zip(entries, all_responses):
        profile_index, _, _ = entry
        assert response is not None
        grouped[profile_index].append(response)
    return [_metrics(queries, group) for group in grouped]


def tune(
    connection: Connection,
    index: str,
    initial_profile: dict[str, float] | None = None,
    passes: int = 2,
) -> dict[str, Any]:
    """Run deterministic coordinate search against all supplied judgments."""
    queries = benchmark_queries()
    current = {**DEFAULT_PROFILE, **(initial_profile or {})}
    baseline = evaluate(connection, index, current)["metrics"]
    best_profile = current.copy()
    best_metrics = baseline
    rounds: list[dict[str, Any]] = []
    tried: set[tuple[tuple[str, float], ...]] = {tuple(sorted(current.items()))}

    for pass_number in range(1, max(1, min(int(passes), 3)) + 1):
        profiles: list[dict[str, float]] = []
        factors = (0.0, 0.5, 0.75, 1.0, 1.5, 2.0)
        for field, base_value in DEFAULT_PROFILE.items():
            anchor = best_profile.get(field, base_value) or base_value
            for factor in factors:
                candidate = best_profile.copy()
                candidate[field] = round(anchor * factor, 4)
                signature = tuple(sorted(candidate.items()))
                if signature not in tried:
                    tried.add(signature)
                    profiles.append(candidate)
        if not profiles:
            break
        outcomes = _evaluate_profiles(connection, index, queries, profiles)
        results = [
            {"profile": profile, "metrics": metrics}
            for profile, metrics in zip(profiles, outcomes)
        ]
        results.sort(key=lambda item: (
            item["metrics"]["target_met"],
            item["metrics"]["objective_score"],
            item["metrics"]["mrr_at_5"],
            item["metrics"]["recall_at_5"],
        ), reverse=True)
        winner = results[0]
        improved = winner["metrics"]["objective_score"] > best_metrics["objective_score"] + 1e-12
        if improved:
            best_profile = winner["profile"]
            best_metrics = winner["metrics"]
        rounds.append({
            "pass": pass_number,
            "candidate_count": len(results),
            "best_candidate_score": winner["metrics"]["objective_score"],
            "improved": improved,
            "top_candidates": results[:5],
        })
        if best_metrics["target_met"]:
            break

    return {
        "baseline": {"profile": current, "metrics": baseline},
        "best": {"profile": best_profile, "metrics": best_metrics},
        "rounds": rounds,
        "target_met": best_metrics["target_met"],
        "method": "deterministic coordinate search over supplied Q01-Q10 labels",
    }

