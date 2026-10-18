"""Loopback-only HTTP server for the retrieval workbench."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from http.cookies import SimpleCookie
import secrets

from . import __version__, codebase
from . import evaluation
from . import embeddings
from . import concepts
from . import ai_coach
from . import token_preview
from . import auth
from . import knowledge
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
    "/style.css": WEB / "style.css",
}
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
            self._json(403, {"error": "이 워크벤치는 loopback에서만 접근할 수 있습니다."})
            return False
        origin = self.headers.get("Origin")
        parts = urlsplit(origin or "")
        try:
            origin_port = parts.port or (80 if parts.scheme == "http" else 443)
        except ValueError:
            origin_port = -1
        if require_origin and (parts.scheme != "http" or parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment or parts.hostname not in {"localhost", "127.0.0.1", "::1"} or origin_port != self.server.server_port or parts.hostname != host):
            self._json(403, {"error": "a same-origin HTTP request is required"})
            return False
        host_port = raw_host.rsplit(":", 1)[1] if raw_host.count(":") == 1 else (raw_host.split("]", 1)[1][1:] if raw_host.startswith("[") and "]" in raw_host and raw_host.split("]", 1)[1].startswith(":") else "")
        if host_port != str(self.server.server_port):
            self._json(403, {"error": "Host does not match this local server"})
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

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 2 * 1024 * 1024:
            raise ElasticsearchError("요청이 너무 큽니다 (최대 2 MiB).")
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
                self._json(401, {"error": "Authentication required"})
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
        self._json(404, {"error": "경로를 찾을 수 없습니다."})

    def _do_get_protected(self, path: str) -> None:
        if path == "/api/knowledge/es-status":
            try:
                self._json(200, knowledge.es_status())
            except Exception:
                self._json(503, {"error": "Private knowledge sync status is temporarily unavailable."})
        elif path == "/api/token-preview/status":
            self._json(200, token_preview.status())
        elif path == "/api/codebase-status":
            try:
                self._json(200, codebase.status())
            except codebase.CodebaseError as exc:
                self._json(503, {"error": _problem_text(exc)})
        else:
            self._json(404, {"error": "경로를 찾을 수 없습니다."})

    def do_POST(self) -> None:
        self._pending_cookies = []
        if not self._guard_local_request(require_origin=True):
            return
        try:
            payload = self._read_json()
            path = urlsplit(self.path).path
            session_id = self._session_id()
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
            handler = {
                "/api/connect": self._connect,
                "/api/sample-info": self._sample_info,
                "/api/sample-import": self._sample_import,
                "/api/vectorize": self._vectorize,
                "/api/mapping": self._mapping,
                "/api/search": self._search,
                "/api/code-rag": self._code_rag,
                "/api/explain": self._explain,
                "/api/document": self._document,
                "/api/token-preview": self._token_preview,
                "/api/token-preview/prepare": self._token_preview_prepare,
                "/api/evaluate": self._evaluate,
                "/api/tune": self._tune,
                "/api/corpus/schema": self._concept_schema,
                "/api/concepts/list": self._concept_list,
                "/api/concepts/save": self._concept_save,
                "/api/concepts/quickstart": self._concept_quickstart,
                "/api/concepts/ensure-query": self._concept_ensure_query,
                "/api/concepts/diagnose": self._concept_diagnose,
                "/api/concepts/versions": self._concept_versions,
                "/api/concepts/restore": self._concept_restore,
                "/api/concepts/export": self._concept_export,
                "/api/concepts/preview": self._concept_preview,
                "/api/concepts/information-need-preview": self._concept_information_need_preview,
                "/api/concepts/vector-candidates": self._concept_vector_candidates,
                "/api/concepts/mode-comparison": self._concept_mode_comparison,
                "/api/concepts/mode-comparison-group": self._concept_mode_comparison_group,
                "/api/concepts/locate-document": self._concept_locate_document,
                "/api/concepts/document": self._concept_document,
                "/api/concepts/judge": self._concept_judge,
                "/api/concepts/tune/readiness": self._concept_tune_readiness,
                "/api/concepts/tune": self._concept_tune,
                "/api/concepts/runs": self._concept_runs,
                "/api/concepts/runs/export": self._concept_run_export,
                "/api/knowledge/list": lambda payload: knowledge.list_documents(),
                "/api/knowledge/preview": knowledge.preview,
                "/api/knowledge/save": knowledge.save_document,
                "/api/knowledge/get": knowledge.get_document,
                "/api/knowledge/delete": knowledge.delete_document,
                "/api/knowledge/search": knowledge.search,
                "/api/knowledge/es-sync": lambda payload: knowledge.sync_es(self._connection(payload)),
                "/api/knowledge/es-vector-sync": lambda payload: knowledge.sync_es(self._connection(payload), vector=True, allow_model_download=payload.get("allow_model_download") is True),
                "/api/knowledge/concept-preview": knowledge.concept_preview,
                "/api/knowledge/judge": knowledge.judge,
                "/api/ai/status": self._ai_status,
                "/api/ai/sessions/create": self._ai_create_session,
                "/api/ai/sessions/message": self._ai_message,
                "/api/ai/sessions/history": self._ai_history,
                "/api/ai/sessions/reset": self._ai_reset,
                "/api/ai/jobs/get": self._ai_job,
                "/api/ai/jobs/cancel": self._ai_cancel,
            }.get(path)
            if not handler:
                self._json(404, {"error": "API 경로를 찾을 수 없습니다."})
                return
            with concepts.owner_scope(user["id"]):
                self._json(200, handler(payload))
        except auth.AuthError as exc:
            self._json(exc.status, {"error": str(exc)})
        except knowledge.KnowledgeError as exc:
            self._json(exc.status, {"error": str(exc)})
        except ElasticsearchError as exc:
            self._json(exc.status or 400, {"error": _problem_text(exc)})
        except codebase.CodebaseError as exc:
            self._json(503, {"error": _problem_text(exc)})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._json(400, {"error": _problem_text(exc)})
        except Exception as exc:  # Keep implementation details out of the local UI.
            self._json(500, {"error": f"내부 오류: {_problem_text(exc)}"})

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
            self._json(404, {"error": "API path not found"})

    def _connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        root = request(connection, "GET", "")
        try:
            indices = list_indices(connection)
            indices_error = None
        except ElasticsearchError as exc:
            indices = []
            indices_error = _problem_text(exc)
        index = self._index(payload)
        exists = index_exists(connection, index)
        count = count_documents(connection, index) if exists else 0
        embedding_status = embeddings.runtime_status()
        has_embedding_mapping = False
        vector_count = 0
        embedding_dimensions = None
        if exists:
            try:
                mapping = vector_mapping(connection, index, require_dimensions=False)
                has_embedding_mapping = True
                embedding_dimensions = mapping.get("dims")
                vector_count = count_vectors(connection, index)
            except ElasticsearchError as exc:
                if "dense_vector 형식의 rag_embedding" not in str(exc):
                    raise
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
                "mapping_available": has_embedding_mapping,
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
            failures = []
            for item in bulk.get("items", []):
                operation = next(iter(item.values()), {})
                if int(operation.get("status", 200)) >= 300:
                    failures.append({"id": operation.get("_id"), "status": operation.get("status"), "error": operation.get("error")})
                if len(failures) >= 10:
                    break
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
        }

    def _vectorize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return vectorize_index(self._connection(payload), self._index(payload))

    def _search(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(payload)
        index = self._index(payload)
        query_text = str(payload.get("query", "")).strip()
        if not query_text:
            raise ElasticsearchError("검색어를 입력하세요.")
        if len(query_text) > 4000:
            raise ElasticsearchError("검색어는 4000자 이하로 입력하세요.")
        try:
            size = max(1, min(int(payload.get("size", 10)), 50))
        except (TypeError, ValueError):
            raise ElasticsearchError("결과 개수는 1~50 사이 정수여야 합니다.") from None
        boosts = self._boosts(payload)
        filters = self._filters(payload)
        mode = str(payload.get("mode", "bm25")).strip().lower()
        try:
            rank_constant = int(payload.get("rank_constant", 60))
        except (TypeError, ValueError):
            raise ElasticsearchError("RRF rank constant는 정수여야 합니다.") from None
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
                )
                result["shared_search"] = {"state": "available"}
            except PrivateIndexAccessError:
                raise
            except ElasticsearchError as exc:
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
            )
        try:
            private = knowledge.search_es_mode(connection, query_text, mode, size)
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
        try:
            size = max(1, min(int(payload.get("size", 5)), 10))
            rank_constant = int(payload.get("rank_constant", 60))
        except (TypeError, ValueError):
            raise ElasticsearchError("결과 개수 또는 RRF rank constant 값이 올바르지 않습니다.") from None
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
        return token_preview.preview_input(input_text)

    @staticmethod
    def _token_preview_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        # The request deliberately has no model, repository, revision, filename,
        # or document-text parameters. Preparation is an explicit local action.
        if payload:
            raise ElasticsearchError("토크나이저 준비 요청 본문은 빈 object여야 합니다.")
        return token_preview.prepare()

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
        )

    def _concept_mode_comparison(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.mode_comparison(
            self._connection(payload), str(payload.get("concept_id", "")), str(payload.get("query_id", "")),
        )

    def _concept_mode_comparison_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        return concepts.mode_comparison_group(
            self._connection(payload), str(payload.get("concept_id", "")), str(payload.get("query_id", "")),
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
