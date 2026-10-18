"""Local codebase-memory-mcp access for gRPC code retrieval."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPO_PATH = PROJECT_DIR / "data" / "sources" / "grpc"
STOPWORDS = {
    "grpc", "grpcio", "the", "and", "for", "with", "from", "that", "this",
    "what", "when", "where", "which", "does", "how", "why", "can", "are",
    "was", "were", "into", "about", "code", "source", "issue", "error",
    "http", "slow", "connection", "connections", "occurs", "occurring",
}
_PROJECT_CACHE: tuple[str, float, dict[str, Any]] | None = None


class CodebaseError(RuntimeError):
    """A local codebase-memory-mcp command or index lookup failed."""


def repository_path() -> Path:
    configured = os.environ.get("ES_RAG_GRPC_REPO_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_REPO_PATH.resolve()


def _binary() -> str:
    configured = os.environ.get("CODEBASE_MEMORY_MCP", "codebase-memory-mcp").strip()
    binary = shutil.which(configured)
    if not binary:
        raise CodebaseError(
            "codebase-memory-mcp CLI를 찾을 수 없습니다. 먼저 codebase-memory-mcp를 설치하세요."
        )
    return binary


def _run(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    command = [_binary(), "cli", "--quiet", tool]
    payload = dict(args or {})
    payload.setdefault("format", "json")
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CodebaseError(f"codebase-memory-mcp {tool} 실행 시간이 60초를 넘었습니다.") from None
    except OSError as exc:
        raise CodebaseError(f"codebase-memory-mcp {tool} 실행 실패: {exc}") from None
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:800]
        raise CodebaseError(f"codebase-memory-mcp {tool} 실패: {detail or '알 수 없는 오류'}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise CodebaseError(f"codebase-memory-mcp {tool}이 JSON이 아닌 응답을 반환했습니다.") from None
    if not isinstance(value, dict):
        raise CodebaseError(f"codebase-memory-mcp {tool} 응답 형식이 올바르지 않습니다.")
    return value


def _indexed_project(repo: Path) -> dict[str, Any]:
    global _PROJECT_CACHE
    if not repo.is_dir():
        raise CodebaseError(f"gRPC 저장소 경로가 없습니다: {repo}")
    now = time.monotonic()
    if _PROJECT_CACHE and _PROJECT_CACHE[0] == str(repo) and now - _PROJECT_CACHE[1] < 60:
        return _PROJECT_CACHE[2]
    listing = _run("list_projects")
    projects = listing.get("projects", [])
    for project in projects if isinstance(projects, list) else []:
        if not isinstance(project, dict):
            continue
        root = project.get("root_path")
        if root and Path(str(root)).resolve() == repo:
            _PROJECT_CACHE = (str(repo), now, project)
            return project
    raise CodebaseError(
        "gRPC 저장소가 codebase-memory-mcp에 아직 색인되지 않았습니다. "
        "‘docs/code + Jira RAG’ 안내의 색인 명령을 실행하세요."
    )


def status() -> dict[str, Any]:
    repo = repository_path()
    if not repo.is_dir():
        return {"available": False, "indexed": False, "repo_path": str(repo)}
    project = _indexed_project(repo)
    detail = _run("index_status", {"project": project["name"]})
    try:
        commit_result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        commit = commit_result.stdout.strip()[:40] if commit_result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        commit = None
    return {
        "available": True,
        "indexed": detail.get("status") == "ready",
        "project": project.get("name"),
        "repo_path": str(repo),
        "branch": project.get("branch"),
        "commit": commit,
        "indexed_at": detail.get("indexed_at"),
        "nodes": detail.get("nodes"),
        "edges": detail.get("edges"),
        "partial_parse_files": detail.get("parse_partial", {}).get("count", 0),
        "unusable_parse_files": detail.get("parse_unusable", {}).get("count", 0),
        "not_indexed_files": detail.get("not_indexed", {}).get("files_count", 0),
    }


def _expanded_query(query: str, issue_hits: list[dict[str, Any]]) -> str:
    context = [query]
    for hit in issue_hits[:3]:
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            continue
        for field in ("summary", "error_signature", "root_cause", "workaround_or_fix"):
            value = str(source.get(field, "")).strip()
            if value:
                context.append(value)
    return "\n".join(context)[:5000]


def _query_terms(text: str, maximum: int = 12) -> list[str]:
    terms: list[str] = []
    folded: set[str] = set()
    for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text):
        term = raw.strip("_")
        key = term.casefold()
        if len(term) < 3 or key in STOPWORDS or key in folded:
            continue
        terms.append(term)
        folded.add(key)
        if len(terms) == maximum:
            break
    return terms


def _code_search_patterns(query: str, issue_hits: list[dict[str, Any]], maximum: int = 8) -> list[str]:
    primary = _query_terms(query, maximum=6)
    issue_identifiers: list[str] = []
    secondary: list[str] = []
    primary_folded = {term.casefold() for term in primary}
    if "keepalive" in primary_folded and ("watchdog" in primary_folded or "timeout" in primary_folded):
        issue_identifiers.append("keepalive_ping_timeout")
    for hit in issue_hits[:3]:
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            continue
        for field in ("error_signature", "summary", "root_cause", "workaround_or_fix"):
            value = str(source.get(field, ""))
            for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", value):
                term = raw.strip("_")
                folded = term.casefold()
                if len(term) < 3 or folded in STOPWORDS:
                    continue
                target = issue_identifiers if (
                    "_" in term and any(key in folded for key in ("keepalive", "watchdog", "timeout", "transport"))
                ) else secondary
                if term not in target:
                    target.append(term)

    # Phrase searches preserve useful co-occurrence in docs/tests; individual
    # identifiers then find the implementation and argument parsing sites.
    phrases = [" ".join(primary[index:index + 2]) for index in range(len(primary) - 1)]
    phrases = [phrase for phrase in phrases if len(phrase) > 3]
    ordered = phrases[:1] + primary + issue_identifiers + secondary
    patterns: list[str] = []
    seen: set[str] = set()
    for pattern in ordered:
        key = pattern.casefold()
        if key in seen:
            continue
        seen.add(key)
        patterns.append(pattern)
        if len(patterns) >= maximum:
            break
    return patterns


def _semantic_hits(result: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    table = result.get("semantic", {})
    columns = table.get("cols", []) if isinstance(table, dict) else []
    rows = table.get("rows", []) if isinstance(table, dict) else []
    hits: list[dict[str, Any]] = []
    for row in rows[:limit]:
        record = dict(zip(columns, row))
        hits.append({
            "qualified_name": record.get("qn", ""),
            "label": record.get("label", ""),
            "file": record.get("file", ""),
            "score": record.get("score"),
        })
    return hits


def _source_hits(result: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    columns = result.get("cols", [])
    rows = result.get("rows", [])
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        record = dict(zip(columns, row))
        file = str(record.get("file", ""))
        lines = str(record.get("lines", ""))
        identity = (file, lines)
        if not file or identity in seen:
            continue
        seen.add(identity)
        source = record.get("source", {})
        snippet = source.get("source", "") if isinstance(source, dict) else ""
        hits.append({
            "qualified_name": str(record.get("qn", "")),
            "label": str(record.get("label", "")),
            "file": file,
            "lines": lines,
            "matches": record.get("matches", []),
            "snippet": str(snippet)[:6000],
            "source_truncated": bool(source.get("source_truncated")) if isinstance(source, dict) else False,
            "matched_terms": record.get("matched_terms", []),
            "retrieval": "code_search",
        })
        if len(hits) >= limit:
            break
    if hits:
        return hits

    raw = result.get("raw_matches", {})
    raw_columns = raw.get("cols", []) if isinstance(raw, dict) else []
    raw_rows = raw.get("rows", []) if isinstance(raw, dict) else []
    for row in raw_rows:
        record = dict(zip(raw_columns, row))
        hits.append({
            "qualified_name": "",
            "label": "Source line",
            "file": str(record.get("file", "")),
            "lines": str(record.get("line", "")),
            "matches": [],
            "snippet": str(record.get("content", ""))[:1000],
            "source_truncated": False,
            "retrieval": "code_search",
        })
        if len(hits) >= limit:
            break
    return hits


def _literal_code_search(
    project: str,
    terms: list[str],
    limit: int,
    source_files: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Search code terms separately, then rank entities matched by multiple terms first."""
    combined: dict[tuple[str, str], dict[str, Any]] = {}
    truncated = False
    specs: list[tuple[str, str | None]] = [(term, None) for term in terms]
    if source_files:
        scoped_term = next((term for term in terms if "_" in term and " " not in term), terms[0] if terms else "")
        if scoped_term:
            specs.extend((scoped_term, f"*{Path(source_file).name}") for source_file in source_files[:2])

    def search_pattern(spec: tuple[str, str | None]) -> tuple[str, str | None, dict[str, Any]]:
        term, file_pattern = spec
        args: dict[str, Any] = {
            "project": project,
            "pattern": term,
            "regex": False,
            "mode": "full",
            "context": 2,
            "result_limit": max(6, min(10, limit + 2)),
            "raw_limit": 0,
            "match_limit": 6,
            "source_max_lines": 24,
            "max_output_tokens": 2400,
        }
        if file_pattern:
            args["file_pattern"] = file_pattern
        result = _run("search_code", args)
        return term, file_pattern, result

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(specs)))) as pool:
        results = list(pool.map(search_pattern, specs))
    for term, file_pattern, result in results:
        truncated = truncated or bool(result.get("truncated", False))
        columns = result.get("cols", [])
        for row in result.get("rows", []):
            record = dict(zip(columns, row))
            file = str(record.get("file", ""))
            qn = str(record.get("qn", ""))
            if not file:
                continue
            identity = (file, qn or str(record.get("lines", "")))
            current = combined.get(identity)
            if current is None:
                current = dict(record)
                current["matched_terms"] = []
                current["match_lines"] = set()
                combined[identity] = current
            if term not in current["matched_terms"]:
                current["matched_terms"].append(term)
            if file_pattern and f"Jira source: {Path(file_pattern[1:]).name}" not in current["matched_terms"]:
                current["matched_terms"].append(f"Jira source: {Path(file_pattern[1:]).name}")
            current["match_lines"].update(record.get("matches", []) or [])
            existing_source = current.get("source", {})
            new_source = record.get("source", {})
            if isinstance(new_source, dict) and len(str(new_source.get("source", ""))) > len(str(existing_source.get("source", "")) if isinstance(existing_source, dict) else ""):
                current["source"] = new_source

    records = list(combined.values())
    for record in records:
        record["matches"] = sorted(record.pop("match_lines", set()))
    # Hits corroborated by several query/Jira terms are more useful than broad single-term matches.
    records.sort(key=lambda item: (
        -int(any(str(term).startswith("Jira source:") for term in item.get("matched_terms", []))),
        -len(item.get("matched_terms", [])),
        -len(item.get("matches", [])),
        str(item.get("file", "")),
    ))
    corroborated = [record for record in records if len(record.get("matched_terms", [])) > 1]
    if corroborated:
        records = corroborated
    columns = list(records[0].keys()) if records else []
    rows = [[record.get(column) for column in columns] for record in records]
    hits = _source_hits({"cols": columns, "rows": rows}, limit)
    return hits, len(records), truncated


