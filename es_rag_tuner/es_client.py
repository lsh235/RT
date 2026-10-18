"""Small, dependency-free Elasticsearch HTTP client used by the local UI."""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


class ElasticsearchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, *, safe_for_user: bool = True):
        super().__init__(message)
        self.status = status
        self.safe_for_user = safe_for_user


class PrivateIndexAccessError(ElasticsearchError):
    """A local authorization guard rejected an Elasticsearch request target."""


def guard_shared_index_access(index: str) -> None:
    """Reject private aliases before callers decide how to report ES failures."""
    _guard_private_path(index, "GET")


# Private knowledge namespaces are authorization-sensitive even though the app
# uses one shared ES credential. The authenticated local account is bound by
# concepts.owner_scope for the lifetime of each protected request.
_LOCAL_OWNER: ContextVar[str | None] = ContextVar("es_rag_es_owner", default=None)
_PRIVATE_SYNC_ALLOWED: ContextVar[bool] = ContextVar("es_rag_private_sync_allowed", default=False)
_PRIVATE_READ_ALLOWED: ContextVar[bool] = ContextVar("es_rag_private_read_allowed", default=False)


def bind_local_owner(owner_id: str | None) -> Any:
    return _LOCAL_OWNER.set(owner_id)


def reset_local_owner(token: Any) -> None:
    _LOCAL_OWNER.reset(token)


@contextmanager
def private_sync_scope():
    token = _PRIVATE_SYNC_ALLOWED.set(True)
    try:
        yield
    finally:
        _PRIVATE_SYNC_ALLOWED.reset(token)


@contextmanager
def private_read_scope():
    token = _PRIVATE_READ_ALLOWED.set(True)
    try:
        yield
    finally:
        _PRIVATE_READ_ALLOWED.reset(token)


def private_alias(owner_id: str) -> str:
    return "esrag-private-" + re.sub(r"[^0-9a-f]", "", str(owner_id).lower())


def _guard_private_path(path: str, method: str = "GET") -> bool:
    owner_id = _LOCAL_OWNER.get()
    owner_alias = private_alias(owner_id) if owner_id else None
    # Normalize once so query strings and URL-encoded index names cannot evade
    # the same boundary checks used by the routes.
    raw_path = urllib.parse.urlsplit("/" + path.lstrip("/")).path
    decoded_path = raw_path
    for _ in range(4):
        decoded = urllib.parse.unquote(decoded_path)
        if decoded == decoded_path:
            break
        decoded_path = decoded
    segments = [segment for segment in decoded_path.split("/") if segment]
    private_target = False
    for segment in segments:
        name = urllib.parse.unquote(segment)
        if "esrag-private-" in name:
            for candidate in name.split(","):
                candidate = candidate.strip()
                if owner_alias is None or not (candidate == owner_alias or re.fullmatch(re.escape(owner_alias) + r"-g[0-9]+", candidate)):
                    raise PrivateIndexAccessError("Private knowledge index access denied", 403)
                private_target = True
    if decoded_path.startswith("/") and segments and segments[0] in {"_search", "_count", "_mapping", "_msearch"}:
        raise PrivateIndexAccessError("Index-scoped Elasticsearch requests are required", 403)
    if "," in decoded_path:
        raise PrivateIndexAccessError("Multi-index Elasticsearch requests are disabled for authenticated accounts", 403)
    if "*" in decoded_path or "?" in decoded_path:
        # The question mark is stripped from raw_path above, so here it only
        # catches path wildcards; query params do not participate.
        if "*" in decoded_path:
            raise PrivateIndexAccessError("Wildcard Elasticsearch access is disabled for authenticated accounts", 403)
    if segments and segments[0] == "_all":
        raise PrivateIndexAccessError("Wildcard Elasticsearch access is disabled for authenticated accounts", 403)
    if private_target and not (_PRIVATE_SYNC_ALLOWED.get() or _PRIVATE_READ_ALLOWED.get()):
        raise PrivateIndexAccessError("Private knowledge indexes are accessible only through private knowledge search/sync", 403)
    return private_target


