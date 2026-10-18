"""Loopback-only HTTP server for the retrieval workbench."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from http.cookies import SimpleCookie
import secrets
import sqlite3

from . import __version__, codebase
from . import evaluation
from . import embeddings
from . import concepts
from . import ai_coach
from . import token_preview
from . import reranker as local_reranker
from . import evaluation_datasets
from . import auth
from . import knowledge
from . import post_routes
from . import storage
from .indexing import vectorize_index
from .es_client import (
    Connection,
    ElasticsearchError,
    PrivateIndexAccessError,
    build_search_query,
    count_documents,
    guard_shared_index_access,
    index_exists,
    list_indices,
    request,
    validate_index,
)
from .retrieval import FILTER_FIELDS, count_vectors, search as retrieve, vector_mapping, vector_mapping_targets


PACKAGE_DIR = Path(__file__).resolve().parent
WEB = PACKAGE_DIR / "web"
STATIC_FILES = {
    "/": WEB / "index.html",
    "/app.js": WEB / "app.js",
    "/api-client.js": WEB / "api-client.js",
    "/cycle44-positive-target-misses.js": WEB / "cycle44-positive-target-misses.js",
    "/style.css": WEB / "style.css",
}
# JSON can escape each stored control character as six ASCII bytes. This bound
# accommodates the 20 MiB account quota plus JSON framing on restore routes.
_ORDINARY_JSON_LIMIT = 2 * 1024 * 1024
_RESTORE_JSON_LIMIT = 128 * 1024 * 1024
_DATASET_JSON_LIMIT = 12 * 1024 * 1024
ALLOWED_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
DISPLAY_FIELDS = [
    "issue_key", "summary", "status", "priority", "components", "error_signature",
    "root_cause", "workaround_or_fix", "description", "steps_to_reproduce", "comments",
    "rag_chunk_text", "source_url",
]


def _load_sample_mapping() -> tuple[str, dict[str, Any]]:
    config = json.loads(evaluation.CONFIG_PATH.read_text(encoding="utf-8"))
    index_name = str(config.get("metadata", {}).get("target_index", "jira-grpc-issues"))
    body = config.get("index_creation_request", {}).get("body")
    if not isinstance(body, dict):
        raise ElasticsearchError("샘플 설정에 index_creation_request.body가 없습니다.")
    return validate_index(index_name), body


def _expected_sample_count() -> int:
    count = 0
    with evaluation.BULK_PATH.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip() and '"_index"' in line:
                count += 1
    return count


def _problem_text(exc: Exception) -> str:
    return str(exc)[:1200]


def _error_code(status: int, area: str = "REQUEST") -> str:
    """Stable machine-readable API error family, independent of prose wording."""
    if status == 401:
        return "AUTH_REQUIRED"
    if status == 403:
        return "REQUEST_FORBIDDEN"
    if status == 404:
        return "NOT_FOUND"
    if status == 409:
        return "CONFLICT"
    if status == 413:
        return "REQUEST_TOO_LARGE"
    if status == 429:
        return "RATE_LIMITED"
    if status >= 500:
        return f"{area}_UNAVAILABLE"
    return "INVALID_REQUEST"


def _safe_domain_message(exc: ElasticsearchError) -> str:
    # Local validation messages are useful to the operator. Remote server and
    # transport responses can include document text, endpoints, or credentials.
    if exc.safe_for_user:
        return _problem_text(exc)
    return "Elasticsearch 요청을 완료할 수 없습니다. 연결과 인덱스 상태를 확인하세요."


def _sample_bulk_failures(items: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    failures = []
    for item in items:
        operation = next(iter(item.values()), {}) if isinstance(item, dict) else {}
        if not isinstance(operation, dict) or int(operation.get("status", 200)) < 300:
            continue
        failures.append({"id": operation.get("_id"), "status": operation.get("status"), "code": "REMOTE_ITEM_REJECTED", "error": "문서 적재를 완료하지 못했습니다."})
        if len(failures) >= limit:
            break
    return failures


def _public_token_preview_result(result: dict[str, Any]) -> dict[str, Any]:
    public = dict(result)
    public.pop("cache_path", None)
    reason = public.get("reason")
    if not public.get("available") and isinstance(reason, str):
        lower = reason.lower()
        if any(marker in reason for marker in ("/", "\\")) or any(marker in lower for marker in ("errno", "traceback", "permissionerror", "filenotfounderror", "sqlite")):
            public["reason"] = "토큰 미리보기를 사용할 수 없습니다. 설치와 로컬 캐시 상태를 확인하세요."
    return public


def _shared_vector_failure_is_unavailable(exc: ElasticsearchError) -> bool:
    """Keep local authorization/input failures out of the shared-lane fallback."""
    if isinstance(exc, PrivateIndexAccessError) or exc.status == 401:
        return False
    if exc.status in {403, 404, 408, 429} or (exc.status is not None and exc.status >= 500):
        return True
    if exc.status is None:
        # Request shape, index name, size, boosts, mode, and filters are checked
        # before entering retrieve(); remaining local ES errors describe vector
        # mapping/model/readiness failures, while transport errors are also safe
        # to present as an unavailable shared lane.
        return True
    if exc.status == 400:
        message = str(exc).lower()
        return any(marker in message for marker in ("dense_vector", "rag_embedding", "knn", "vector", "mapping", "no handler for type"))
    return False


class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version = "ESRagTuner/" + __version__
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        # Request targets and headers can carry credentials; keep the local
        # server's default access log from recording them.
        return

    def _guard_local_request(self, *, require_origin: bool = False) -> bool:
        raw_host = self.headers.get("Host", "").lower()
        if raw_host.startswith("[") and "]" in raw_host:
            host = raw_host[1:raw_host.index("]")]
        else:
            host = raw_host.rsplit(":", 1)[0] if raw_host.count(":") == 1 else raw_host
        if host not in {"localhost", "127.0.0.1", "::1"}:
            self._api_error(403, "이 워크벤치는 loopback에서만 접근할 수 있습니다.", "REQUEST_FORBIDDEN")
            return False
        origin = self.headers.get("Origin")
        parts = urlsplit(origin or "")
        try:
            origin_port = parts.port or (80 if parts.scheme == "http" else 443)
        except ValueError:
            origin_port = -1
        if require_origin and (parts.scheme != "http" or parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment or parts.hostname not in {"localhost", "127.0.0.1", "::1"} or origin_port != self.server.server_port or parts.hostname != host):
            self._api_error(403, "a same-origin HTTP request is required", "REQUEST_FORBIDDEN")
            return False
        host_port = raw_host.rsplit(":", 1)[1] if raw_host.count(":") == 1 else (raw_host.split("]", 1)[1][1:] if raw_host.startswith("[") and "]" in raw_host and raw_host.split("]", 1)[1].startswith(":") else "")
        if host_port != str(self.server.server_port):
            self._api_error(403, "Host does not match this local server", "REQUEST_FORBIDDEN")
            return False
        return True

    def _cookies(self) -> SimpleCookie:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except Exception:
            return SimpleCookie()
        return jar

    def _session_id(self) -> str | None:
        morsel = self._cookies().get(auth.COOKIE_NAME)
        return morsel.value if morsel else None

    def _set_cookie(self, name: str, value: str, *, max_age: int | None = None, clear: bool = False) -> None:
        cookie = f"{name}={value}; Path=/; HttpOnly; SameSite=Strict"
        if max_age is not None:
            cookie += f"; Max-Age={0 if clear else max_age}"
        self._pending_cookies.append(cookie)

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for cookie in getattr(self, "_pending_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _api_error(self, status: int, message: str, code: str) -> None:
        self._json(status, {"error": message, "code": code})

    def _read_json(self, *, max_bytes: int = _ORDINARY_JSON_LIMIT) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > max_bytes:
            raise ElasticsearchError("요청 본문이 허용된 크기를 초과했습니다.")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ElasticsearchError("요청 본문이 올바른 JSON이 아닙니다.") from None
        if not isinstance(value, dict):
            raise ElasticsearchError("요청 본문은 JSON object여야 합니다.")
        return value

    @staticmethod
    def _connection(payload: dict[str, Any]) -> Connection:
        value = payload.get("connection") or {}
        if not isinstance(value, dict):
            raise ElasticsearchError("connection 값이 올바르지 않습니다.")
        return Connection.from_payload(value)

    @staticmethod
    def _index(payload: dict[str, Any]) -> str:
        return validate_index(payload.get("index", "jira-grpc-issues"))

    @staticmethod
    def _boosts(payload: dict[str, Any]) -> dict[str, float]:
        source = payload.get("boosts") or evaluation.DEFAULT_PROFILE
        if not isinstance(source, dict):
            raise ElasticsearchError("boosts 값이 올바르지 않습니다.")
        result: dict[str, float] = {}
        for field, value in source.items():
            if field not in evaluation.DEFAULT_PROFILE:
                raise ElasticsearchError(f"지원하지 않는 검색 필드입니다: {field}")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ElasticsearchError(f"필드 가중치는 숫자여야 합니다: {field}") from None
            if number < 0 or number > 100:
                raise ElasticsearchError(f"필드 가중치는 0~100 사이여야 합니다: {field}")
            result[str(field)] = number
        return result

    @staticmethod
    def _filters(payload: dict[str, Any]) -> list[dict[str, str]]:
        values = payload.get("filters") or []
        if not isinstance(values, list):
            raise ElasticsearchError("filters 값은 배열이어야 합니다.")
        return [{"field": str(item.get("field", "")), "value": str(item.get("value", ""))}
                for item in values if isinstance(item, dict)]

    def do_GET(self) -> None:
        self._pending_cookies = []
        try:
            self._handle_get()
        except auth.AuthError as exc:
            self._api_error(exc.status, str(exc), _error_code(exc.status, "AUTH"))
        except storage.SchemaError:
            self._api_error(503, "로컬 데이터베이스 형식을 확인할 수 없습니다. 데이터를 변경하지 않았습니다.", "STORAGE_SCHEMA_INVALID")
        except sqlite3.Error:
            self._api_error(500, "로컬 저장소 작업을 완료하지 못했습니다. 저장 상태를 확인하세요.", "STORAGE_ERROR")
        except Exception:
            self._api_error(500, "내부 오류가 발생했습니다. 요청의 민감한 내용은 오류 응답에 포함되지 않습니다.", "INTERNAL_ERROR")

    def _handle_get(self) -> None:
        self._pending_cookies = []
        if not self._guard_local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(200, {"ok": True, "version": __version__})
            return
        if path == "/api/auth/session":
            nonce = secrets.token_urlsafe(24)
            self._set_cookie("es_rag_login_nonce", nonce, max_age=600)
            user = auth.authenticate(self._session_id())
            configured = auth.is_configured()
            if user:
                self._json(200, {"configured": True, "authenticated": True, "user": user, "csrf_token": auth.csrf_token(self._session_id() or "")})
            else:
                response = {"configured": configured, "authenticated": False}
                if configured:
                    response["csrf_token"] = auth.login_nonce_token(nonce)
                self._json(200, response)
            return
        if path.startswith("/api/") and path not in {"/api/health"}:
            user = auth.authenticate(self._session_id())
            if not user:
                self._api_error(401, "Authentication required", "AUTH_REQUIRED")
                return
            with concepts.owner_scope(user["id"]):
                self._do_get_protected(path)
            return
        self._do_get_public(path)

    def _do_get_public(self, path: str) -> None:
        file_path = STATIC_FILES.get(path)
        if file_path and file_path.is_file():
            data = file_path.read_bytes()
            mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", f"{mime}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self._api_error(404, "경로를 찾을 수 없습니다.", "NOT_FOUND")

    def _do_get_protected(self, path: str) -> None:
        if path == "/api/embedding/profiles":
            default_profile_id = embeddings.profile_spec()["profile_id"]
            profiles = []
            for profile in embeddings.list_profiles():
                profile_id = profile["profile_id"]
                runtime = embeddings.runtime_status(profile_id)
                spec = embeddings.profile_spec(profile_id)
                recipe = embeddings.profile_recipe(profile_id)
                try:
                    tokenizer_version = importlib.metadata.version("tokenizers")
                except importlib.metadata.PackageNotFoundError:
                    tokenizer_version = None
                profiles.append({
                    "profile_id": profile_id,
                    "model_name": spec["model_name"],
                    "source_repo": spec.get("source_repo"),
                    "source_revision": runtime.get("source_revision", spec.get("source_revision")),
                    "fastembed_version": spec.get("fastembed_version"),
                    "dimensions": spec["dimensions"],
                    "similarity": spec.get("similarity"),
                    "query_prefix": spec.get("query_prefix", ""),
                    "passage_prefix": spec.get("passage_prefix", ""),
                    "max_tokens": spec.get("max_tokens", spec.get("context_tokens")),
                    "normalized": spec.get("normalized"),
                    "tokenizer_runtime_installed": importlib.util.find_spec("tokenizers") is not None,
                    "tokenizer_runtime_version": tokenizer_version,
                    "license": spec.get("license"),
                    "recipe": recipe,
                    "recipe_fingerprint": recipe["recipe_fingerprint"],
                    "runtime_installed": runtime.get("runtime_installed", False),
                    "model_cached": runtime.get("model_cached", False),
                    "setup_state": runtime.get("setup_state", runtime.get("status", "unavailable")),
                    "safe_message": runtime.get("safe_message") or {
                        "cached": "로컬 모델이 준비되었습니다.",
                        "model_not_cached": "모델이 캐시에 없습니다. 명시적으로 준비한 뒤 다시 시도하세요.",
                        "dependency_missing": "FastEmbed 런타임이 없습니다. semantic extra를 설치하세요.",
                        "loading_failure": "로컬 모델을 불러오지 못했습니다. 설치와 캐시 상태를 확인하세요.",
                    }.get(runtime.get("status"), "프로필 상태를 확인할 수 없습니다."),
                })
            self._json(200, {"default_profile_id": default_profile_id, "profiles": profiles})
        elif path == "/api/knowledge/es-status":
            try:
                self._json(200, knowledge.es_status())
            except Exception:
                self._api_error(503, "Private knowledge sync status is temporarily unavailable.", "KNOWLEDGE_UNAVAILABLE")
        elif path == "/api/token-preview/status":
            self._json(200, _public_token_preview_result(token_preview.status()))
        elif path == "/api/reranker/status":
            self._json(200, local_reranker.status())
        elif path == "/api/codebase-status":
            try:
                self._json(200, codebase.status())
            except codebase.CodebaseError as exc:
                self._api_error(503, "코드베이스 기능을 사용할 수 없습니다. 설정을 확인한 뒤 다시 시도하세요.", "DEPENDENCY_UNAVAILABLE")
        else:
            self._api_error(404, "경로를 찾을 수 없습니다.", "NOT_FOUND")

    def do_POST(self) -> None:
        self._pending_cookies = []
        if not self._guard_local_request(require_origin=True):
            return
        try:
            path = urlsplit(self.path).path
            session_id = self._session_id()
            max_bytes = _ORDINARY_JSON_LIMIT
            content_length = int(self.headers.get("Content-Length", "0"))
            if path in {"/api/knowledge/restore/preview", "/api/knowledge/restore/commit"} and content_length > _ORDINARY_JSON_LIMIT:
                restore_user = auth.authenticate(session_id)
                if not restore_user:
                    raise auth.AuthError("Authentication required", 401)
                if not auth.verify_csrf(session_id, self.headers.get("X-CSRF-Token")):
                    raise auth.AuthError("CSRF validation failed", 403)
                max_bytes = _RESTORE_JSON_LIMIT
            if path == "/api/evaluation/datasets/import" and content_length > _ORDINARY_JSON_LIMIT:
                import_user = auth.authenticate(session_id)
                if not import_user:
                    raise auth.AuthError("Authentication required", 401)
                if not auth.verify_csrf(session_id, self.headers.get("X-CSRF-Token")):
                    raise auth.AuthError("CSRF validation failed", 403)
                max_bytes = _DATASET_JSON_LIMIT
            payload = self._read_json(max_bytes=max_bytes)
            if path == "/api/auth/login":
                nonce = self._cookies().get("es_rag_login_nonce")
                if not auth.is_configured():
                    raise auth.AuthError("Initial administrator is not configured", 503)
                if not auth.verify_login_csrf(nonce.value if nonce else None, self.headers.get("X-CSRF-Token")):
                    raise auth.AuthError("CSRF validation failed", 403)
                user, new_session, csrf = auth.login(payload.get("username", ""), payload.get("password", ""))
                self._set_cookie(auth.COOKIE_NAME, new_session, max_age=auth.SESSION_TTL_SECONDS)
                self._set_cookie("es_rag_login_nonce", "", max_age=0, clear=True)
                self._json(200, {"configured": True, "authenticated": True, "user": user, "csrf_token": csrf})
                return
            user = auth.authenticate(session_id)
            if not user:
                raise auth.AuthError("Authentication required", 401)
            self._owner_id = user["id"]
            if not auth.verify_csrf(session_id, self.headers.get("X-CSRF-Token")):
                raise auth.AuthError("CSRF validation failed", 403)
            if path == "/api/auth/logout":
                auth.logout(session_id)
                self._set_cookie(auth.COOKIE_NAME, "", max_age=0, clear=True)
                self._json(200, {"authenticated": False})
                return
            if path == "/api/auth/password/change":
                auth.change_password(user["id"], payload.get("current_password", ""), payload.get("new_password", ""))
                self._set_cookie(auth.COOKIE_NAME, "", max_age=0, clear=True)
                self._json(200, {"changed": True, "authenticated": False})
                return
            if path.startswith("/api/admin/accounts/"):
                if user["role"] != "admin":
                    raise auth.AuthError("Administrator role required", 403)
                self._admin_accounts(path, payload)
                return
            handler = post_routes.resolve_post(self, path)
            if not handler:
                self._api_error(404, "API 경로를 찾을 수 없습니다.", "NOT_FOUND")
                return
            with concepts.owner_scope(user["id"]):
                self._json(200, handler(payload))
        except auth.AuthError as exc:
            self._api_error(exc.status, str(exc), _error_code(exc.status, "AUTH"))
        except storage.SchemaError:
            self._api_error(503, "로컬 데이터베이스 형식을 확인할 수 없습니다. 데이터를 변경하지 않았습니다.", "STORAGE_SCHEMA_INVALID")
        except knowledge.KnowledgeError as exc:
            self._api_error(exc.status, str(exc), _error_code(exc.status, "KNOWLEDGE"))
        except ElasticsearchError as exc:
            status = exc.status or 400
            self._api_error(status, _safe_domain_message(exc), _error_code(status, "RETRIEVAL"))
        except codebase.CodebaseError as exc:
            self._api_error(503, "코드베이스 기능을 사용할 수 없습니다. 설정을 확인한 뒤 다시 시도하세요.", "DEPENDENCY_UNAVAILABLE")
        except sqlite3.Error:
            self._api_error(500, "로컬 저장소 작업을 완료하지 못했습니다. 저장 상태를 확인하세요.", "STORAGE_ERROR")
        except (OSError, ValueError, TypeError, KeyError):
            self._api_error(400, "요청을 처리할 수 없습니다. 입력값을 확인하세요.", "INVALID_REQUEST")
        except Exception:  # Never send implementation details to the browser.
            self._api_error(500, "내부 오류가 발생했습니다. 로그에 민감한 요청 내용은 기록되지 않습니다.", "INTERNAL_ERROR")

    def _admin_accounts(self, path: str, payload: dict[str, Any]) -> None:
        if path == "/api/admin/accounts/list":
            self._json(200, {"accounts": auth.list_accounts()})
        elif path == "/api/admin/accounts/create":
            account = auth.create_account(payload.get("username", ""), payload.get("display_name", ""), payload.get("password", ""))
            self._json(201, {"account": account})
        elif path == "/api/admin/accounts/update":
            account = auth.update_account(payload.get("user_id", ""), payload.get("display_name", ""))
            self._json(200, {"account": account})
        elif path == "/api/admin/accounts/password/reset":
            auth.admin_reset_password(self._owner_id, payload.get("user_id", ""), payload.get("new_password", ""))
            self._json(200, {"reset": True})
        elif path == "/api/admin/accounts/disable":
            if "disabled" in payload and payload["disabled"] is not True:
                raise auth.AuthError("disabled must be true when provided")
            auth.disable_account(payload.get("user_id", ""))
            self._json(200, {"disabled": True})
        else:
            self._api_error(404, "API path not found", "NOT_FOUND")

    def _connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        profile_id = payload.get("profile_id")
        profile_spec = embeddings.profile_spec(profile_id)
        profile_recipe = embeddings.profile_recipe(profile_id)
        root = request(connection, "GET", "")
        try:
            indices = list_indices(connection)
            indices_error = None
        except ElasticsearchError as exc:
            indices = []
            indices_error = _safe_domain_message(exc)
        index = self._index(payload)
        exists = index_exists(connection, index)
        count = count_documents(connection, index) if exists else 0
        embedding_status = embeddings.runtime_status(profile_id)
        has_embedding_mapping = False
        vector_count = 0
        embedding_dimensions = None
        mapping_compatible = None
        mapping_error = None
        if exists:
            try:
                raw_mapping = vector_mapping(connection, index, require_dimensions=False)
                has_embedding_mapping = True
                embedding_dimensions = raw_mapping.get("dims")
                vector_count = count_vectors(connection, index)
                try:
                    mapping = vector_mapping(
                        connection,
                        index,
                        profile_id=profile_id,
                        allow_untagged_empty_profile=vector_count == 0,
                    )
                    embedding_dimensions = mapping.get("dims")
                    mapping_compatible = True
                except ElasticsearchError as exc:
                    if exc.status != 409:
                        raise
                    mapping_error = _safe_domain_message(exc)
                    mapping_compatible = False
            except ElasticsearchError as exc:
                if "dense_vector 형식의 rag_embedding" not in str(exc):
                    raise
                else:
                    mapping_compatible = False
        return {
            "cluster_name": root.get("cluster_name", ""),
            "version": root.get("version", {}).get("number", "unknown"),
            "tagline": root.get("tagline", ""),
            "indices": indices,
            "indices_error": indices_error,
            "selected_index": index,
            "selected_index_exists": exists,
            "selected_index_count": count,
            "sample_expected_count": _expected_sample_count(),
            "sample_data_metadata_count": json.loads(evaluation.CONFIG_PATH.read_text(encoding="utf-8")).get("metadata", {}).get("total_documents"),
            "embedding": {
                **embedding_status,
                "profile_id": profile_spec["profile_id"],
                "profile_recipe": profile_recipe,
                "mapping_available": has_embedding_mapping,
                "mapping_compatible": mapping_compatible if mapping_compatible is not None else has_embedding_mapping,
                "mapping_error": mapping_error,
                "mapping_dimensions": embedding_dimensions,
                "vector_count": vector_count,
                "document_count": count,
            },
        }

    def _sample_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        exists = index_exists(connection, index)
        count = count_documents(connection, index) if exists else 0
        return {
            "index": index,
            "exists": exists,
            "document_count": count,
            "sample_expected_count": _expected_sample_count(),
            "metadata_count": json.loads(evaluation.CONFIG_PATH.read_text(encoding="utf-8")).get("metadata", {}).get("total_documents"),
            "can_import": not exists,
        }

    def _sample_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        requested = self._index(payload)
        sample_index, body = _load_sample_mapping()
        index = requested
        if index_exists(connection, index):
            return {
                "created": False,
                "index": index,
                "document_count": count_documents(connection, index),
                "message": "기존 인덱스는 덮어쓰지 않았습니다. 현재 인덱스 내용을 유지했습니다.",
            }
        mapping_body = body
        dense_vector_omitted = False
        try:
            request(connection, "PUT", quote(index, safe=""), mapping_body)
        except ElasticsearchError as exc:
            properties = body.get("mappings", {}).get("properties", {})
            embedding_mapping = properties.get("rag_embedding", {})
            unsupported_dense_vector = (
                embedding_mapping.get("type") == "dense_vector"
                and "No handler for type [dense_vector]" in str(exc)
            )
            if not unsupported_dense_vector:
                raise
            # Older OSS distributions can reject this mapping type. The sample
            # corpus has no embedding values, so preserve lexical search while
            # leaving the attached source mapping untouched.
            if index_exists(connection, index):
                raise ElasticsearchError(
                    "dense_vector 호환 재시도 전에 인덱스가 생성되었습니다. 기존 상태를 보존했습니다."
                ) from None
            mapping_body = {
                **body,
                "mappings": {
                    **body.get("mappings", {}),
                    "properties": {
                        field: definition
                        for field, definition in properties.items()
                        if field != "rag_embedding"
                    },
                },
            }
            request(connection, "PUT", quote(index, safe=""), mapping_body)
            dense_vector_omitted = True
        source_lines = evaluation.BULK_PATH.read_text(encoding="utf-8").splitlines()
        bulk_lines = []
        for line in source_lines:
            if line.startswith('{"index":'):
                action = json.loads(line)
                action["index"]["_index"] = index
                bulk_lines.append(json.dumps(action, ensure_ascii=False, separators=(",", ":")))
            else:
                bulk_lines.append(line)
        raw_bulk = "\n".join(bulk_lines) + "\n"
        bulk = request(
            connection,
            "POST",
            f"{quote(index, safe='')}/_bulk?refresh=false",
            raw_bulk,
            content_type="application/x-ndjson",
            timeout=90,
        )
        if bulk.get("errors"):
            failures = _sample_bulk_failures(bulk.get("items", []))
            try:
                partial_count = count_documents(connection, index)
            except ElasticsearchError:
                partial_count = None
            return {
                "created": True,
                "index": index,
                "partial": True,
                "document_count": partial_count,
                "failed_items": failures,
                "message": "일부 문서 적재가 실패했습니다. 생성된 인덱스와 성공 문서는 유지했습니다.",
            }
        request(connection, "POST", f"{quote(index, safe='')}/_refresh")
        return {
            "created": True,
            "index": index,
            "document_count": count_documents(connection, index),
            "bulk_took_ms": bulk.get("took"),
            "message": (
                "샘플 데이터를 적재했습니다. 이 Elasticsearch 배포판은 dense_vector 매핑을 지원하지 않아 rag_embedding 필드를 제외했습니다."
                if dense_vector_omitted else "샘플 데이터를 적재했습니다."
            ),
            "dense_vector_mapping_omitted": dense_vector_omitted,
            "mapping_index_name_in_attachment": sample_index,
            "attachment_metadata_count": json.loads(evaluation.CONFIG_PATH.read_text(encoding="utf-8")).get("metadata", {}).get("total_documents"),
        }

    def _mapping(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        profile_id = payload.get("profile_id")
        profile_spec = embeddings.profile_spec(profile_id)
        response = request(connection, "GET", f"{quote(index, safe='')}/_mapping")
        if not isinstance(response, dict) or not response:
            raise ElasticsearchError("선택한 인덱스 또는 alias의 구체 인덱스 매핑을 확인할 수 없습니다.")
        properties: dict[str, Any] = {}
        for concrete_index, value in response.items():
            mappings = value.get("mappings", {}) if isinstance(value, dict) else {}
            concrete_properties = mappings.get("properties", {}) if isinstance(mappings, dict) else {}
            if not isinstance(concrete_properties, dict):
                raise ElasticsearchError(f"{concrete_index}의 매핑 properties 응답 형식이 올바르지 않습니다.")
            for name, definition in concrete_properties.items():
                if not isinstance(definition, dict):
                    raise ElasticsearchError(f"{concrete_index}의 {name} 매핑 응답 형식이 올바르지 않습니다.")
                if name in properties and properties[name] != definition:
                    # Conflicting alias mappings cannot be represented as one
                    # safe mapping; the UI may display the name but must not
                    # treat either definition as authoritative.
                    properties[name] = {"type": "mapping_conflict"}
                else:
                    properties[name] = definition
        try:
            vector_mapping_targets(connection, index, require_dimensions=False)
            vector_available = True
        except ElasticsearchError:
            vector_available = False
        return {
            "index": index,
            "properties": properties,
            "fields": sorted(properties.keys()),
            "has_rag_embedding_mapping": vector_available,
            "profile_id": profile_spec["profile_id"],
            "profile_dimensions": profile_spec["dimensions"],
        }

    def _vectorize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return vectorize_index(self._connection(payload), self._index(payload), payload.get("profile_id"))

    def _reranker_prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        return local_reranker.prepare(payload.get("consent"))

    def _search(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        query_text = str(payload.get("query", "")).strip()
        if not query_text:
            raise ElasticsearchError("검색어를 입력하세요.")
        if len(query_text) > 4000:
            raise ElasticsearchError("검색어는 4000자 이하로 입력하세요.")
        size = payload.get("size", 10)
        if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 50:
            raise ElasticsearchError("결과 개수는 1~50 사이 정수여야 합니다.")
        candidate_pool = payload.get("candidate_pool", size)
        if not isinstance(candidate_pool, int) or isinstance(candidate_pool, bool) or not size <= candidate_pool <= 200:
            raise ElasticsearchError("candidate_pool은 top-K 이상 200 이하 정수여야 합니다.")
        rerank = payload.get("rerank", False)
        if not isinstance(rerank, bool):
            raise ElasticsearchError("rerank 값은 boolean이어야 합니다.")
        boosts = self._boosts(payload)
        filters = self._filters(payload)
        mode = str(payload.get("mode", "bm25")).strip().lower()
        rank_constant = payload.get("rank_constant", 60)
        if not isinstance(rank_constant, int) or isinstance(rank_constant, bool) or not 1 <= rank_constant <= 200:
            raise ElasticsearchError("RRF rank constant는 1~200 사이 정수여야 합니다.")
        if mode in {"vector", "hybrid"}:
            # Reject account-private aliases before the shared-lane fallback:
            # the client-side index is untrusted and the request guard remains
            # the second line of defense on every actual ES request.
            guard_shared_index_access(index)
            for item in filters:
                if item["value"] and item["field"] not in FILTER_FIELDS:
                    raise ElasticsearchError(f"필터를 지원하지 않는 필드입니다: {item['field']}")
            try:
                result = retrieve(
                    connection, index, query_text, size, boosts, filters,
                    mode=mode, rank_constant=rank_constant, source_fields=DISPLAY_FIELDS,
                    profile_id=payload.get("profile_id"),
                    candidate_pool=candidate_pool, rerank=rerank,
                )
                result["shared_search"] = {"state": "available"}
            except PrivateIndexAccessError:
                raise
            except ElasticsearchError as exc:
                if rerank:
                    raise
                if not _shared_vector_failure_is_unavailable(exc):
                    raise
                # Shared vector readiness is independent of the account-private
                # lane. Keep its failure safe and continue to the private query.
                result = {"mode": mode, "query": {"mode": mode, "rank_constant": rank_constant}, "total": 0, "took_ms": None, "hits": [],
                          "shared_search": {"state": "unavailable", "message": "공유 인덱스의 벡터 검색을 사용할 수 없습니다. 연결, 매핑, 벡터 상태를 확인하세요. 비공개 lane 검색은 계속 시도했습니다."}}
        else:
            result = retrieve(
                connection,
                index,
                query_text,
                size,
                boosts,
                filters,
                mode=mode,
                rank_constant=rank_constant,
                source_fields=DISPLAY_FIELDS,
                profile_id=payload.get("profile_id"),
                candidate_pool=candidate_pool, rerank=rerank,
            )
        try:
            private = knowledge.search_es_mode(connection, query_text, mode, size, payload.get("profile_id"))
        except Exception:
            private = {"state": "unavailable", "mode": mode, "results": [], "message": "내 비공개 지식 검색을 준비할 수 없습니다. 공유 결과는 유지했으며 비공개 검색은 숨겼습니다. 내 지식 화면에서 모델, 매핑, 동기화 상태를 확인하세요."}
        result["private_knowledge"] = private
        return result

    def _code_rag(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        query_text = str(payload.get("query", "")).strip()
        if not query_text:
            raise ElasticsearchError("검색어를 입력하세요.")
        if len(query_text) > 4000:
            raise ElasticsearchError("검색어는 4000자 이하로 입력하세요.")
        size = payload.get("size", 10)
        if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 50:
            raise ElasticsearchError("결과 개수는 1~50 사이 정수여야 합니다.")
        candidate_pool = payload.get("candidate_pool", size)
        if not isinstance(candidate_pool, int) or isinstance(candidate_pool, bool) or not size <= candidate_pool <= 200:
            raise ElasticsearchError("candidate_pool은 top-K 이상 200 이하 정수여야 합니다.")
        rank_constant = payload.get("rank_constant", 60)
        if not isinstance(rank_constant, int) or isinstance(rank_constant, bool) or not 1 <= rank_constant <= 200:
            raise ElasticsearchError("RRF rank constant는 1~200 사이 정수여야 합니다.")
        rerank = payload.get("rerank", False)
        if not isinstance(rerank, bool):
            raise ElasticsearchError("rerank 값은 boolean이어야 합니다.")
        guard_shared_index_access(index)
        boosts = self._boosts(payload)
        filters = self._filters(payload)
        issues = retrieve(
            connection,
            index,
            query_text,
            size,
            boosts,
            filters,
            mode="hybrid",
            rank_constant=rank_constant,
            source_fields=DISPLAY_FIELDS,
            profile_id=payload.get("profile_id"),
            candidate_pool=candidate_pool,
            rerank=rerank,
        )
        code = codebase.search(query_text, issues.get("hits", []), size)
        return {
            "mode": "code_rag",
            "query": query_text,
            "answer": codebase.compose_answer(issues, code),
            "issues": issues,
            "code": code,
        }

    def _explain(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        document_id = str(payload.get("id", "")).strip()
        query_text = str(payload.get("query", "")).strip()
        if not document_id or not query_text:
            raise ElasticsearchError("문서 ID와 설명할 검색어가 필요합니다.")
        query = build_search_query(
            query_text, self._boosts(payload), self._filters(payload), include_inner_hits=False
        )
        result = request(
            connection,
            "POST",
            f"{quote(index, safe='')}/_explain/{quote(document_id, safe='')}",
            {"query": query},
        )
        return result

    def _document(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        document_id = str(payload.get("id", "")).strip()
        if not document_id:
            raise ElasticsearchError("문서 ID가 필요합니다.")
        result = request(connection, "GET", f"{quote(index, safe='')}/_doc/{quote(document_id, safe='')}")
        result["embedding_input"] = embeddings.passage_input(result.get("_source", {}))
        return result

    @staticmethod
    def _token_preview(payload: dict[str, Any]) -> dict[str, Any]:
        input_text = payload.get("input_text")
        if not isinstance(input_text, str):
            raise ElasticsearchError("input_text는 문자열이어야 합니다.")
        return _public_token_preview_result(token_preview.preview_input(input_text))

    @staticmethod
    def _token_preview_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        # The request deliberately has no model, repository, revision, filename,
        # or document-text parameters. Preparation is an explicit local action.
        if payload:
            raise ElasticsearchError("토크나이저 준비 요청 본문은 빈 object여야 합니다.")
        return _public_token_preview_result(token_preview.prepare())

    def _evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        mode = str(payload.get("mode", "bm25")).strip().lower()
        try:
            rank_constant = int(payload.get("rank_constant", 60))
        except (TypeError, ValueError):
            raise ElasticsearchError("RRF rank constant는 정수여야 합니다.") from None
        return evaluation.evaluate(connection, index, self._boosts(payload), mode, rank_constant)

    def _tune(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        try:
            passes = int(payload.get("passes", 2))
        except (TypeError, ValueError):
            raise ElasticsearchError("반복 횟수는 정수여야 합니다.") from None
        return evaluation.tune(connection, index, self._boosts(payload), passes)

    def _concept_schema(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.corpus_schema(self._connection(payload), self._index(payload))

    def _concept_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.list_concepts()

    def _concept_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.save_concept(payload.get("concept"))

    def _concept_quickstart(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.quickstart(self._connection(payload), self._index(payload), str(payload.get("query", "")))

    def _concept_ensure_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.ensure_query(str(payload.get("concept_id", "")), str(payload.get("query", "")), str(payload.get("split", "train")))

    def _concept_diagnose(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.diagnose(
            self._connection(payload), payload.get("concept"), str(payload.get("query", "")),
            str(payload.get("query_id", "")), str(payload.get("document_index", "")),
            str(payload.get("document_id", "")),
        )

    def _concept_versions(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.list_versions(str(payload.get("concept_id", "")), payload.get("limit", 50))

    def _concept_restore(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.restore_version(str(payload.get("concept_id", "")), str(payload.get("version_id", "")))

    def _concept_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.export_profile(self._connection(payload), str(payload.get("concept_id", "")), str(payload.get("version_id", "")))

    def _concept_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.preview(
            self._connection(payload), payload.get("concept"),
            str(payload.get("query", "")), str(payload.get("query_id", "")),
            payload.get("filters"),
        )

    def _concept_information_need_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.information_need_preview(
            self._connection(payload),
            str(payload.get("concept_id", "")),
            str(payload.get("query_id", "")),
        )

    def _concept_vector_candidates(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.vector_candidates(
            self._connection(payload), str(payload.get("concept_id", "")), str(payload.get("query_id", "")),
            payload.get("profile_id"),
        )

    def _concept_mode_comparison(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.mode_comparison(
            self._connection(payload), str(payload.get("concept_id", "")), str(payload.get("query_id", "")),
            payload.get("profile_id"),
        )

    def _concept_mode_comparison_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.mode_comparison_group(
            self._connection(payload), str(payload.get("concept_id", "")), str(payload.get("query_id", "")),
            payload.get("profile_id"),
        )

    def _concept_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        raw_document_id = payload.get("document_id")
        if not isinstance(raw_document_id, (str, int)) or isinstance(raw_document_id, bool):
            raise ElasticsearchError("document_id는 문자열 또는 정수여야 합니다.")
        document_id = str(raw_document_id)
        if not document_id or len(document_id.encode("utf-8")) > 512:
            raise ElasticsearchError("document_id는 UTF-8 기준 1~512 bytes여야 합니다.")
        result = request(connection, "GET", f"{quote(index, safe='')}/_doc/{quote(document_id, safe='')}")
        if not result.get("found", True):
            raise ElasticsearchError("해당 인덱스에서 문서를 찾을 수 없습니다.", 404)
        return {"document_index": str(result.get("_index", index)), "document_id": str(result.get("_id", document_id)), "source": result.get("_source", {})}

    def _concept_locate_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.locate_document(
            self._connection(payload),
            str(payload.get("concept_id", "")),
            payload.get("text", ""),
        )

    def _concept_judge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.save_judgment(payload)

    def _concept_tune(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.tune(self._connection(payload), payload.get("concept"), payload.get("passes", 2))

    def _concept_tune_readiness(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.tune_readiness(payload.get("concept"))

    def _concept_runs(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.list_runs(str(payload.get("concept_id", "")).strip(), payload.get("limit", 50))

    def _concept_run_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.export_run(str(payload.get("concept_id", "")), str(payload.get("run_id", "")))

    def _evaluation_dataset_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.create_dataset(
            payload.get("name"), payload.get("provenance"), payload.get("queries"), payload.get("qrels"),
            payload.get("unjudged_policy", "judged_only"), payload.get("qrels_complete", False),
        )

    def _evaluation_dataset_version_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.create_version(
            payload.get("dataset_id"), payload.get("base_version_id"), payload.get("name"),
            payload.get("provenance"), payload.get("queries"), payload.get("qrels"),
            payload.get("unjudged_policy", "judged_only"), payload.get("qrels_complete", False),
        )

    @staticmethod
    def _evaluation_dataset_import(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.import_dataset(payload.get("format"), payload.get("content"))

    @staticmethod
    def _evaluation_dataset_list(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.list_datasets(str(payload.get("dataset_id", "")))

    @staticmethod
    def _evaluation_dataset_detail(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.get_dataset_version(payload.get("dataset_id"), payload.get("version_id"))

    @staticmethod
    def _evaluation_dataset_export(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.export_dataset(payload.get("dataset_id"), payload.get("version_id"), payload.get("format"))

    def _evaluation_dataset_evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.evaluate(
            self._connection(payload), payload.get("index", ""), payload.get("dataset_id"),
            payload.get("version_id"), payload.get("split"), payload.get("mode", "bm25"),
            payload.get("settings", {}), payload.get("cutoff"), payload.get("configuration_frozen", False),
        )

    @staticmethod
    def _evaluation_runs_list(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.list_runs(payload.get("dataset_id"), payload.get("version_id"))

    @staticmethod
    def _evaluation_run_export(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.export_run(payload.get("dataset_id"), payload.get("version_id"), payload.get("run_id"))

    @staticmethod
    def _evaluation_runs_compare(payload: dict[str, Any]) -> dict[str, Any]:
        return evaluation_datasets.compare_runs(payload.get("dataset_id"), payload.get("version_id"),
                                                payload.get("left_run_id"), payload.get("right_run_id"))

    def _ai_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ai_coach.status()

    def _ai_create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ai_coach.create_session(
            str(payload.get("provider", "")), str(payload.get("model", "")),
            self._connection(payload), payload.get("corpus", {}), str(payload.get("concept_id", "")), owner_id=self._owner_id,
        )

    def _ai_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ai_coach.submit_message(
            str(payload.get("session_id", "")), self._connection(payload),
            str(payload.get("message", "")), payload.get("context", {}), owner_id=self._owner_id,
        )

    def _ai_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ai_coach.history(str(payload.get("session_id", "")), payload.get("limit", 20), owner_id=self._owner_id)

    def _ai_reset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ai_coach.reset_session(str(payload.get("session_id", "")), owner_id=self._owner_id)

    def _ai_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ai_coach.get_job(str(payload.get("job_id", "")), owner_id=self._owner_id)

    def _ai_cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        return ai_coach.cancel_job(str(payload.get("job_id", "")), owner_id=self._owner_id)


def main() -> None:
    import getpass
    import sys

    if sys.argv[1:3] == ["auth", "bootstrap-admin"]:
        username = input("Administrator username: ").strip()
        display_name = input("Display name: ").strip()
        password = getpass.getpass("Password (minimum 15 characters): ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("Passwords do not match.")
        try:
            user = auth.bootstrap_admin(username, display_name, password)
        except auth.AuthError as exc:
            raise SystemExit(str(exc)) from None
        print(f"Initial administrator configured for {user['username']}.")
        return
    if sys.argv[1:3] == ["auth", "reset-admin-password"]:
        username = input("Enabled administrator username: ").strip()
        password = getpass.getpass("New password (minimum 15 characters): ")
        confirmation = getpass.getpass("Confirm new password: ")
        if password != confirmation:
            raise SystemExit("Passwords do not match.")
        try:
            auth.reset_admin_password(username, password)
        except auth.AuthError as exc:
            raise SystemExit(str(exc)) from None
        print(f"Administrator password reset for {username.strip().lower()}; prior sessions were revoked.")
        return
    if sys.argv[1:2] in (["db-backup"], ["db-restore"]):
        from .db_maintenance import MaintenanceError, backup_database, restore_database

        command = sys.argv[1]
        maintenance_parser = argparse.ArgumentParser(description="Offline local SQLite maintenance")
        maintenance_parser.add_argument("--source", required=True, help="explicit source SQLite file")
        maintenance_parser.add_argument("--destination", required=True, help="explicit destination SQLite file")
        if command == "db-restore":
            maintenance_parser.add_argument("--offline-confirmed", action="store_true", help="confirm the workbench process is stopped")
        maintenance_args = maintenance_parser.parse_args(sys.argv[2:])
        try:
            if command == "db-backup":
                backup_database(maintenance_args.source, maintenance_args.destination)
                print("Verified SQLite backup created.")
            else:
                restore_database(maintenance_args.source, maintenance_args.destination, offline_confirmed=maintenance_args.offline_confirmed)
                print("Verified SQLite database restored.")
        except MaintenanceError as exc:
            raise SystemExit(str(exc)) from None
        return
    parser = argparse.ArgumentParser(description="Local Elasticsearch RAG retrieval tuning workbench")
    parser.add_argument("--host", default="127.0.0.1", help="loopback address only (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("보안상 loopback 주소에서만 실행할 수 있습니다.")
    server = ThreadingHTTPServer((args.host, args.port), WorkbenchHandler)
    server.daemon_threads = True
    print(f"ES RAG Tuning Workbench {__version__} is ready at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