def search(query: str, issue_hits: list[dict[str, Any]], size: int = 5) -> dict[str, Any]:
    repo = repository_path()
    project = _indexed_project(repo)
    enriched = _expanded_query(query, issue_hits)
    limit = max(3, min(int(size), 10))

    semantic_result = _run("search_graph", {
        "project": project["name"],
        "semantic_query": [enriched],
        "semantic_limit": limit,
        "max_output_tokens": 3000,
    })

    terms = _code_search_patterns(query, issue_hits, maximum=8)
    source_files: list[str] = []
    for hit in issue_hits[:3]:
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            continue
        for field in ("error_signature", "summary", "root_cause", "workaround_or_fix"):
            for path in re.findall(r"\b(?:src|test|include|doc)/[A-Za-z0-9_./-]+\.(?:cc|cpp|c|h|md)\b", str(source.get(field, ""))):
                if path not in source_files:
                    source_files.append(path)
    code_hits, code_candidates, search_truncated = (
        _literal_code_search(project["name"], terms, limit, source_files) if terms else ([], 0, False)
    )

    return {
        "project": project.get("name"),
        "repo_path": str(repo),
        "expanded_terms": terms,
        "semantic_total": semantic_result.get("semantic_total", 0),
        "semantic_hits": _semantic_hits(semantic_result, limit),
        "total_code_matches": code_candidates,
        "code_hits": code_hits,
        "search_truncated": search_truncated,
    }