def _body_index_targets(path: str, body: Any) -> list[str]:
    pathname = urllib.parse.urlsplit("/" + path.lstrip("/")).path
    if not any(pathname.endswith(suffix) for suffix in ("/_bulk", "_bulk", "/_msearch", "_msearch", "/_aliases", "_aliases", "/_reindex", "_reindex")):
        return []
    raw = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    targets: list[str] = []
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"_index", "index"} and isinstance(item, str):
                    targets.append(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for line in raw.splitlines():
        try:
            visit(json.loads(line))
        except (ValueError, TypeError):
            continue
    return targets


@dataclass(frozen=True)
class Connection:
    url: str
    auth_type: str = "none"
    username: str = ""
    password: str = ""
    api_key: str = ""

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> "Connection":
        raw_url = str(value.get("url", "http://127.0.0.1:9200")).strip().rstrip("/")
        parsed = urllib.parse.urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ElasticsearchError("URL은 http:// 또는 https:// 주소여야 합니다.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ElasticsearchError("URL에 사용자 정보, query, fragment를 넣지 말고 인증 입력란을 사용하세요.")
        auth = value.get("auth") or {}
        if not isinstance(auth, dict):
            raise ElasticsearchError("인증 값이 올바르지 않습니다.")
        auth_type = str(auth.get("type", "none"))
        if auth_type not in {"none", "basic", "api_key"}:
            raise ElasticsearchError("지원하지 않는 인증 방식입니다.")
        if auth_type == "basic" and not str(auth.get("username", "")):
            raise ElasticsearchError("Basic 인증에는 사용자 이름이 필요합니다.")
        if auth_type == "api_key" and not str(auth.get("api_key", "")):
            raise ElasticsearchError("API Key 인증 문자열을 입력하세요.")
        return cls(
            url=raw_url,
            auth_type=auth_type,
            username=str(auth.get("username", "")),
            password=str(auth.get("password", "")),
            api_key=str(auth.get("api_key", "")),
        )

    def authorization(self) -> str | None:
        if self.auth_type == "basic":
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            return f"Basic {token}"
        if self.auth_type == "api_key":
            return f"ApiKey {self.api_key.strip()}"
        return None


def validate_index(index: str) -> str:
    index = str(index).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,254}", index):
        raise ElasticsearchError("인덱스 이름은 소문자, 숫자, 점, 밑줄, 하이픈만 사용할 수 있습니다.")
    if index in {".", ".."} or index.startswith("_") or index.startswith("-") or index.startswith("+"):
        raise ElasticsearchError("올바르지 않은 Elasticsearch 인덱스 이름입니다.")
    return index


def request(
    connection: Connection,
    method: str,
    path: str,
    body: Any = None,
    *,
    content_type: str = "application/json",
    timeout: float = 30,
) -> Any:
    _guard_private_path(path, method)
    if body is not None:
        for target in _body_index_targets(path, body):
            target_method = "GET" if path.rstrip("/").endswith("_msearch") else method
            _guard_private_path(target, target_method)
    base = connection.url.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    headers = {"Accept": "application/json"}
    authorization = connection.authorization()
    if authorization:
        headers["Authorization"] = authorization
    if body is None:
        data = None
    elif isinstance(body, bytes):
        data = body
    elif isinstance(body, str):
        data = body.encode("utf-8")
        headers["Content-Type"] = content_type
    else:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            if not payload:
                return {}
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read(64 * 1024).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            error = parsed.get("error", parsed)
            if isinstance(error, dict):
                reason = error.get("reason") or error.get("type") or json.dumps(error, ensure_ascii=False)
            else:
                reason = str(error)
        except (ValueError, AttributeError):
            reason = raw.strip() or exc.reason
        raise ElasticsearchError(f"Elasticsearch HTTP {exc.code}: {reason}", exc.code, safe_for_user=False) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ElasticsearchError("Elasticsearch에 연결할 수 없습니다. 연결 주소와 서비스 상태를 확인하세요.", safe_for_user=False) from None
    except json.JSONDecodeError:
        raise ElasticsearchError("Elasticsearch가 JSON이 아닌 응답을 반환했습니다.") from None


def list_indices(connection: Connection) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"format": "json", "h": "index,health,status,docs.count,store.size"})
    result = request(connection, "GET", f"_cat/indices?{query}")
    if not isinstance(result, list):
        return []
    owner_id = _LOCAL_OWNER.get()
    alias = private_alias(owner_id) if owner_id else None
    return [row for row in result if not re.fullmatch(r"esrag-private-[0-9a-f]{32}(?:-g[0-9]+)?", str(row.get("index", ""))) or (alias is not None and (row.get("index") == alias or re.fullmatch(re.escape(alias) + r"-g[0-9]+", str(row.get("index", "")))))]


def index_exists(connection: Connection, index: str) -> bool:
    index = validate_index(index)
    try:
        request(connection, "HEAD", urllib.parse.quote(index, safe=""))
        return True
    except ElasticsearchError as exc:
        if exc.status == 404:
            return False
        raise


def count_documents(connection: Connection, index: str) -> int:
    index = validate_index(index)
    result = request(connection, "GET", f"{urllib.parse.quote(index, safe='')}/_count")
    return int(result.get("count", 0))


def build_search_query(
    query_text: str,
    boosts: dict[str, float],
    filters: list[dict[str, str]] | None = None,
    *,
    comments: bool = True,
    include_inner_hits: bool = True,
) -> dict[str, Any]:
    """Build an inspectable lexical query; comment fields retain nested semantics."""
    should: list[dict[str, Any]] = []
    main_fields = [
        f"{field}^{float(weight):g}"
        for field, weight in boosts.items()
        if not field.startswith("comments.") and float(weight) > 0
    ]
    nested_fields = [
        f"{field}^{float(weight):g}"
        for field, weight in boosts.items()
        if field.startswith("comments.") and float(weight) > 0
    ]
    if main_fields:
        should.append({"multi_match": {
            "query": query_text,
            "type": "best_fields",
            "fields": main_fields,
            "tie_breaker": 0.3,
        }})
    if comments and nested_fields:
        nested_query: dict[str, Any] = {
            "path": "comments",
            "score_mode": "max",
            "query": {"multi_match": {
                "query": query_text,
                "type": "best_fields",
                "fields": nested_fields,
                "tie_breaker": 0.3,
            }},
        }
        if include_inner_hits:
            nested_query["inner_hits"] = {"size": 2}
        should.append({"nested": nested_query})
    if re.fullmatch(r"(?i)GRPC-\d+", query_text.strip()):
        should.append({"term": {"issue_key": {"value": query_text.strip().upper(), "boost": 20}}})
    if not should:
        raise ElasticsearchError("검색에 사용할 필드 가중치를 0보다 크게 설정하세요.")

    bool_query: dict[str, Any] = {"should": should, "minimum_should_match": 1}
    valid_filter_fields = {
        "issue_key", "issue_type", "status", "priority", "resolution", "components",
        "labels", "language", "affected_versions", "fix_versions", "project.key",
    }
    filter_queries = []
    for item in filters or []:
        field = str(item.get("field", "")).strip()
        value = str(item.get("value", "")).strip()
        if not value:
            continue
        if field not in valid_filter_fields:
            raise ElasticsearchError(f"필터를 지원하지 않는 필드입니다: {field}")
        filter_queries.append({"term": {field: value}})
    if filter_queries:
        bool_query["filter"] = filter_queries
    return {"bool": bool_query}