def compose_answer(issue_result: dict[str, Any], code_result: dict[str, Any]) -> dict[str, str]:
    """Build a transparent extractive answer from retrieved fields and code references."""
    issue_hits = issue_result.get("hits", [])
    code_hits = code_result.get("code_hits", [])
    parts: list[str] = []
    if issue_hits:
        hit = issue_hits[0]
        source = hit.get("_source", {})
        if not isinstance(source, dict):
            source = {}
        key = str(source.get("issue_key", hit.get("_id", "관련 이슈")))
        summary = str(source.get("summary", "")).strip()
        if summary:
            parts.append(f"가장 관련된 Jira 문서는 {key} ({summary})입니다.")
        root_cause = str(source.get("root_cause", "")).strip()
        resolution = str(source.get("workaround_or_fix", "")).strip()
        if root_cause:
            parts.append(f"이 문서가 기록한 원인: {root_cause[:900]}")
        if resolution:
            parts.append(f"문서에 기록된 해결/우회 방법: {resolution[:700]}")
    else:
        parts.append("현재 Jira 인덱스에서 관련 문서를 찾지 못했습니다.")

    if code_hits:
        refs = [
            f"{item['file']}:{item['lines']}" if item.get("lines") else str(item.get("file", ""))
            for item in code_hits[:3]
        ]
        refs = [ref for ref in refs if ref]
        if refs:
            parts.append("현재 gRPC 코드 색인에서 대조할 근거를 찾았습니다: " + ", ".join(refs) + ".")
        read_handler = next((
            item for item in code_hits
            if "read_action_locked" in str(item.get("qualified_name", ""))
            or "cancel any pending keepalive timers" in str(item.get("snippet", "")).lower()
        ), None)
        first_source = issue_hits[0].get("_source", {}) if issue_hits else {}
        if not isinstance(first_source, dict):
            first_source = {}
        root_cause = str(first_source.get("root_cause", "")).lower()
        if read_handler and "does not cancel" in root_cause:
            location = f"{read_handler.get('file', '')}:{read_handler.get('lines', '')}".rstrip(":")
            parts.append(
                f"대조 시 주의: 현재 색인의 read_action_locked({location})에는 incoming read 때 pending keepalive timer를 취소하는 코드가 보입니다. "
                "Jira 원인 필드는 수신 데이터가 이미 보낸 ping의 watchdog을 취소하지 않는다고 기록하므로, 이슈 당시 버전과 최신 master의 동작 차이를 원문으로 확인해야 합니다."
            )
    else:
        parts.append("코드 색인에서 일치하는 원문 발췌를 찾지 못했습니다. 의미 검색 후보를 확인하세요.")

    return {
        "text": " ".join(parts),
        "kind": "extractive_evidence_summary",
        "notice": "이 요약은 검색된 Jira 원인·해결 필드와 코드 위치를 묶었습니다. 모델이 새로 생성한 설명은 아니며, 아래 원문 근거를 함께 확인하세요.",
    }
