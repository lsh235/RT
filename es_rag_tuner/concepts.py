"""Local persistence and read-only concept retrieval helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from . import embeddings
from . import storage
from .es_client import Connection, ElasticsearchError, request, validate_index, bind_local_owner, reset_local_owner
from .retrieval import count_vectors, vector_mapping_targets

MAX_FIELDS = 20
MAX_TERMS = 100
MAX_QUERY_CASES = 100
MAX_TEXT = 4000
_OWNER_ID: ContextVar[str | None] = ContextVar("es_rag_owner_id", default=None)


@contextmanager
def owner_scope(owner_id: str) -> Iterator[None]:
    """Bind local saved-state access to the authenticated account for this request."""
    if not owner_id:
        raise ElasticsearchError("Authenticated account scope is required", 401)
    token = _OWNER_ID.set(str(owner_id))
    es_token = bind_local_owner(str(owner_id))
    try:
        yield
    finally:
        reset_local_owner(es_token)
        _OWNER_ID.reset(token)


def _db_path() -> Path:
    owner_id = _OWNER_ID.get()
    if owner_id:
        from .auth import state_database_path
        path = state_database_path(owner_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.name.endswith(".accounts"):
            try:
                path.parent.chmod(0o700)
            except OSError:
                pass
        return path
    from .auth import is_configured
    if is_configured():
        raise ElasticsearchError("Authenticated account scope is required", 401)
    configured = os.environ.get("ES_RAG_CONCEPT_DB", "").strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        path = Path.home() / ".local" / "share" / "es-rag-workbench" / "concepts.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _connect_db() -> Iterator[sqlite3.Connection]:
    db_path = _db_path()
    db: sqlite3.Connection | None = None
    try:
        # Serialize file creation/open as well as journal and schema setup.
        # SQLite connections opened simultaneously against a missing file can
        # race while initializing the database header, before a connection
        # level PRAGMA or migration lock can take effect.
        with storage.file_lock_for_path(db_path):
            db = sqlite3.connect(db_path, timeout=30)
            try:
                db_path.chmod(0o600)
            except OSError:
                db.close()
                db = None
                raise
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=30000")
            storage.configure_journal_mode(db)
            # Snapshot and apply versioned schema changes before writing the
            # account ownership marker. Then serialize owner validation.
            storage.migrate(db, "state")
            db.execute("BEGIN IMMEDIATE")
            owner_id = _OWNER_ID.get()
            if owner_id:
                db.execute("CREATE TABLE IF NOT EXISTS state_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner_id TEXT NOT NULL)")
                owner = db.execute("SELECT owner_id FROM state_owner WHERE singleton=1").fetchone()
                if owner and owner["owner_id"] != owner_id:
                    raise ElasticsearchError("Saved-state database owner marker is inconsistent", 503)
                if not owner:
                    db.execute("INSERT INTO state_owner(singleton,owner_id) VALUES(1,?)", (owner_id,))
            db.commit()
        assert db is not None
        yield db
        db.commit()
    except Exception:
        if db is not None:
            db.rollback()
        raise
    finally:
        if db is not None:
            db.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public_failure_message(exc: Exception, fallback: str) -> str:
    if isinstance(exc, ElasticsearchError) and exc.safe_for_user:
        return str(exc).strip()[:1200] or fallback
    return fallback


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _query_judgment_fingerprint(query: dict[str, Any]) -> str:
    """Keep judgments tied to query identity/text/split, not its display group."""
    return _json_hash({key: value for key, value in query.items() if key != "information_need"})


def list_concepts() -> dict[str, Any]:
    with _connect_db() as db:
        rows = db.execute("SELECT body FROM concepts ORDER BY updated_at DESC, id").fetchall()
    return {"concepts": [json.loads(row["body"]) for row in rows], "storage": "sqlite"}


def get_saved_concept(concept_id: str) -> dict[str, Any]:
    """Read and validate one authoritative saved concept from the local store."""
    concept_id = str(concept_id).strip()
    if not concept_id or len(concept_id) > 128:
        raise ElasticsearchError("concept_id 값이 올바르지 않습니다.")
    with _connect_db() as db:
        row = db.execute("SELECT body FROM concepts WHERE id=?", (concept_id,)).fetchone()
    if not row:
        raise ElasticsearchError("저장된 개념을 찾을 수 없습니다.", 404)
    return validate_concept(json.loads(row["body"]))


def information_need_preview(connection: Connection, concept_id: str, query_id: str) -> dict[str, Any]:
    """Preview each saved formulation in one information need independently."""
    concept = get_saved_concept(concept_id)
    selected = next((item for item in concept["queries"] if item["id"] == query_id), None)
    if selected is None:
        raise ElasticsearchError("선택한 저장 질의를 찾을 수 없습니다.", 404)
    need_label = " ".join(selected.get("information_need", "").split())
    if not need_label:
        raise ElasticsearchError("선택한 질의에 정보 요구 묶음이 없습니다.")
    identity = need_label.casefold()
    members = [item for item in concept["queries"] if " ".join(item.get("information_need", "").split()).casefold() == identity]
    if len(members) < 2 or len(members) > 10:
        raise ElasticsearchError("정보 요구 묶음 미리보기는 저장 질의 2~10개가 필요합니다.")
    results, failures = [], []
    for item in members:
        try:
            result = preview(connection, concept, query_id=item["id"])
            results.append({"query_id": item["id"], "query": item["query"], "split": item["split"], "preview": result})
        except ElasticsearchError as exc:
            failures.append({"query_id": item["id"], "query": item["query"], "split": item["split"], "error": _public_failure_message(exc, "이 질의의 미리보기를 완료하지 못했습니다.")})
        except Exception:
            failures.append({"query_id": item["id"], "query": item["query"], "split": item["split"], "error": "이 질의의 미리보기를 완료하지 못했습니다."})
    status = "complete" if not failures else "partial"
    return {"information_need": need_label, "split": selected["split"], "count": len(members), "status": status, "results": results, "failures": failures}


def validate_concept(value: Any, *, assign_id: bool = False, allow_title_outside_text_fields: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ElasticsearchError("concept 값은 JSON object여야 합니다.")
    # Persist only documented fields: request payloads may contain UI-only or
    # credential-like extras and must never leak those into SQLite snapshots.
    allowed = {"id", "name", "description", "aliases", "related", "excluded_terms", "corpus", "filters", "settings", "queries"}
    concept = {key: value[key] for key in allowed if key in value}
    name = str(concept.get("name", "")).strip()
    if not name or len(name) > 200:
        raise ElasticsearchError("개념 이름은 1~200자여야 합니다.")
    concept["name"] = name
    concept["description"] = str(concept.get("description", ""))[:MAX_TEXT]
    raw_id = str(concept.get("id", "")).strip()
    if len(raw_id) > 128:
        raise ElasticsearchError("concept id는 128자 이하여야 합니다.")
    if assign_id and not raw_id:
        concept["id"] = str(uuid.uuid4())
    elif not raw_id:
        concept["id"] = ""
    concept["id"] = raw_id or concept.get("id", "")
    for key in ("aliases", "excluded_terms"):
        items = concept.get(key, [])
        if not isinstance(items, list) or len(items) > MAX_TERMS:
            raise ElasticsearchError(f"{key}는 최대 {MAX_TERMS}개 문자열 배열이어야 합니다.")
        concept[key] = [str(item).strip()[:300] for item in items if str(item).strip()]
    related = concept.get("related", [])
    if not isinstance(related, list) or len(related) > MAX_TERMS:
        raise ElasticsearchError(f"related는 최대 {MAX_TERMS}개 항목이어야 합니다.")
    clean_related = []
    for item in related:
        if not isinstance(item, dict) or not str(item.get("term", "")).strip():
            continue
        try:
            weight = float(item.get("weight", 1))
        except (TypeError, ValueError):
            raise ElasticsearchError("관련 용어 weight는 숫자여야 합니다.") from None
        if not math.isfinite(weight) or not 0 < weight <= 10:
            raise ElasticsearchError("관련 용어 weight는 0 초과 10 이하의 유한한 값이어야 합니다.")
        clean_related.append({"term": str(item["term"]).strip()[:300], "relation": str(item.get("relation", "related"))[:80], "weight": weight})
    concept["related"] = clean_related
    corpus = concept.get("corpus") or {}
    if not isinstance(corpus, dict):
        raise ElasticsearchError("corpus 값이 올바르지 않습니다.")
    corpus = {key: corpus[key] for key in ("index", "title_field", "text_fields", "filter_fields") if key in corpus}
    corpus["index"] = validate_index(corpus.get("index", ""))
    corpus["title_field"] = str(corpus.get("title_field", "")).strip()
    for key in ("text_fields", "filter_fields"):
        values = corpus.get(key, [])
        if not isinstance(values, list) or len(values) > MAX_FIELDS:
            raise ElasticsearchError(f"corpus.{key}는 최대 {MAX_FIELDS}개 필드 배열이어야 합니다.")
        corpus[key] = list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
    if not corpus["text_fields"]:
        raise ElasticsearchError("corpus.text_fields에 검색할 필드를 하나 이상 지정하세요.")
    if corpus["title_field"] and corpus["title_field"] not in corpus["text_fields"] and not allow_title_outside_text_fields:
        raise ElasticsearchError("title_field는 text_fields에도 포함되어야 합니다.")
    concept["corpus"] = corpus
    raw_filters = concept.get("filters", [])
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_FIELDS:
        raise ElasticsearchError(f"filters는 최대 {MAX_FIELDS}개 항목이어야 합니다.")
    saved_filters = []
    for item in raw_filters:
        if not isinstance(item, dict):
            raise ElasticsearchError("각 filter는 object여야 합니다.")
        field = str(item.get("field", "")).strip()
        value = item.get("value")
        if not field or field not in corpus["filter_fields"]:
            raise ElasticsearchError("filters에는 corpus.filter_fields에 지정한 field만 사용할 수 있습니다.")
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value):
            raise ElasticsearchError("filter value는 문자열 또는 유한한 숫자/boolean이어야 합니다.")
        if isinstance(value, str) and (not value.strip() or len(value) > 500):
            raise ElasticsearchError("filter 문자열은 1~500자여야 합니다.")
        saved_filters.append({"field": field, "value": value})
    concept["filters"] = saved_filters
    settings = concept.get("settings") or {}
    if not isinstance(settings, dict):
        raise ElasticsearchError("settings 값이 올바르지 않습니다.")
    settings = {key: settings[key] for key in ("size", "candidate_size", "mode", "concept_weight", "related_weight", "field_boosts") if key in settings}
    settings["mode"] = str(settings.get("mode", "bm25")).lower()
    if settings["mode"] != "bm25":
        raise ElasticsearchError("개념 검색은 현재 bm25 모드만 지원합니다.")
    settings["size"] = _bounded_int(settings.get("size", 10), 1, 50, "size")
    settings["candidate_size"] = _bounded_int(settings.get("candidate_size", 50), settings["size"], 100, "candidate_size")
    for key in ("concept_weight", "related_weight"):
        try:
            number = float(settings.get(key, 1))
        except (TypeError, ValueError):
            raise ElasticsearchError(f"{key}는 숫자여야 합니다.") from None
        if not math.isfinite(number) or not 0 <= number <= 20:
            raise ElasticsearchError(f"{key}는 0~20 사이의 유한한 값이어야 합니다.")
        settings[key] = number
    boosts = settings.get("field_boosts", {}) or {}
    if not isinstance(boosts, dict):
        raise ElasticsearchError("field_boosts 값은 object여야 합니다.")
    settings["field_boosts"] = {str(k): _bounded_float(v, 0, 100, f"{k} boost") for k, v in boosts.items()}
    unexpected_boosts = set(settings["field_boosts"]) - set(corpus["text_fields"])
    if unexpected_boosts:
        raise ElasticsearchError("field_boosts에는 corpus.text_fields에 지정한 필드만 사용할 수 있습니다.")
    concept["settings"] = settings
    queries = concept.get("queries", [])
    if not isinstance(queries, list) or len(queries) > MAX_QUERY_CASES:
        raise ElasticsearchError(f"queries는 최대 {MAX_QUERY_CASES}개여야 합니다.")
    clean_queries = []
    seen = set()
    information_need_splits: dict[str, str] = {}
    for index, item in enumerate(queries):
        if not isinstance(item, dict):
            raise ElasticsearchError("각 query는 object여야 합니다.")
        query_id = str(item.get("id", f"q{index + 1}")).strip()
        text = str(item.get("query", "")).strip()
        split = str(item.get("split", "train"))
        if not query_id or query_id in seen or not text or len(text) > MAX_TEXT or split not in {"train", "validation"}:
            raise ElasticsearchError("query id는 고유해야 하며 query/split 값이 올바르지 않습니다.")
        seen.add(query_id)
        query_entry = {"id": query_id, "query": text, "split": split}
        raw_information_need = item.get("information_need", "")
        if not isinstance(raw_information_need, str):
            raise ElasticsearchError("정보 요구 묶음은 문자열이어야 합니다.")
        information_need = " ".join(raw_information_need.split())
        if len(information_need) > 120:
            raise ElasticsearchError("정보 요구 묶음은 최대 120자까지 입력할 수 있습니다.")
        if information_need:
            identity = information_need.casefold()
            previous_split = information_need_splits.get(identity)
            if previous_split is not None and previous_split != split:
                raise ElasticsearchError("같은 정보 요구 묶음은 학습용과 별도 확인용 질의에 나누어 넣을 수 없습니다. 두 질의의 사용 방식을 같게 하거나 묶음 이름을 바꾸세요.")
            information_need_splits[identity] = split
            query_entry["information_need"] = information_need
        clean_queries.append(query_entry)
    concept["queries"] = clean_queries
    return concept


def _bounded_int(value: Any, low: int, high: int, label: str) -> int:
    if isinstance(value, float) and not value.is_integer():
        raise ElasticsearchError(f"{label}은 정수여야 합니다.")
    if isinstance(value, str) and not re.fullmatch(r"[+-]?\d+", value.strip()):
        raise ElasticsearchError(f"{label}은 정수여야 합니다.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ElasticsearchError(f"{label}은 정수여야 합니다.") from None
    if isinstance(value, bool) or number < low or number > high:
        raise ElasticsearchError(f"{label}은 {low}~{high} 사이여야 합니다.")
    return number


def _bounded_float(value: Any, low: float, high: float, label: str) -> float:
    if isinstance(value, bool):
        raise ElasticsearchError(f"{label}은 숫자여야 합니다.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ElasticsearchError(f"{label}은 숫자여야 합니다.") from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ElasticsearchError(f"{label}은 {low}~{high} 사이의 유한한 값이어야 합니다.")
    return number


def save_concept(value: Any) -> dict[str, Any]:
    concept = validate_concept(value, assign_id=True)
    with _connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        return _save_concept_db(db, concept)


def _save_concept_db(db: sqlite3.Connection, concept: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(concept, ensure_ascii=False, allow_nan=False)
    version_id = str(uuid.uuid4())
    created_at = _now()
    row = db.execute("SELECT COALESCE(MAX(version_number),0) AS current_number FROM concept_versions WHERE concept_id=?", (concept["id"],)).fetchone()
    version_number = int(row["current_number"]) + 1
    db.execute("UPDATE concept_versions SET is_current=0 WHERE concept_id=?", (concept["id"],))
    db.execute("INSERT INTO concepts(id,body,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at", (concept["id"], body, created_at))
    db.execute("INSERT INTO concept_versions(version_id,concept_id,version_number,body,fingerprint,created_at,is_current) VALUES(?,?,?,?,?,?,1)", (version_id, concept["id"], version_number, body, _json_hash(concept), created_at))
    return {"concept": concept, "version_id": version_id, "version_number": version_number}


def list_versions(concept_id: str, limit: Any = 50) -> dict[str, Any]:
    concept_id = str(concept_id)
    if not concept_id or len(concept_id) > 128:
        raise ElasticsearchError("concept_id 값이 올바르지 않습니다.")
    limit = _bounded_int(limit, 1, 100, "limit")
    with _connect_db() as db:
        rows = db.execute("SELECT version_id,version_number,body,fingerprint,created_at FROM concept_versions WHERE concept_id=? ORDER BY version_number DESC LIMIT ?", (concept_id, limit)).fetchall()
    return {"versions": [{"version_id": row["version_id"], "version_number": row["version_number"], "created_at": row["created_at"], "concept_fingerprint": row["fingerprint"], "concept": json.loads(row["body"])} for row in rows]}


def restore_version(concept_id: str, version_id: str) -> dict[str, Any]:
    concept_id, version_id = str(concept_id), str(version_id)
    with _connect_db() as db:
        row = db.execute("SELECT body FROM concept_versions WHERE concept_id=? AND version_id=?", (concept_id, version_id)).fetchone()
    if not row:
        raise ElasticsearchError("선택한 개념 버전을 찾을 수 없습니다.", 404)
    restored = save_concept(json.loads(row["body"]))
    restored["restored_from"] = version_id
    return restored


def export_profile(connection: Connection, concept_id: str, version_id: str = "") -> dict[str, Any]:
    concept_id, version_id = str(concept_id), str(version_id)
    with _connect_db() as db:
        if version_id:
            row = db.execute("SELECT version_id,version_number,body,fingerprint FROM concept_versions WHERE concept_id=? AND version_id=?", (concept_id, version_id)).fetchone()
        else:
            row = db.execute("SELECT version_id,version_number,body,fingerprint FROM concept_versions WHERE concept_id=? AND is_current=1 ORDER BY version_number DESC LIMIT 1", (concept_id,)).fetchone()
    if not row:
        raise ElasticsearchError("내보낼 개념 버전을 찾을 수 없습니다.", 404)
    concept = validate_concept(json.loads(row["body"]))
    schema = _validate_search_fields(connection, concept)
    effective_filters = _normalize_filters(concept, concept["filters"])
    marker = "__ES_RAG_RUNTIME_QUERY__"
    query = _make_query(marker, concept)
    if effective_filters:
        query["bool"]["filter"] = _filter_clauses(concept, effective_filters)
    def replace_query(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: replace_query(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_query(item) for item in value]
        return "__ES_RAG_RAW_QUERY__" if value == marker else value
    search_body = {"size": concept["settings"]["size"], "track_total_hits": True, "_source": True, "query": query}
    source = json.dumps({**search_body, "query": replace_query(query)}, ensure_ascii=False, separators=(",", ":"))
    # Elasticsearch's Mustache toJson helper emits scalar strings without JSON
    # quotes; use a normal quoted variable here (the documented search-template
    # form for a user query string).
    source = source.replace('"__ES_RAG_RAW_QUERY__"', '"{{query}}"')
    profile = {"format": "es-rag-profile-v1", "version_id": row["version_id"], "version_number": row["version_number"], "fingerprint": row["fingerprint"], "mapping_fingerprint": _json_hash(schema["fields"]), "concept": {key: value for key, value in concept.items() if not key.startswith("_")}}
    return {"format": "es-rag-profile-v1", "profile": profile, "runtime": {"python": "from es_rag_tuner.profile_runtime import search_profile; search_profile(connection, profile, query)", "search_template": {"lang": "mustache", "source": source}, "example_params": {"query": "your user query"}, "example_search_body": search_body, "install_template_example": "PUT _scripts/es-rag-profile-" + str(concept["id"]), "invoke_template_example": "POST " + concept["corpus"]["index"] + "/_search/template"}, "warnings": ["Generated query is BM25-only. Export does not deploy it or verify an external application's retrieval and answer quality.", "Mapping fingerprint is informational; the Python runtime helper validates the live mapping before each search."]}


def ensure_query(concept_id: str, query_text: str, split: str = "train") -> dict[str, Any]:
    concept_id = str(concept_id)
    query_text = str(query_text).strip()
    split = str(split)
    if not concept_id or len(concept_id) > 128:
        raise ElasticsearchError("concept_id 값이 올바르지 않습니다.")
    if not query_text or len(query_text) > MAX_TEXT or split not in {"train", "validation"}:
        raise ElasticsearchError("검색 질의 또는 split 값이 올바르지 않습니다.")
    with _connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM concepts WHERE id=?", (concept_id,)).fetchone()
        if not row:
            raise ElasticsearchError("저장된 개념을 찾을 수 없습니다.", 404)
        concept = validate_concept(json.loads(row["body"]))
        exact = next((item for item in concept["queries"] if item["query"] == query_text and item["split"] == split), None)
        if exact:
            return {"concept_id": concept_id, "query_id": exact["id"], "query": exact["query"], "split": exact["split"]}
        base_id = "adhoc-" + _json_hash({"query": query_text, "split": split})[:16]
        query_id = base_id
        used = {item["id"] for item in concept["queries"]}
        suffix = 2
        while query_id in used:
            query_id = f"{base_id}-{suffix}"
            suffix += 1
        concept["queries"].append({"id": query_id, "query": query_text, "split": split})
        save_result = _save_concept_db(db, concept)
        return {"concept_id": concept_id, "query_id": query_id, "query": query_text, "split": split, "version_id": save_result["version_id"]}


def corpus_schema(connection: Connection, index: str, *, timeout: float | None = None) -> dict[str, Any]:
    index = validate_index(index)
    request_options = {"timeout": timeout} if timeout is not None else {}
    mapping_response = request(connection, "GET", f"{quote(index, safe='')}/_mapping", **request_options)
    mappings = [value.get("mappings", {}) for value in mapping_response.values() if isinstance(value, dict)]
    if not mappings:
        mappings = [mapping_response.get(index, {}).get("mappings", {})]
    properties: dict[str, Any] = {}
    for mapping in mappings:
        for name, definition in mapping.get("properties", {}).items():
            # Aliases can span indices. If definitions disagree, retain a
            # conservative type marker so field validation cannot overclaim.
            if name in properties and properties[name] != definition:
                properties[name] = {"type": "mapping_conflict"}
            else:
                properties[name] = definition
    fields: list[dict[str, Any]] = []

    def visit(tree: dict[str, Any], prefix: str = "", nested_path: str | None = None, parent_enabled: bool = True) -> None:
        for name, definition in tree.items():
            path = f"{prefix}.{name}" if prefix else name
            current_nested_path = path if definition.get("type") == "nested" else nested_path
            nested = current_nested_path is not None
            indexed = parent_enabled and definition.get("enabled", True) is not False and definition.get("index", True) is not False
            kind = str(definition.get("type", "object" if definition.get("properties") else "unknown"))
            fields.append({"name": path, "type": kind, "searchable": indexed and kind in {"text", "match_only_text", "search_as_you_type", "keyword", "constant_keyword", "wildcard"}, "filterable": indexed and kind in {"keyword", "constant_keyword", "integer", "long", "short", "byte", "float", "double", "half_float", "scaled_float", "boolean", "date", "ip"}, "nested": nested, "nested_path": current_nested_path, "source_field": path})
            if isinstance(definition.get("properties"), dict):
                visit(definition["properties"], path, current_nested_path, indexed)
            for subfield, subdef in definition.get("fields", {}).items():
                sub_kind = str(subdef.get("type", "unknown"))
                sub_indexed = indexed and subdef.get("index", True) is not False
                fields.append({"name": f"{path}.{subfield}", "type": sub_kind, "searchable": sub_indexed and sub_kind in {"text", "match_only_text", "search_as_you_type", "keyword", "wildcard"}, "filterable": sub_indexed and sub_kind in {"keyword", "constant_keyword", "integer", "long", "short", "byte", "float", "double", "half_float", "scaled_float", "boolean", "date", "ip"}, "nested": nested, "nested_path": current_nested_path, "source_field": path})
    visit(properties)
    conflicts = [field["name"] for field in fields if field["type"] == "mapping_conflict"]
    warnings = ["Alias mappings disagree for: " + ", ".join(conflicts[:20]) + (" …" if len(conflicts) > 20 else "")] if conflicts else []
    unsupported = [field["name"] for field in fields if field["type"] in {"semantic_text", "dense_vector", "sparse_vector", "completion", "rank_feature", "rank_features"}]
    if unsupported:
        warnings.append("Specialized fields are shown as non-searchable in this BM25 concept workflow: " + ", ".join(unsupported[:20]) + (" …" if len(unsupported) > 20 else ""))
    warning_codes = (["mapping_conflict"] if conflicts else []) + (["specialized_field_unsupported"] if unsupported else [])
    return {"index": index, "fields": fields, "warnings": warnings, "warning_codes": warning_codes}


def quickstart(connection: Connection, index: str, query: str = "") -> dict[str, Any]:
    """Suggest a bounded first experiment from mapping metadata and sample hits."""
    schema = corpus_schema(connection, index)
    fields = schema["fields"]
    field_by_name = {field["name"]: field for field in fields}
    searchable = [item for item in fields if item["searchable"]]
    text_fields = [item["name"] for item in searchable if item["type"] in {"text", "match_only_text", "search_as_you_type"}]
    if not text_fields:
        text_fields = [item["name"] for item in searchable]
    suggested_text_fields = text_fields[:MAX_FIELDS]
    title_priority = {"title": 0, "summary": 1, "subject": 2, "headline": 3, "name": 4}
    title_candidates = [item for item in searchable if not item["nested"] and item["name"].split(".")[-1].casefold() in title_priority]
    title_candidates.sort(key=lambda item: (
        title_priority[item["name"].split(".")[-1].casefold()] + (3 if "." in item["name"] else 0),
        item["name"].count("."),
        item["name"],
    ))
    scalar_text_fallback = next((item["name"] for item in searchable if not item["nested"]), None)
    title_field = title_candidates[0]["name"] if title_candidates else scalar_text_fallback
    if title_field and title_field not in suggested_text_fields:
        suggested_text_fields = ([title_field] + suggested_text_fields)[:MAX_FIELDS]
    filter_fields = [item["name"] for item in fields if item["filterable"]][:MAX_FIELDS]
    result = {"index": schema["index"], "fields": fields, "suggested_text_fields": suggested_text_fields, "suggested_title_field": title_field, "suggested_filter_fields": filter_fields, "sample_documents": [], "warnings": list(schema["warnings"]), "warning_codes": list(schema["warning_codes"])}

    def sample_rows(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        distinct = []
        remainder = []
        seen_titles = set()
        for hit in hits:
            title = _get_path(hit.get("source", {}), field_by_name.get(title_field, {}).get("source_field", title_field)) if title_field else None
            title_key = json.dumps(title, ensure_ascii=False, sort_keys=True) if title not in (None, "", [], {}) else None
            if title_key is None or title_key not in seen_titles:
                distinct.append(hit)
                if title_key is not None:
                    seen_titles.add(title_key)
            else:
                remainder.append(hit)
        selected = (distinct + remainder)[:3]
        rows = []
        for hit in selected:
            source = hit.get("source", {})
            selected_source = {}
            for field in suggested_text_fields:
                source_field = field_by_name.get(field, {}).get("source_field", field)
                values = _source_text_values(_get_path(source, source_field), source_field)
                if values:
                    selected_source[field] = [text[:1200] for _, text in values[:6]]
            rows.append({"_index": hit.get("_index", index), "_id": hit.get("_id", ""), "source": selected_source})
        return rows

    query = str(query).strip()
    if query and suggested_text_fields:
        temp = validate_concept({"name": "First search", "corpus": {"index": index, "title_field": title_field or "", "text_fields": suggested_text_fields, "filter_fields": filter_fields}, "settings": {"size": 12, "candidate_size": 12}})
        _validate_search_fields(connection, temp)
        sample = _hits(connection, index, query, 12, temp, expanded=False)
        result["sample_documents"] = sample_rows(sample["hits"])
        result["sample_total"] = sample["total"]
    else:
        includes = list(dict.fromkeys(field_by_name[name]["source_field"] for name in suggested_text_fields if name in field_by_name))
        sample = request(connection, "POST", f"{quote(index, safe='')}/_search", {"size": 12, "track_total_hits": False, "_source": {"includes": includes}, "query": {"match_all": {}}})
        raw_hits = sample.get("hits", {}).get("hits", [])
        hydrated = [{"_index": item.get("_index", index), "_id": item.get("_id", ""), "source": _safe_source(item.get("_source", {}))} for item in raw_hits]
        result["sample_documents"] = sample_rows(hydrated)
        result["sample_total"] = None
        result["warnings"].append("No first-search query was provided; sample documents are examples, not relevance suggestions.")
        result["warning_codes"].append("sample_not_query_ranked")
    return result


def _bounded_explanation(value: Any, depth: int = 0) -> Any:
    if not isinstance(value, dict):
        return value
    result = {}
    for key in ("value", "description", "details"):
        if key not in value:
            continue
        item = value[key]
        if key == "description":
            result[key] = str(item)[:1000]
        elif key == "details":
            if depth >= 4:
                result[key] = []
            else:
                result[key] = [_bounded_explanation(child, depth + 1) for child in item[:20] if isinstance(item, list) and isinstance(child, dict)] if isinstance(item, list) else []
        elif isinstance(item, (int, float)) and not math.isfinite(item):
            result[key] = None
        else:
            result[key] = item
    return result


def diagnose(connection: Connection, concept_value: Any, query: str = "", query_id: str = "", document_index: str = "", document_id: str = "") -> dict[str, Any]:
    concept = validate_concept(concept_value)
    _validate_search_fields(connection, concept)
    query = str(query).strip()
    query_id = str(query_id).strip()
    if query_id:
        saved = next((item for item in concept["queries"] if item["id"] == query_id), None)
        if not saved:
            raise ElasticsearchError(f"저장된 query id를 찾을 수 없습니다: {query_id}")
        if query and query != saved["query"]:
            raise ElasticsearchError("query와 query_id가 서로 다른 저장 query를 가리킵니다.")
        query = saved["query"]
    if not query or len(query) > MAX_TEXT:
        raise ElasticsearchError("검색어는 1~4000자여야 합니다.")
    index = validate_index(document_index)
    document_id = str(document_id)
    if not document_id or len(document_id.encode("utf-8")) > 512:
        raise ElasticsearchError("document_id는 비어 있을 수 없으며 512 UTF-8 바이트 이하여야 합니다.")
    effective_filters = _normalize_filters(concept, concept["filters"])
    try:
        document = request(connection, "GET", f"{quote(index, safe='')}/_doc/{quote(document_id, safe='')}")
    except ElasticsearchError as exc:
        if exc.status == 404:
            return {"document_index": index, "document_id": document_id, "query_id": query_id or None, "classification": "document_not_found", "probes": [], "selected_field_presence": [], "next_steps": ["인덱스 이름과 문서 ID를 확인하세요."], "warnings": ["The exact document could not be read from Elasticsearch."], "warning_codes": ["diagnostic_document_missing"]}
        raise
    source = document.get("_source", {})
    selected_presence = []
    for field in concept["corpus"]["text_fields"]:
        source_field = concept.get("_field_metadata", {}).get(field, {}).get("source_field", field)
        value = _get_path(source, source_field)
        has_value = bool(_source_text_values(value, source_field))
        selected_presence.append({"field": field, "has_value": has_value})
    baseline_query = _make_query(query, concept, expanded=False)
    candidate_query = _make_query(query, concept, expanded=True)
    filtered_candidate = dict(candidate_query)
    if effective_filters:
        filtered_candidate["bool"] = {**filtered_candidate["bool"], "filter": _filter_clauses(concept, effective_filters)}
    probes = []
    def explain(name: str, body: dict[str, Any]) -> bool:
        response = request(connection, "POST", f"{quote(index, safe='')}/_explain/{quote(document_id, safe='')}", {"query": body})
        matched = bool(response.get("matched"))
        explanation = _bounded_explanation(response.get("explanation", {}))
        score = explanation.get("value") if isinstance(explanation, dict) else None
        probes.append({"name": name, "matched": matched, "score": score if isinstance(score, (int, float)) and math.isfinite(score) else None, "explanation": explanation})
        return matched
    baseline_match = explain("baseline", baseline_query)
    candidate_match = explain("candidate_with_filters", filtered_candidate)
    classification = "inconclusive"
    warning_codes = []
    next_steps = []
    if candidate_match:
        pool = _hits(connection, concept["corpus"]["index"], query, concept["settings"]["candidate_size"], concept, filters=effective_filters)
        position = next((hit["rank"] for hit in pool["hits"] if str(hit.get("_index")) == index and str(hit.get("_id")) == document_id), None)
        if position is None:
            classification = "matches_outside_candidate_pool"
            next_steps.append("문서는 개념 질의에 매치되지만 현재 후보 수보다 낮은 순위입니다. 후보 수를 늘리거나 평가 문서로 포함해 확인하세요.")
        elif position > concept["settings"]["size"]:
            classification = "matches_below_display_window"
            next_steps.append("문서는 후보 목록에는 있지만 현재 화면의 표시 개수 밖입니다. 결과 개수를 늘려 보세요.")
        elif baseline_match:
            classification = "baseline_match"
            next_steps.append("기본 검색도 이 문서와 매치합니다. 질의 변형이나 필드 선택을 검토하세요.")
        else:
            classification = "expansion_match"
            next_steps.append("기본 질의는 이 문서와 매치하지 않지만 개념 확장은 매치합니다.")
    elif effective_filters:
        unfiltered = explain("candidate_without_filters", candidate_query)
        if unfiltered:
            classification = "filtered_out"
            next_steps.append("저장된 메타데이터 필터를 확인하거나 이 문서가 의도한 필터 범위에 속하는지 확인하세요.")
    if classification == "inconclusive" and concept["excluded_terms"]:
        without_exclusions = {**candidate_query, "bool": {key: value for key, value in candidate_query["bool"].items() if key != "must_not"}}
        if explain("candidate_without_exclusions", without_exclusions):
            classification = "excluded"
            next_steps.append("제외 표현 중 하나가 문서와 매치했습니다. 제외 목록과 원문 발췌를 검토하세요.")
    if classification == "inconclusive":
        classification = "no_selected_field_match" if any(item["has_value"] for item in selected_presence) else "no_selected_field_value"
        next_steps.append("선택된 원문 필드, 매핑, 인덱싱 시점과 문서 내용을 확인하세요. 현재 증거만으로 정확한 원인을 단정할 수 없습니다.")
        warning_codes.append("diagnostic_cause_uncertain")
    warnings = ["Explain probes test this exact document against the current query; they do not establish semantic relevance or RAG answer quality."]
    if warning_codes:
        warnings.append("No probe established a single cause; inspect mapping and indexed text before changing retrieval settings.")
    return {"document_index": index, "document_id": document_id, "query_id": query_id or None, "classification": classification, "probes": probes, "selected_field_presence": selected_presence, "next_steps": next_steps, "warnings": warnings, "warning_codes": list(dict.fromkeys(warning_codes))}


def _index_identity(connection: Connection, index: str, *, timeout: float | None = None) -> tuple[dict[str, Any], str | None]:
    try:
        request_options = {"timeout": timeout} if timeout is not None else {}
        result = request(connection, "GET", f"{quote(index, safe='')}/_settings?filter_path=*.settings.index.uuid", **request_options)
    except ElasticsearchError:
        return {"requested_index": index, "uuids": [], "available": False}, "Elasticsearch index UUID was unavailable; run history cannot detect index recreation from UUID."
    identities = []
    for concrete_index, body in sorted(result.items()):
        value = body.get("settings", {}).get("index", {}).get("uuid") if isinstance(body, dict) else None
        if value:
            identities.append({"index": concrete_index, "uuid": str(value)})
    if not identities:
        return {"requested_index": index, "uuids": [], "available": False}, "Elasticsearch index UUID was not returned; run history cannot detect index recreation from UUID."
    return {"requested_index": index, "uuids": identities, "available": True}, None


def _validate_search_fields(connection: Connection, concept: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
    schema = corpus_schema(connection, concept["corpus"]["index"], timeout=timeout)
    by_name = {field["name"]: field for field in schema["fields"]}
    for name in concept["corpus"]["text_fields"]:
        field = by_name.get(name)
        if not field or not field["searchable"]:
            raise ElasticsearchError(f"검색 필드가 없거나 검색할 수 없습니다: {name}")
    title = concept["corpus"]["title_field"]
    if title and (title not in by_name or not by_name[title]["searchable"] or by_name[title]["nested"]):
        raise ElasticsearchError(f"title_field가 mapping에 없거나 검색 가능한 scalar 필드가 아닙니다: {title}")
    for name in concept["corpus"]["filter_fields"]:
        field = by_name.get(name)
        if not field or not field.get("filterable", False):
            raise ElasticsearchError(f"filter field가 없거나 exact filter를 지원하지 않습니다: {name}")
    concept["_field_metadata"] = by_name
    concept["filters"] = _normalize_filters(concept, concept["filters"])
    return schema


def locate_document(connection: Connection, concept_id: str, text: str) -> dict[str, Any]:
    """Find bounded candidate documents using only a saved concept's mapped text fields."""
    concept_id = str(concept_id).strip()
    if not concept_id or len(concept_id) > 128:
        raise ElasticsearchError("concept_id 값이 올바르지 않습니다.")
    if not isinstance(text, str):
        raise ElasticsearchError("찾을 단어는 문자열이어야 합니다.")
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        raise ElasticsearchError("찾을 단어는 1~4000자여야 합니다.")
    with _connect_db() as db:
        row = db.execute("SELECT body FROM concepts WHERE id=?", (concept_id,)).fetchone()
    if not row:
        raise ElasticsearchError("저장된 개념을 찾을 수 없습니다.", 404)
    stored_concept = json.loads(row["body"])
    # The locator includes an older profile's separately configured title
    # field without rewriting the saved profile or changing regular validation.
    concept = validate_concept(stored_concept, allow_title_outside_text_fields=True)
    _validate_search_fields(connection, concept)

    corpus = concept["corpus"]
    title_field = corpus.get("title_field")
    fields = list(dict.fromkeys([*corpus["text_fields"], *([title_field] if title_field else [])]))
    metadata = concept.get("_field_metadata", {})
    groups: dict[str | None, list[str]] = {}
    for field in fields:
        groups.setdefault(metadata[field].get("nested_path"), []).append(field)
    should = []
    for nested_path, grouped_fields in groups.items():
        match = {"multi_match": {"query": text, "type": "best_fields", "fields": grouped_fields, "tie_breaker": 0.2}}
        should.append({"nested": {"path": nested_path, "score_mode": "max", "query": match}} if nested_path else match)

    source_fields = list(dict.fromkeys(metadata[field]["source_field"] for field in fields))
    scalar_fields = [field for field in fields if not metadata[field].get("nested_path")]
    body = {
        "size": 10,
        "from": 0,
        "track_total_hits": False,
        "_source": {"includes": source_fields},
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
    }
    if scalar_fields:
        body["highlight"] = {
            "fields": {
                field: {"number_of_fragments": 1, "fragment_size": 180, "require_field_match": True}
                for field in scalar_fields
            }
        }
    # Do not allow a shard timeout/failure to masquerade as a clean no-match.
    result = request(connection, "POST", f"{quote(corpus['index'], safe='')}/_search?allow_partial_search_results=false", body)
    if not isinstance(result, dict):
        raise ElasticsearchError("문서 찾기를 완료하지 못했습니다: Elasticsearch 응답 형식이 올바르지 않습니다.", 502)
    if result.get("timed_out") is not False:
        raise ElasticsearchError("문서 찾기를 완료하지 못했습니다: 검색 완료 여부를 확인할 수 없습니다.", 502)
    shards = result.get("_shards")
    failed_shards = shards.get("failed") if isinstance(shards, dict) else None
    if isinstance(failed_shards, bool) or not isinstance(failed_shards, int):
        raise ElasticsearchError("문서 찾기를 완료하지 못했습니다: shard 상태를 확인할 수 없습니다.", 502)
    if failed_shards != 0:
        raise ElasticsearchError("문서 찾기를 완료하지 못했습니다: Elasticsearch shard 오류.", 502)

    response_hits = result.get("hits")
    hits = response_hits.get("hits") if isinstance(response_hits, dict) else None
    if not isinstance(hits, list) or any(not isinstance(hit, dict) for hit in hits):
        raise ElasticsearchError("문서 찾기를 완료하지 못했습니다: 검색 결과 목록이 올바르지 않습니다.", 502)
    for hit in hits:
        if not isinstance(hit.get("_index"), str) or not hit["_index"]:
            raise ElasticsearchError("문서 찾기를 완료하지 못했습니다: 후보 인덱스 식별자가 없습니다.", 502)
        hit_id = hit.get("_id")
        if isinstance(hit_id, bool) or not isinstance(hit_id, (str, int)) or str(hit_id) == "":
            raise ElasticsearchError("문서 찾기를 완료하지 못했습니다: 후보 문서 ID가 없습니다.", 502)
    candidates = []
    title_source = metadata.get(title_field, {}).get("source_field") if title_field else None
    def source_value(source: Any, path: str | None) -> Any:
        if not path or not isinstance(source, dict):
            return None
        value: Any = source
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, list):
            value = next((item for item in value if isinstance(item, str) and item.strip()), None)
        return value if isinstance(value, str) and value.strip() else None

    for hit in hits[:10]:
        source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
        title = source_value(source, title_source) or str(hit.get("_id", ""))
        highlight = hit.get("highlight") if isinstance(hit.get("highlight"), dict) else {}
        matched = []
        excerpts = {}
        for field in scalar_fields:
            fragments = highlight.get(field)
            if not isinstance(fragments, list):
                continue
            fragment = next((item for item in fragments if isinstance(item, str) and item.strip()), None)
            if fragment is not None:
                matched.append(field)
                excerpts[field] = fragment
        excerpt_field = matched[0] if matched else None
        excerpt = excerpts.get(excerpt_field) if excerpt_field else None
        nested_only = not scalar_fields and any(metadata[field].get("nested_path") for field in fields)
        candidates.append({
            "document_index": str(hit.get("_index", corpus["index"])),
            "document_id": str(hit.get("_id", "")),
            "score": hit.get("_score") if isinstance(hit.get("_score"), (int, float)) and math.isfinite(hit["_score"]) else None,
            "title": title[:300],
            "excerpt": excerpt[:600] if excerpt else None,
            "excerpt_field": excerpt_field,
            "matched_fields": matched,
            "excerpt_is_nested": nested_only,
        })
    return {"index": corpus["index"], "fields": fields, "candidates": candidates}


def _terms(concept: dict[str, Any]) -> list[tuple[str, float, str]]:
    settings = concept["settings"]
    terms = [(concept["name"], settings["concept_weight"], "concept")]
    if concept["description"].strip():
        terms.append((concept["description"].strip(), settings["concept_weight"], "definition"))
    terms += [(term, settings["concept_weight"], "alias") for term in concept["aliases"]]
    terms += [(item["term"], item["weight"] * settings["related_weight"], "related") for item in concept["related"]]
    return [(text, weight, kind) for text, weight, kind in terms if text and weight > 0]


def _make_query(query_text: str, concept: dict[str, Any], *, expanded: bool = True) -> dict[str, Any]:
    fields = concept["corpus"]["text_fields"]
    boosts = concept["settings"]["field_boosts"]
    field_names = [f"{field}^{boosts.get(field, 1):g}" for field in fields if boosts.get(field, 1) > 0]
    if not field_names:
        raise ElasticsearchError("검색 필드 가중치가 모두 0입니다.")
    metadata = concept.get("_field_metadata", {})

    def clauses(text: str, boost: float = 1.0) -> list[dict[str, Any]]:
        groups: dict[str | None, list[str]] = {}
        for field in fields:
            weight = boosts.get(field, 1)
            if weight <= 0:
                continue
            field_info = metadata.get(field, {})
            groups.setdefault(field_info.get("nested_path"), []).append(f"{field}^{weight:g}")
        result = []
        for nested_path, grouped_fields in groups.items():
            match: dict[str, Any] = {"multi_match": {"query": text, "type": "best_fields", "fields": grouped_fields, "tie_breaker": 0.2}}
            if boost != 1:
                match["multi_match"]["boost"] = boost
            if nested_path:
                result.append({"nested": {"path": nested_path, "score_mode": "max", "query": match}})
            else:
                result.append(match)
        return result

    def exclusion_clauses(text: str) -> list[dict[str, Any]]:
        groups: dict[str | None, list[str]] = {}
        for field in fields:
            if boosts.get(field, 1) <= 0:
                continue
            nested_path = metadata.get(field, {}).get("nested_path")
            groups.setdefault(nested_path, []).append(field)
        result = []
        for nested_path, grouped_fields in groups.items():
            phrase: dict[str, Any] = {"multi_match": {"query": text, "type": "phrase", "fields": grouped_fields}}
            result.append({"nested": {"path": nested_path, "score_mode": "none", "query": phrase}} if nested_path else phrase)
        return result

    should: list[dict[str, Any]] = clauses(query_text)
    if expanded:
        for text, weight, _kind in _terms(concept):
            if weight <= 0:
                continue
            should.extend(clauses(text, weight))
    bool_query: dict[str, Any] = {"should": should, "minimum_should_match": 1}
    if expanded and concept["excluded_terms"]:
        bool_query["must_not"] = [clause for item in concept["excluded_terms"] for clause in exclusion_clauses(item)]
    return {"bool": bool_query}


def _safe_source(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value[:100_000])
    if isinstance(value, list):
        return [_safe_source(item) for item in value[:100]]
    if isinstance(value, dict):
        return {str(key): _safe_source(item) for key, item in list(value.items())[:100]}
    return value


def _selected_source(source: Any, fields: list[str]) -> Any:
    """Project source data onto explicit dotted paths while preserving arrays."""
    if isinstance(source, list):
        return [_selected_source(item, fields) for item in source[:100]]
    if not isinstance(source, dict):
        return {}
    result: dict[str, Any] = {}
    grouped: dict[str, list[str]] = {}
    terminal: set[str] = set()
    for field in fields:
        parts = [part for part in field.split(".") if part]
        if not parts:
            continue
        grouped.setdefault(parts[0], [])
        if len(parts) == 1:
            terminal.add(parts[0])
        else:
            grouped[parts[0]].append(".".join(parts[1:]))
    for key, children in grouped.items():
        if key not in source:
            continue
        if key in terminal:
            result[key] = source[key]
            continue
        child = _selected_source(source[key], children)
        if child:
            result[key] = child
    return result


def _get_path(source: dict[str, Any], path: str) -> Any:
    def walk(current: Any, parts: list[str]) -> Any:
        if not parts:
            return current
        if isinstance(current, list):
            return [walk(item, parts) for item in current]
        if not isinstance(current, dict):
            return None
        return walk(current.get(parts[0]), parts[1:])
    return walk(source, path.split("."))


def _source_text_values(value: Any, path: str) -> list[tuple[str, str]]:
    """Return original scalar source values without joining array elements."""
    if isinstance(value, list):
        return [pair for index, item in enumerate(value) for pair in _source_text_values(item, f"{path}[{index}]")]
    if isinstance(value, dict):
        return [pair for key, item in value.items() for pair in _source_text_values(item, f"{path}.{key}")]
    if isinstance(value, (str, int, float)):
        text = str(value)
        return [(path, text)] if text else []
    return []


def _normalize_filters(concept: dict[str, Any], filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    metadata = concept.get("_field_metadata", {})
    for item in filters:
        field = str(item["field"])
        value = item.get("value")
        kind = metadata.get(field, {}).get("type")
        if kind in {"byte", "short", "integer", "long"}:
            if isinstance(value, bool):
                raise ElasticsearchError(f"{field} requires an integer filter value.")
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ElasticsearchError(f"{field} requires an integer filter value.") from None
            if isinstance(value, float) and not value.is_integer() or isinstance(value, str) and not re.fullmatch(r"[+-]?\d+", value.strip()):
                raise ElasticsearchError(f"{field} requires an integer filter value.")
            bounds = {"byte": (-(2**7), 2**7 - 1), "short": (-(2**15), 2**15 - 1), "integer": (-(2**31), 2**31 - 1), "long": (-(2**63), 2**63 - 1)}[kind]
            if not bounds[0] <= number <= bounds[1]:
                raise ElasticsearchError(f"{field} filter value is outside the mapped integer range.")
            value = number
        elif kind in {"float", "double", "half_float", "scaled_float"}:
            value = _bounded_float(value, -1e100, 1e100, f"{field} filter")
        elif kind == "boolean":
            if isinstance(value, str) and value.lower() in {"true", "false"}:
                value = value.lower() == "true"
            elif not isinstance(value, bool):
                raise ElasticsearchError(f"{field} requires a boolean filter value.")
        else:
            value = str(value)
            if not value.strip() or len(value) > 500:
                raise ElasticsearchError(f"{field} filter value must be 1 to 500 characters.")
        normalized.append({"field": field, "value": value})
    return normalized


def _filter_clauses(concept: dict[str, Any], filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    metadata = concept.get("_field_metadata", {})
    for item in filters:
        field = str(item["field"])
        value = item.get("value")
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value):
            raise ElasticsearchError("filter value는 문자열 또는 유한한 숫자/boolean이어야 합니다.")
        clause: dict[str, Any] = {"term": {field: value}}
        nested_path = metadata.get(field, {}).get("nested_path")
        if nested_path:
            clause = {"nested": {"path": nested_path, "query": clause, "score_mode": "none"}}
        result.append(clause)
    return result


def _evidence(source: dict[str, Any], concept: dict[str, Any] | None, *, include_evidence: bool = True) -> tuple[str, list[dict[str, str]]]:
    if not concept:
        return "", []
    snippets: list[tuple[int, str]] = []
    evidence = []
    terms = [(term, kind) for term, _weight, kind in _terms(concept)] if include_evidence else []
    if include_evidence:
        for word in re.findall(r"[\w-]{3,}", concept.get("description", "")):
            terms.append((word, "definition"))
    for field in concept["corpus"]["text_fields"]:
        source_field = concept.get("_field_metadata", {}).get(field, {}).get("source_field", field)
        values = _source_text_values(_get_path(source, source_field), source_field)
        for source_path, value in values:
            clean = _safe_source(value)
            matched = False
            lower = clean.casefold()
            field_seen = set()
            for term, kind in terms:
                position = lower.find(term.casefold())
                if position >= 0:
                    key = (field, source_path, term.casefold(), kind)
                    if key not in field_seen and len(evidence) < 30:
                        left, right = max(0, position - 120), min(len(clean), position + len(term) + 160)
                        evidence.append({"field": field, "source_field": source_field, "source_path": source_path, "term": term[:160], "kind": kind, "basis": "lexical", "status": "candidate", "snippet": (("… " if left else "") + clean[left:right].strip() + (" …" if right < len(clean) else ""))[:320]})
                        field_seen.add(key)
                    matched = True
            if matched:
                priority = {"alias": 5, "related": 4, "concept": 3, "definition": 1}
                matches = [(priority.get(kind, 0), term, kind) for term, kind in terms if term.casefold() in lower]
                best_priority, term, _kind = max(matches, key=lambda item: (item[0], len(item[1])))
                pos = lower.find(term.casefold())
                left, right = max(0, pos - 180), min(len(clean), pos + len(term) + 260)
                excerpt = clean[left:right].strip()
                snippets.append((best_priority, ("… " if left else "") + excerpt + (" …" if right < len(clean) else "")))
            elif not include_evidence and clean.strip():
                snippets.append((0, clean.strip()))
    snippet = max(snippets, key=lambda item: item[0])[1] if snippets else ""
    return snippet[:600], evidence


def _hits(connection: Connection, index: str, query: str, size: int, concept: dict[str, Any], *, expanded: bool = True, filters: list[dict[str, Any]] | None = None, timeout: float | None = None) -> dict[str, Any]:
    query_body = _make_query(query, concept, expanded=expanded)
    if filters:
        query_body["bool"]["filter"] = _filter_clauses(concept, filters)
    body = {"size": size, "track_total_hits": True, "_source": True, "query": query_body}
    request_options = {"timeout": timeout} if timeout is not None else {}
    result = request(connection, "POST", f"{quote(index, safe='')}/_search", body, **request_options)
    response_hits = result.get("hits", {})
    raw_hits = response_hits.get("hits", [])
    hits = []
    for rank, item in enumerate(raw_hits, 1):
        raw_source = item.get("_source", {})
        source = _safe_source(raw_source)
        snippet, evidence = _evidence(source if isinstance(source, dict) else {}, concept, include_evidence=expanded)
        if not snippet:
            title = _get_path(source, concept["corpus"]["title_field"]) if concept["corpus"]["title_field"] else ""
            snippet = str(title or "")[:600]
        hits.append({"_index": item.get("_index", index), "_id": item.get("_id", ""), "_score": item.get("_score"), "rank": rank, "source": source, "source_sha256": _json_hash(raw_source), "snippet": snippet, "evidence": evidence})
    total = response_hits.get("total", 0)
    if isinstance(total, dict):
        total = total.get("value", 0)
    return {"hits": hits, "total": int(total), "query": body["query"]}


def preview(connection: Connection, concept_value: Any, query: str = "", query_id: str = "", filters: Any = None) -> dict[str, Any]:
    concept = validate_concept(concept_value)
    _validate_search_fields(connection, concept)
    query = str(query).strip()
    if query_id:
        saved = next((item for item in concept["queries"] if item["id"] == query_id), None)
        if not saved:
            raise ElasticsearchError(f"저장된 query id를 찾을 수 없습니다: {query_id}")
        if query and query != saved["query"]:
            raise ElasticsearchError("query와 query_id가 서로 다른 저장 query를 가리킵니다.")
        query = saved["query"]
    if not query or len(query) > MAX_TEXT:
        raise ElasticsearchError("검색어는 1~4000자여야 합니다.")
    filter_values = concept["filters"] if filters is None else filters
    if not isinstance(filter_values, list):
        raise ElasticsearchError("filters는 배열이어야 합니다.")
    if len(filter_values) > MAX_FIELDS:
        raise ElasticsearchError(f"filters는 최대 {MAX_FIELDS}개 항목이어야 합니다.")
    for item in filter_values:
        if not isinstance(item, dict) or item.get("field") not in concept["corpus"]["filter_fields"]:
            raise ElasticsearchError("concept에 등록된 filter_fields만 사용할 수 있습니다.")
    filter_values = _normalize_filters(concept, filter_values)
    # Compile exact term filters into the query after validation.
    baseline = _hits(connection, concept["corpus"]["index"], query, concept["settings"]["candidate_size"], concept, expanded=False, filters=filter_values)
    candidate = _hits(connection, concept["corpus"]["index"], query, concept["settings"]["candidate_size"], concept, filters=filter_values)
    baseline["pool_count"] = len(baseline["hits"])
    candidate["pool_count"] = len(candidate["hits"])
    judgments = _judgments(concept["id"], concept) if concept["id"] and query_id else []
    selected = [row for row in judgments if row["query_id"] == query_id and not row.get("stale")]
    judgment_map = {(row["document_index"], row["document_id"]): {"rating": row["rating"], "pinned": bool(row["pinned"]), "reason": row["reason"]} for row in selected}
    for hit in candidate["hits"]:
        key = (str(hit.get("_index", concept["corpus"]["index"])), str(hit.get("_id", "")))
        hit["judgment"] = judgment_map.get(key, {"rating": None, "pinned": False, "reason": ""})
        hit["pinned"] = bool(hit["judgment"]["pinned"])
        hit["organic_rank"] = hit["rank"]
    existing = {(str(hit.get("_index", "")), str(hit.get("_id", ""))) for hit in candidate["hits"]}
    warnings = ["Elasticsearch scores are ranking scores, not probabilities.", "Lexical evidence is a surface-text match; absence of this evidence does not imply irrelevance."]
    warning_codes = ["score_not_probability", "lexical_candidate_evidence"]
    if any(row.get("stale") for row in judgments):
        warnings.append("Some saved judgments refer to an older query version and were not attached to this preview.")
        warning_codes.append("stale_judgments")
    if query_id:
        for row in selected:
            key = (row["document_index"], row["document_id"])
            if row["pinned"] and key not in existing:
                try:
                    doc = request(connection, "GET", f"{quote(row['document_index'], safe='')}/_doc/{quote(row['document_id'], safe='')}")
                except ElasticsearchError as exc:
                    if exc.status == 404:
                        warnings.append(f"Pinned document {row['document_index']}/{row['document_id']} could not be found.")
                        warning_codes.append("pinned_document_missing")
                        continue
                    raise
                source = _safe_source(doc.get("_source", {}))
                source_hash = _json_hash(doc.get("_source", {}))
                snippet, evidence = _evidence(source if isinstance(source, dict) else {}, concept)
                if not snippet and concept["corpus"]["title_field"]:
                    snippet = str(_get_path(source, concept["corpus"]["title_field"]) or "")[:600]
                candidate["hits"].append({"_index": row["document_index"], "_id": row["document_id"], "_score": None, "rank": None, "organic_rank": None, "pinned": True, "source": source, "source_sha256": source_hash, "snippet": snippet, "evidence": evidence, "judgment": {"rating": row["rating"], "pinned": True, "reason": row["reason"]}})
                existing.add(key)
    base_ranks = {(str(hit.get("_index", concept["corpus"]["index"])), str(hit["_id"])): hit["rank"] for hit in baseline["hits"]}
    candidate_ranks = {(str(hit.get("_index", concept["corpus"]["index"])), str(hit["_id"])): hit.get("organic_rank", hit["rank"]) for hit in candidate["hits"]}
    comparison = [{"document_index": doc_index, "document_id": doc_id, "baseline_rank": base_ranks.get((doc_index, doc_id)), "candidate_rank": candidate_ranks.get((doc_index, doc_id))} for doc_index, doc_id in sorted(set(base_ranks) | set(candidate_ranks))]
    display_size = concept["settings"]["size"]
    baseline["hits"] = baseline["hits"][:display_size]
    organic_visible = candidate["hits"][:display_size]
    visible_keys = {(str(hit.get("_index", "")), str(hit.get("_id", ""))) for hit in organic_visible}
    pinned_extra = [hit for hit in candidate["hits"][display_size:] if hit.get("pinned")]
    candidate["hits"] = organic_visible + [hit for hit in pinned_extra if (str(hit.get("_index", "")), str(hit.get("_id", ""))) not in visible_keys]
    run_id = str(uuid.uuid4())
    mapping_fingerprint = _json_hash(_validate_search_fields(connection, concept)["fields"])
    index_identity, identity_warning = _index_identity(connection, concept["corpus"]["index"])
    if identity_warning:
        warnings.append(identity_warning)
        warning_codes.append("index_identity_unavailable")
    safe_concept = {key: value for key, value in concept.items() if not key.startswith("_")}
    preview_snapshot = {
        "query": query,
        "query_id": query_id,
        "effective_filters": filter_values,
        "settings": concept["settings"],
        "input_snapshot": {"concept": safe_concept, "query": next((item for item in concept["queries"] if item["id"] == query_id), {"id": "adhoc", "query": query}), "filters": filter_values, "judgments": selected},
        "baseline_ids": [[hit.get("_index"), hit.get("_id"), hit.get("rank")] for hit in baseline["hits"]],
        "candidate_ids": [[hit.get("_index"), hit.get("_id"), hit.get("organic_rank")] for hit in candidate["hits"]],
        "output_snapshot": {
            "baseline": [{"index": hit.get("_index"), "id": hit.get("_id"), "rank": hit.get("rank"), "source_sha256": hit.get("source_sha256")} for hit in baseline["hits"]],
            "candidate": [{"index": hit.get("_index"), "id": hit.get("_id"), "organic_rank": hit.get("organic_rank"), "pinned": bool(hit.get("pinned")), "source_sha256": hit.get("source_sha256")} for hit in candidate["hits"]],
        },
        "reproducibility": {
            "index": concept["corpus"]["index"],
            "index_identity": index_identity,
            "mapping_fingerprint": mapping_fingerprint,
            "query_fingerprint": _json_hash(next((item for item in concept["queries"] if item["id"] == query_id), {"query": query, "id": "adhoc"})),
            "concept_fingerprint": _json_hash(concept),
            "filters_fingerprint": _json_hash(filter_values),
            "settings_fingerprint": _json_hash(concept["settings"]),
            "judgment_fingerprint": _json_hash(selected),
        },
    }
    _store_run(concept["id"], "preview", preview_snapshot, run_id=run_id)
    return {"run_id": run_id, "query": query, "filters": filter_values, "effective_filters": filter_values, "baseline": baseline, "candidate": candidate, "comparison": comparison, "warnings": warnings, "warning_codes": list(dict.fromkeys(warning_codes))}


def _load_saved_concept_readonly(concept_id: str) -> dict[str, Any]:
    concept_id = str(concept_id).strip()
    if not concept_id or len(concept_id) > 128:
        raise ElasticsearchError("저장된 개념을 선택하세요.")
    configured_db = os.environ.get("ES_RAG_CONCEPT_DB", "").strip()
    db_path = Path(configured_db).expanduser() if configured_db else Path.home() / ".local" / "share" / "es-rag-workbench" / "concepts.sqlite3"
    if not db_path.is_file():
        raise ElasticsearchError("저장된 개념 데이터베이스를 읽을 수 없습니다. 먼저 개념을 저장하세요.", 503)
    db = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("SELECT body FROM concepts WHERE id=?", (concept_id,)).fetchone()
    except sqlite3.OperationalError:
        raise ElasticsearchError("저장된 개념 테이블을 읽을 수 없습니다.", 503) from None
    finally:
        db.close()
    if not row:
        raise ElasticsearchError("저장된 개념을 찾을 수 없습니다. 먼저 개념을 저장하세요.", 404)
    return validate_concept(json.loads(row["body"]))


def _saved_query(concept: dict[str, Any], query_id: str) -> dict[str, Any]:
    query_id = str(query_id).strip()
    if not query_id or len(query_id) > 128:
        raise ElasticsearchError("저장된 질의를 선택하세요.")
    saved_query = next((item for item in concept["queries"] if item["id"] == query_id), None)
    if not saved_query:
        raise ElasticsearchError("선택한 질의는 저장된 개념에 없습니다. 질의를 저장한 뒤 다시 시도하세요.")
    return saved_query


def _vector_candidates_for_saved_query(connection: Connection, concept: dict[str, Any], query_id: str,
                                       judgments: list[dict[str, Any]] | None = None,
                                       effective_filters: list[dict[str, Any]] | None = None,
                                       profile_id: str | None = None) -> dict[str, Any]:
    saved_query = _saved_query(concept, query_id)
    _validate_search_fields(connection, concept)
    index = concept["corpus"]["index"]
    source_fields = list(dict.fromkeys(
        concept.get("_field_metadata", {}).get(field, {}).get("source_field", field)
        for field in [*concept["corpus"]["text_fields"], *([concept["corpus"]["title_field"]] if concept["corpus"]["title_field"] else [])]
    ))
    spec = embeddings.profile_spec(profile_id)
    recipe = embeddings.profile_recipe(profile_id)
    _, concrete_indices = (vector_mapping_targets(connection, index, profile_id=profile_id)
                           if profile_id is not None else vector_mapping_targets(connection, index))
    if count_vectors(connection, index) <= 0:
        raise ElasticsearchError("선택한 인덱스에 사용할 수 있는 임베딩 문서가 없습니다. 인덱스 준비 상태를 확인하세요.")
    try:
        if profile_id is None:
            query_vector = embeddings.embed_texts([saved_query["query"]], "query", local_files_only=True)[0]
        else:
            query_vector = embeddings.embed_texts([saved_query["query"]], "query", local_files_only=True, profile_id=profile_id)[0]
    except Exception as exc:
        raise ElasticsearchError(f"질의 임베딩을 준비하지 못했습니다: {str(exc)[:300]}", 503, safe_for_user=False) from None
    if not isinstance(query_vector, list) or len(query_vector) != spec["dimensions"]:
        raise ElasticsearchError("질의 임베딩 응답의 차원이 올바르지 않습니다.", 503)
    filters = concept["filters"] if effective_filters is None else effective_filters
    knn: dict[str, Any] = {"field": "rag_embedding", "query_vector": query_vector, "k": concept["settings"]["size"], "num_candidates": min(10000, max(50, concept["settings"]["size"] * 10))}
    if filters:
        knn["filter"] = {"bool": {"filter": _filter_clauses(concept, filters)}}
    body = {"size": concept["settings"]["size"], "track_total_hits": True, "_source": source_fields, "knn": knn}
    result = request(connection, "POST", f"{quote(index, safe='')}/_search?allow_partial_search_results=false", body)
    if not isinstance(result, dict) or result.get("timed_out") is not False:
        raise ElasticsearchError("벡터 후보 검색이 시간 초과 또는 불완전 응답으로 끝났습니다.", 503)
    shards = result.get("_shards")
    failed_shards = shards.get("failed") if isinstance(shards, dict) else None
    if not isinstance(failed_shards, int) or isinstance(failed_shards, bool) or failed_shards != 0:
        raise ElasticsearchError("벡터 후보 검색에서 shard 오류가 발생했습니다. 부분 결과는 표시하지 않았습니다.", 503)
    response_hits = result.get("hits")
    raw_hits = response_hits.get("hits") if isinstance(response_hits, dict) else None
    if not isinstance(raw_hits, list) or len(raw_hits) > concept["settings"]["size"]:
        raise ElasticsearchError("벡터 후보 검색 응답 형식이 올바르지 않습니다.", 503)
    if judgments is None:
        judgments = _judgments_readonly(concept["id"], concept)
    judgment_map = {(item["document_index"], item["document_id"]): item for item in judgments if item["query_id"] == query_id and not item.get("stale")}
    candidates = []
    for rank, hit in enumerate(raw_hits, 1):
        score = hit.get("_score") if isinstance(hit, dict) else None
        if not isinstance(hit, dict) or hit.get("_id") is None or not str(hit.get("_id")) or not isinstance(hit.get("_source"), dict) or not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
            raise ElasticsearchError("벡터 후보 검색 결과 형식이 올바르지 않습니다.", 503)
        raw_document_index = hit.get("_index")
        if not isinstance(raw_document_index, str) or raw_document_index not in concrete_indices:
            raise ElasticsearchError(
                "벡터 후보 검색 결과의 concrete _index가 alias 매핑 대상에 없습니다. "
                "alias 대상 또는 Elasticsearch 검색 응답을 확인하세요.",
                503,
            )
        document_index = raw_document_index
        raw_source = _selected_source(hit["_source"], source_fields)
        source = _safe_source(raw_source)
        snippet, _ = _evidence(source, concept, include_evidence=False)
        if not snippet and concept["corpus"]["title_field"]:
            snippet = str(_get_path(source, concept["corpus"]["title_field"]) or "")[:600]
        saved = judgment_map.get((document_index, str(hit["_id"])))
        candidates.append({"_index": document_index, "_id": str(hit["_id"]), "_score": hit.get("_score"), "rank": rank, "source": source, "source_sha256": _json_hash(raw_source), "snippet": snippet,
                           "judgment": {"rating": saved["rating"], "pinned": bool(saved["pinned"]), "reason": saved["reason"]} if saved else {"rating": None, "pinned": False, "reason": ""}})
    if "total" not in response_hits:
        raise ElasticsearchError("벡터 후보 검색 응답에 total이 없습니다.", 503)
    total = response_hits["total"]
    if isinstance(total, dict):
        if total.get("relation") != "eq":
            raise ElasticsearchError("벡터 후보 검색 total이 정확한 응답이 아닙니다.", 503)
        total = total.get("value")
    if not isinstance(total, int) or isinstance(total, bool) or total < len(candidates):
        raise ElasticsearchError("벡터 후보 검색 total 응답이 올바르지 않습니다.", 503)
    return {"concept_id": concept["id"], "query_id": query_id, "query": saved_query["query"], "index": index, "mode": "vector", "model": spec["model_name"],
            "profile_id": spec["profile_id"], "recipe": recipe, "field": "rag_embedding", "dimensions": spec["dimensions"], "approximate": True, "exhaustive": False, "total": total, "candidates": candidates}


def vector_candidates(connection: Connection, concept_id: str, query_id: str,
                      profile_id: str | None = None) -> dict[str, Any]:
    """Read a bounded dense-vector candidate list for one persisted query."""
    concept = _load_saved_concept_readonly(concept_id)
    _saved_query(concept, query_id)
    return _vector_candidates_for_saved_query(connection, concept, str(query_id).strip(), profile_id=profile_id)


def _complete_comparison_hits(connection: Connection, concept: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
    filters = _normalize_filters(concept, concept["filters"])
    body_query = _make_query(query["query"], concept, expanded=True)
    if filters:
        body_query["bool"]["filter"] = _filter_clauses(concept, filters)
    body = {"size": concept["settings"]["size"], "track_total_hits": True, "_source": False, "query": body_query}
    result = request(connection, "POST", f"{quote(concept['corpus']['index'], safe='')}/_search?allow_partial_search_results=false", body)
    if not isinstance(result, dict) or result.get("timed_out") is not False:
        raise ElasticsearchError("BM25 비교 검색이 시간 초과 또는 불완전 응답으로 끝났습니다.", 503)
    shards = result.get("_shards")
    if not isinstance(shards, dict) or not isinstance(shards.get("failed"), int) or isinstance(shards.get("failed"), bool) or shards["failed"] != 0:
        raise ElasticsearchError("BM25 비교 검색에서 shard 오류가 발생했습니다. 부분 결과는 표시하지 않았습니다.", 503)
    hits_obj = result.get("hits")
    raw_hits = hits_obj.get("hits") if isinstance(hits_obj, dict) else None
    if not isinstance(raw_hits, list) or not isinstance(hits_obj, dict) or "total" not in hits_obj:
        raise ElasticsearchError("BM25 비교 검색 응답 형식이 올바르지 않습니다.", 503)
    raw_total = hits_obj["total"]
    if isinstance(raw_total, dict):
        total = raw_total.get("value")
        if raw_total.get("relation") != "eq" or not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ElasticsearchError("BM25 비교 검색 total이 정확하고 유효한 정수가 아닙니다.", 503)
    elif isinstance(raw_total, int) and not isinstance(raw_total, bool) and raw_total >= 0:
        total = raw_total
    else:
        raise ElasticsearchError("BM25 비교 검색 total이 정확하고 유효한 정수가 아닙니다.", 503)
    size = concept["settings"]["size"]
    if len(raw_hits) > size or total < len(raw_hits) or len(raw_hits) != min(size, total):
        raise ElasticsearchError("BM25 비교 검색 결과 개수가 정확한 total 및 요청 크기와 일치하지 않습니다.", 503)
    output = []
    identities: set[tuple[str, str]] = set()
    for hit in raw_hits:
        if not isinstance(hit, dict) or not isinstance(hit.get("_id"), str) or not hit["_id"] or not isinstance(hit.get("_index"), str) or not hit["_index"]:
            raise ElasticsearchError("BM25 비교 결과의 concrete index/document identity가 올바르지 않습니다.", 503)
        identity = (hit["_index"], hit["_id"])
        if identity in identities:
            raise ElasticsearchError("BM25 비교 결과에 중복 문서 identity가 있습니다.", 503)
        identities.add(identity)
        output.append({"_index": identity[0], "_id": identity[1]})
    return output


def mode_comparison(connection: Connection, concept_id: str, query_id: str,
                    profile_id: str | None = None) -> dict[str, Any]:
    """Compare judged-only metrics for one saved query without recording or mutating data."""
    concept = _load_saved_concept_readonly(concept_id)
    saved_query = _saved_query(concept, query_id)
    query_id = saved_query["id"]
    _validate_search_fields(connection, concept)
    all_judgments = _judgments_readonly(concept["id"], concept)
    stale_count = sum(row.get("query_id") == query_id and row.get("stale") for row in all_judgments)
    judgments = [row for row in all_judgments if row.get("query_id") == query_id and not row.get("stale")]
    filters = _normalize_filters(concept, concept["filters"])
    bm25_hits = _complete_comparison_hits(connection, concept, saved_query)
    _, concrete_indices = (vector_mapping_targets(connection, concept["corpus"]["index"], profile_id=profile_id)
                           if profile_id is not None else vector_mapping_targets(connection, concept["corpus"]["index"]))
    vector = (_vector_candidates_for_saved_query(connection, concept, query_id, all_judgments, filters, profile_id)
              if profile_id is not None else _vector_candidates_for_saved_query(connection, concept, query_id, all_judgments, filters))
    if any(hit["_index"] not in concrete_indices for hit in bm25_hits):
        raise ElasticsearchError("BM25 비교 결과의 concrete _index가 alias 매핑 대상에 없습니다.", 503)
    bm25_keys = [_metric_document_key(hit["_index"], hit["_id"]) for hit in bm25_hits]
    vector_keys = [_metric_document_key(hit["_index"], hit["_id"]) for hit in vector["candidates"]]
    k = concept["settings"]["size"]

    def metrics_for(ranking: list[str]) -> dict[str, Any]:
        result = _graded_metrics({query_id: ranking}, judgments, k)
        row = next(item for item in result["queries"] if item["query_id"] == query_id)
        meaningful = "no_judgments" if row["judged_count"] == 0 else "no_positive_judgments" if row["positive_judged_count"] == 0 else "available"
        if meaningful != "available":
            row["ndcg_at_k"] = None
            row["recall_of_judged_relevant_at_k"] = None
            result["ndcg_at_k"] = None
            result["recall_of_judged_relevant_at_k"] = None
        return {"status": meaningful, "k": k, "ndcg_at_k": row["ndcg_at_k"],
                "judged_coverage_at_k": row["judged_coverage_at_k"],
                "recall_of_judged_relevant_at_k": row["recall_of_judged_relevant_at_k"],
                "judged_count": row["judged_count"], "positive_judged_count": row["positive_judged_count"],
                "relevant_found_at_k": row["relevant_found_at_k"], "retrieved_judged_count": row["retrieved_judged_count"],
                "unjudged_retrieved_count": row["unjudged_retrieved_count"],
                "explicit_unjudged_count": row["explicit_unjudged_count"], "stale_judgment_count": stale_count}

    return {"concept_id": concept["id"], "query_id": query_id, "query": saved_query["query"], "split": saved_query["split"],
            "index": concept["corpus"]["index"], "settings_size": k, "effective_filters": filters,
            "filters_fingerprint": _json_hash(filters), "judgments_applied_to_current_filters": True,
            "metrics": {"concept_bm25": metrics_for(bm25_keys), "e5_vector": metrics_for(vector_keys)},
            "vector": {"approximate": True, "exhaustive": False, "model": vector["model"],
                       "profile_id": vector["profile_id"], "recipe": vector["recipe"], "dimensions": vector["dimensions"], "field": vector["field"],
                       "candidate_limit": k, "candidate_count": len(vector_keys), "total": vector["total"]},
            "bm25": {"candidate_count": len(bm25_keys)},
            "limits": ["nDCG는 평가한 문서만으로 계산하며 미평가 문서를 무관(0점)으로 보지 않습니다.",
                       "관련 문서 회수율은 저장된 평가 문서 중 알려진 관련 문서에 한정됩니다.",
                       "두 결과는 현재 저장 필터를 적용했습니다. 평가 당시에도 같은 필터였다는 기록은 아닙니다.",
                       "벡터 결과는 근사 top-K 후보로 전체 코퍼스를 다루지 않습니다. 두 지표 모두 코퍼스 전체 품질을 보장하지 않습니다."]}


def mode_comparison_group(connection: Connection, concept_id: str, query_id: str,
                          profile_id: str | None = None) -> dict[str, Any]:
    """Compare paired read-only retrieval for every saved query in one need group."""
    concept = _load_saved_concept_readonly(concept_id)
    anchor = _saved_query(concept, query_id)
    label = " ".join(anchor.get("information_need", "").split())
    if not label:
        raise ElasticsearchError("선택한 저장 질의에 정보 요구 묶음 이름이 없습니다.")
    group_key = label.casefold()
    members = [item for item in concept["queries"]
               if " ".join(item.get("information_need", "").split()).casefold() == group_key]
    if not 2 <= len(members) <= 10:
        raise ElasticsearchError("정보 요구 묶음 비교에는 저장 질의 2~10개가 필요합니다.")
    splits = {item["split"] for item in members}
    if len(splits) != 1:
        raise ElasticsearchError("정보 요구 묶음의 모든 저장 질의는 같은 사용 방식이어야 합니다.")

    # All saved-group checks happen before any Elasticsearch access.
    _validate_search_fields(connection, concept)
    all_judgments = _judgments_readonly(concept["id"], concept)
    filters = _normalize_filters(concept, concept["filters"])
    k = concept["settings"]["size"]
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for saved_query in members:
        qid = saved_query["id"]
        try:
            concrete_indices = None
            bm25_hits = vector = None
            retrieval_errors: list[Exception] = []
            try:
                _, concrete_indices = (vector_mapping_targets(connection, concept["corpus"]["index"], profile_id=profile_id)
                                       if profile_id is not None else vector_mapping_targets(connection, concept["corpus"]["index"]))
            except Exception as exc:
                retrieval_errors.append(exc)
            # Attempt both sides for every member; if either side fails, discard
            # the whole pair below so a one-sided ranking can never escape.
            try:
                bm25_hits = _complete_comparison_hits(connection, concept, saved_query)
            except Exception as exc:
                retrieval_errors.append(exc)
            try:
                vector = (_vector_candidates_for_saved_query(connection, concept, qid, all_judgments, filters, profile_id)
                          if profile_id is not None else _vector_candidates_for_saved_query(connection, concept, qid, all_judgments, filters))
            except Exception as exc:
                retrieval_errors.append(exc)
            if retrieval_errors:
                raise ElasticsearchError("; ".join(str(error)[:500] for error in retrieval_errors)[:1200], 503, safe_for_user=False)
            assert bm25_hits is not None and vector is not None and concrete_indices is not None
            if any(hit["_index"] not in concrete_indices for hit in bm25_hits):
                raise ElasticsearchError("BM25 비교 결과의 concrete _index가 alias 매핑 대상에 없습니다.", 503)
            bm25_keys = [_metric_document_key(hit["_index"], hit["_id"]) for hit in bm25_hits]
            vector_keys = [_metric_document_key(hit["_index"], hit["_id"]) for hit in vector["candidates"]]
            current = [row for row in all_judgments
                       if row.get("query_id") == qid and not row.get("stale")]
            stale_count = sum(row.get("query_id") == qid and row.get("stale") for row in all_judgments)

            def metrics_for(ranking: list[str]) -> dict[str, Any]:
                aggregate = _graded_metrics({qid: ranking}, current, k)
                row = next(item for item in aggregate["queries"] if item["query_id"] == qid)
                status = "no_judgments" if row["judged_count"] == 0 else (
                    "no_positive_judgments" if row["positive_judged_count"] == 0 else "available")
                return {"status": status, "k": k,
                        "ndcg_at_k": row["ndcg_at_k"] if status == "available" else None,
                        "judged_coverage_at_k": row["judged_coverage_at_k"],
                        "recall_of_judged_relevant_at_k": row["recall_of_judged_relevant_at_k"] if status == "available" else None,
                        "judged_count": row["judged_count"], "positive_judged_count": row["positive_judged_count"],
                        "relevant_found_at_k": row["relevant_found_at_k"],
                        "retrieved_judged_count": row["retrieved_judged_count"],
                        "unjudged_retrieved_count": row["unjudged_retrieved_count"],
                        "explicit_unjudged_count": row["explicit_unjudged_count"],
                        "stale_judgment_count": stale_count}

            results.append({"query_id": qid, "query": saved_query["query"], "split": saved_query["split"],
                            "status": "complete",
                            "metrics": {"concept_bm25": metrics_for(bm25_keys), "e5_vector": metrics_for(vector_keys)},
                            "vector": {"approximate": True, "exhaustive": False, "model": vector["model"],
                                       "profile_id": vector["profile_id"], "recipe": vector["recipe"], "dimensions": vector["dimensions"],
                                       "field": vector["field"], "candidate_limit": k,
                                       "candidate_count": len(vector_keys), "total": vector["total"]},
                            "bm25": {"candidate_count": len(bm25_keys)}})
        except Exception as exc:
            message = _public_failure_message(exc, "이 저장 질의의 두 검색을 완료하지 못했습니다.")
            failures.append({"query_id": qid, "query": saved_query["query"],
                             "split": saved_query["split"], "error": message})

    selected_count = len(members)
    completed_count = len(results)
    failed_count = len(failures)
    aggregate_metrics: dict[str, dict[str, dict[str, Any]]] | None = None
    if failed_count == 0:
        aggregate_metrics = {}
        metric_fields = ("ndcg_at_k", "judged_coverage_at_k", "recall_of_judged_relevant_at_k")
        for field in metric_fields:
            aggregate_metrics[field] = {}
            for mode in ("concept_bm25", "e5_vector"):
                if field == "judged_coverage_at_k":
                    eligible = [row["metrics"][mode][field] for row in results
                                if row["metrics"][mode]["judged_count"] > 0]
                else:
                    eligible = [row["metrics"][mode][field] for row in results
                                if row["metrics"][mode]["positive_judged_count"] > 0]
                aggregate_metrics[field][mode] = {
                    "mean": sum(eligible) / len(eligible) if eligible else None,
                    "query_count": len(eligible), "selected_query_count": selected_count,
                }
    return {"concept_id": concept["id"], "anchor_query_id": anchor["id"],
            "information_need": label, "split": anchor["split"], "index": concept["corpus"]["index"],
            "settings_size": k, "effective_filters": filters,
            "selected_count": selected_count, "completed_count": completed_count,
            "failed_count": failed_count, "status": "complete" if not failed_count else "partial",
            "queries": results, "failures": failures, "aggregate": aggregate_metrics,
            "limits": ["질의별 평균은 각 저장 질의를 같은 비중으로 계산하며, 실제 사용 빈도를 반영하지 않습니다.",
                       "nDCG는 평가한 문서만으로 계산하며 미평가 문서를 무관(0점)으로 보지 않습니다.",
                       "관련 문서 회수율은 저장된 평가 문서 중 알려진 관련 문서에 한정됩니다.",
                       "현재 저장 필터를 적용하며 평가 당시에도 같은 필터였다는 기록은 아닙니다.",
                       "E5 벡터 결과는 근사 top-K 후보이며 코퍼스 전체 품질을 보장하지 않습니다.",
                       "이 비교는 검색 결과 순위만 평가하며 생성된 RAG 답변의 품질을 평가하지 않습니다."]}


def save_judgment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ElasticsearchError("judgment 요청은 object여야 합니다.")
    fields = [str(value.get(key, "")).strip() for key in ("concept_id", "query_id", "document_index")]
    raw_document_id = value.get("document_id")
    if not isinstance(raw_document_id, (str, int)) or isinstance(raw_document_id, bool):
        raise ElasticsearchError("document_id는 문자열 또는 정수여야 합니다.")
    document_id = str(raw_document_id)
    if any(not item for item in fields) or document_id == "":
        raise ElasticsearchError("concept_id, query_id, document_index, document_id가 필요합니다.")
    with _connect_db() as db:
        row = db.execute("SELECT body FROM concepts WHERE id=?", (fields[0],)).fetchone()
    if not row:
        raise ElasticsearchError("저장된 concept id를 찾을 수 없습니다.")
    saved_concept = json.loads(row["body"])
    if fields[1] not in {item["id"] for item in saved_concept.get("queries", [])}:
        raise ElasticsearchError("query_id는 저장된 concept query여야 합니다.")
    if len(document_id.encode("utf-8")) > 512:
        raise ElasticsearchError("document_id는 UTF-8 기준 512 bytes 이하여야 합니다.")
    rating = value.get("rating")
    if rating is not None:
        rating = _bounded_int(rating, 0, 3, "rating")
    pinned_value = value.get("pinned", False)
    if not isinstance(pinned_value, bool):
        raise ElasticsearchError("pinned 값은 boolean이어야 합니다.")
    pinned = pinned_value
    reason = str(value.get("reason", ""))[:1000]
    judgment = {"concept_id": fields[0], "query_id": fields[1], "document_index": validate_index(fields[2]), "document_id": document_id, "rating": rating, "pinned": pinned, "reason": reason, "updated_at": _now()}
    query_entry = next(item for item in saved_concept["queries"] if item["id"] == fields[1])
    query_fingerprint = _query_judgment_fingerprint(query_entry)
    judgment["query_fingerprint"] = query_fingerprint
    with _connect_db() as db:
        db.execute("INSERT INTO judgments(concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at,query_fingerprint) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(concept_id,query_id,document_index,document_id) DO UPDATE SET rating=excluded.rating,pinned=excluded.pinned,reason=excluded.reason,updated_at=excluded.updated_at,query_fingerprint=excluded.query_fingerprint", (*fields, document_id, rating, int(pinned), reason, judgment["updated_at"], query_fingerprint))
    return {"judgment": judgment}


def _judgments(concept_id: str, concept: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with _connect_db() as db:
        rows = db.execute("SELECT * FROM judgments WHERE concept_id=?", (concept_id,)).fetchall()
    result = [dict(row) for row in rows]
    if concept is not None:
        current = {item["id"]: _query_judgment_fingerprint(item) for item in concept["queries"]}
        for row in result:
            row["stale"] = row["query_id"] not in current or current[row["query_id"]] != row["query_fingerprint"]
    return result


def _judgments_readonly(concept_id: str, concept: dict[str, Any]) -> list[dict[str, Any]]:
    """Read judgments without creating a DB, schema, or journal side effect."""
    # Resolve through the request-bound owner scope so an account can only
    # inspect its own state database. _db_path() resolves identity but does not
    # open or initialize that database; keep the existence check before opening
    # SQLite in read-only URI mode below.
    path = _db_path()
    if not path.is_file():
        raise ElasticsearchError("저장된 평가 데이터베이스를 읽을 수 없습니다.", 503)
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(judgments)")}
        if not {"concept_id", "query_id", "rating"}.issubset(columns):
            raise ElasticsearchError("저장된 평가 테이블을 읽을 수 없습니다.", 503)
        try:
            rows = db.execute("SELECT * FROM judgments WHERE concept_id=?", (concept_id,)).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table: judgments" in str(error).lower():
                raise ElasticsearchError("저장된 평가 테이블을 읽을 수 없습니다.", 503) from None
            raise
    finally:
        db.close()
    result = [dict(row) for row in rows]
    current = {item["id"]: _query_judgment_fingerprint(item) for item in concept["queries"]}
    for row in result:
        row["stale"] = row["query_id"] not in current or current[row["query_id"]] != row.get("query_fingerprint", "")
    return result


def tune_readiness(concept_value: Any) -> dict[str, Any]:
    """Report aggregate label eligibility without connecting to Elasticsearch."""
    concept = validate_concept(concept_value)
    judgments = _judgments_readonly(concept["id"], concept)
    query_map = {item["id"]: item for item in concept["queries"]}
    current = [row for row in judgments if not row.get("stale")]
    query_coverage = {
        split: {"graded": set(), "positive": set()}
        for split in ("train", "validation")
    }
    counts = {
        "training_queries": len({item["id"] for item in concept["queries"] if item["split"] == "train"}),
        "training_graded": 0,
        "training_positive": 0,
        "training_graded_queries": 0,
        "training_positive_queries": 0,
        "validation_queries": len({item["id"] for item in concept["queries"] if item["split"] == "validation"}),
        "validation_graded": 0,
        "validation_positive": 0,
        "validation_graded_queries": 0,
        "validation_positive_queries": 0,
        "training_information_need_groups": 0,
        "training_graded_information_need_groups": 0,
        "training_positive_information_need_groups": 0,
        "validation_information_need_groups": 0,
        "validation_graded_information_need_groups": 0,
        "validation_positive_information_need_groups": 0,
        "stale": sum(bool(row.get("stale")) for row in judgments),
    }
    group_by_query: dict[str, str] = {}
    information_need_groups = {"train": set(), "validation": set()}
    for query in concept["queries"]:
        split = query["split"]
        label = query.get("information_need", "")
        group_key = f"label:{label.casefold()}" if label else f"query:{query['id']}"
        group_by_query[query["id"]] = group_key
        information_need_groups[split].add(group_key)
    for split, prefix in (("train", "training"), ("validation", "validation")):
        counts[f"{prefix}_information_need_groups"] = len(information_need_groups[split])
    group_coverage = {
        split: {"graded": set(), "positive": set()}
        for split in ("train", "validation")
    }
    for row in current:
        if row.get("rating") is None:
            continue
        split = query_map.get(row["query_id"], {}).get("split")
        if split not in {"train", "validation"}:
            continue
        count_prefix = "training" if split == "train" else "validation"
        counts[f"{count_prefix}_graded"] += 1
        query_coverage[split]["graded"].add(row["query_id"])
        group_coverage[split]["graded"].add(group_by_query[row["query_id"]])
        if row["rating"] > 0:
            counts[f"{count_prefix}_positive"] += 1
            query_coverage[split]["positive"].add(row["query_id"])
            group_coverage[split]["positive"].add(group_by_query[row["query_id"]])
    counts["training_graded_queries"] = len(query_coverage["train"]["graded"])
    counts["training_positive_queries"] = len(query_coverage["train"]["positive"])
    counts["validation_graded_queries"] = len(query_coverage["validation"]["graded"])
    counts["validation_positive_queries"] = len(query_coverage["validation"]["positive"])
    counts["training_graded_information_need_groups"] = len(group_coverage["train"]["graded"])
    counts["training_positive_information_need_groups"] = len(group_coverage["train"]["positive"])
    counts["validation_graded_information_need_groups"] = len(group_coverage["validation"]["graded"])
    counts["validation_positive_information_need_groups"] = len(group_coverage["validation"]["positive"])
    eligible = counts["training_positive"] > 0
    return {
        "eligible": eligible,
        "reason_code": "train_positive_available" if eligible else "train_positive_required",
        "counts": counts,
        "scope": "label_readiness_only",
    }


def _store_run(concept_id: str, kind: str, body: dict[str, Any], run_id: str | None = None) -> str:
    run_id = run_id or str(uuid.uuid4())
    body = {**body, "reproducibility": {**body.get("reproducibility", {}), "stored_at": _now()}}
    with _connect_db() as db:
        db.execute("INSERT INTO runs(id,concept_id,created_at,kind,body) VALUES(?,?,?,?,?)", (run_id, concept_id, _now(), kind, json.dumps(body, ensure_ascii=False, allow_nan=False)))
    return run_id


def _metric_document_key(document_index: Any, document_id: Any) -> str:
    """Encode exact concrete index/ID identity without delimiter collisions."""
    return json.dumps([str(document_index), str(document_id)], ensure_ascii=False, separators=(",", ":"))


def _graded_metrics(rankings: dict[str, list[str]], judgments: list[dict[str, Any]], k: int) -> dict[str, Any]:
    by_query: dict[str, dict[str, int]] = {}
    explicit_unjudged: dict[str, int] = {}
    for row in judgments:
        key = _metric_document_key(row["document_index"], row["document_id"])
        # A pin is a placement preference, never a grade. A separately entered
        # non-null rating remains valid evidence even when the document is pinned.
        if row["rating"] is not None:
            by_query.setdefault(row["query_id"], {})[key] = int(row["rating"])
        else:
            explicit_unjudged[row["query_id"]] = explicit_unjudged.get(row["query_id"], 0) + 1
    rows = []
    for query_id in sorted(set(by_query) | set(rankings) | set(explicit_unjudged)):
        grades = by_query.get(query_id, {})
        ranked = rankings.get(query_id, [])[:k]
        # nDCG is computed on the condensed judged-only ranking. Unknown
        # documents do not count as gains or as zero-grade evidence.
        condensed = [doc for doc in ranked if doc in grades][:k]
        dcg = sum((2**grades[doc] - 1) / math.log2(rank + 1) for rank, doc in enumerate(condensed, 1))
        ideal = sorted(grades.values(), reverse=True)[:k]
        idcg = sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1))
        judged_retrieved = sum(doc in grades for doc in ranked)
        unjudged_retrieved = sum(doc not in grades for doc in ranked)
        relevant = sum(grade > 0 for grade in grades.values())
        found_relevant = sum(grades.get(doc, 0) > 0 for doc in ranked)
        rows.append({"query_id": query_id, "judged_count": len(grades), "positive_judged_count": relevant, "relevant_found_at_k": found_relevant, "explicit_unjudged_count": explicit_unjudged.get(query_id, 0), "retrieved_judged_count": judged_retrieved, "unjudged_retrieved_count": unjudged_retrieved, "judged_coverage_at_k": judged_retrieved / min(k, len(ranked)) if ranked else 0.0, "recall_of_judged_relevant_at_k": found_relevant / relevant if relevant else 0.0, "ndcg_at_k": dcg / idcg if idcg else 0.0})
    return {"k": k, "query_count": len(rows), "judged_count": sum(row["judged_count"] for row in rows), "positive_judged_count": sum(row["positive_judged_count"] for row in rows), "relevant_found_at_k": sum(row["relevant_found_at_k"] for row in rows), "queries_with_positive_judgments": sum(row["positive_judged_count"] > 0 for row in rows), "queries_with_relevant_found": sum(row["relevant_found_at_k"] > 0 for row in rows), "explicit_unjudged_count": sum(explicit_unjudged.values()), "retrieved_judged_count": sum(row["retrieved_judged_count"] for row in rows), "unjudged_retrieved_count": sum(row["unjudged_retrieved_count"] for row in rows), "ndcg_at_k": sum(row["ndcg_at_k"] for row in rows) / len(rows) if rows else 0.0, "judged_coverage_at_k": sum(row["judged_coverage_at_k"] for row in rows) / len(rows) if rows else 0.0, "recall_of_judged_relevant_at_k": sum(row["recall_of_judged_relevant_at_k"] for row in rows) / len(rows) if rows else 0.0, "queries": rows}


TUNE_ALGORITHM_VERSION = "bounded-validation-selection-v1"
TUNE_MAX_CANDIDATES = 30
TUNE_MAX_SECONDS = 600


class _TuneTimeBudgetExpired(Exception):
    pass


def _tune_candidates(base_settings: dict[str, Any], train_query_ids: list[str], limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Return a stable train-independent configuration grid with baseline first.

    The train IDs are intentionally the only split information accepted here;
    validation and any possible held-out split cannot affect candidate order.
    """
    del train_query_ids  # eligibility is checked by tune before calling this helper
    axes: dict[str, list[float]] = {}
    for key in ("concept_weight", "related_weight"):
        current = float(base_settings.get(key, 1.0))
        axes[key] = sorted({0.0, 1.0, *(max(0.0, min(20.0, current * factor)) for factor in (0.5, 0.75, 1.0, 1.5, 2.0))})
    generated: dict[str, dict[str, Any]] = {}
    for concept_weight in axes["concept_weight"]:
        for related_weight in axes["related_weight"]:
            item = {**base_settings, "concept_weight": concept_weight, "related_weight": related_weight}
            key = json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False)
            generated[key] = item
    baseline_key = json.dumps(base_settings, sort_keys=True, separators=(",", ":"), allow_nan=False)
    ordered = [dict(base_settings)]
    ordered.extend(generated[key] for key in sorted(generated) if key != baseline_key)
    return ordered[:limit], len(ordered) > limit


def _validation_diagnostics(baseline: dict[str, Any] | None, selected: dict[str, Any] | None,
                            judgments: list[dict[str, Any]], query_map: dict[str, dict[str, Any]],
                            baseline_rankings: dict[str, list[str]], selected_rankings: dict[str, list[str]],
                            k: int, *, failure: str | None = None) -> list[dict[str, Any]]:
    val_ids = {qid for qid, query in query_map.items() if query.get("split") == "validation"}
    val_judgments = [row for row in judgments if row.get("query_id") in val_ids and not row.get("stale")]
    explicit_unjudged = {(row["query_id"], _metric_document_key(row["document_index"], row["document_id"]))
                         for row in val_judgments if row.get("rating") is None}
    by_query: dict[str, dict[str, int]] = {}
    for row in val_judgments:
        if row.get("rating") is not None:
            by_query.setdefault(row["query_id"], {})[_metric_document_key(row["document_index"], row["document_id"])] = int(row["rating"])
    baseline_rows = {row.get("query_id"): row for row in (baseline or {}).get("queries", [])}
    selected_rows = {row.get("query_id"): row for row in (selected or {}).get("queries", [])}

    def document_refs(keys: set[str], grades: dict[str, int]) -> list[dict[str, Any]]:
        items = []
        for key in sorted(keys):
            index, document_id = json.loads(key)
            items.append({"document_index": index, "document_id": document_id, "rating": grades.get(key)})
        return items

    def unjudged_count(qid: str, ranked: list[str], grades: dict[str, int]) -> int:
        # Both explicit-unjudged and absent judgments are unknown evidence.
        return sum(doc not in grades or (qid, doc) in explicit_unjudged for doc in ranked)

    rows = []
    for qid in sorted(val_ids):
        query = query_map[qid]
        grades = by_query.get(qid, {})
        relevant = {doc for doc, grade in grades.items() if grade > 0}
        before = baseline_rankings.get(qid, [])[:k]
        after = selected_rankings.get(qid, [])[:k]
        before_found, after_found = relevant & set(before), relevant & set(after)
        b_metrics, s_metrics = baseline_rows.get(qid, {}), selected_rows.get(qid, {})
        metric_deltas = {}
        for metric in ("ndcg_at_k", "judged_coverage_at_k", "recall_of_judged_relevant_at_k"):
            before_value, after_value = b_metrics.get(metric), s_metrics.get(metric)
            metric_deltas[metric] = after_value - before_value if isinstance(before_value, (int, float)) and isinstance(after_value, (int, float)) else None
        stale_count = sum(bool(row.get("stale")) for row in judgments if row.get("query_id") == qid)
        time_limited = bool(failure and "time budget" in failure.casefold())
        status = "failed" if failure and not time_limited else ("incomplete" if time_limited or not b_metrics or not s_metrics or len(grades) == 0 else "ok")
        incomplete_categories = ["qrels_incomplete"]
        if not grades:
            incomplete_categories.append("no_current_validation_judgments")
        if stale_count:
            incomplete_categories.append("stale_judgments_excluded")
        error_categories = ["time_budget"] if time_limited else (["validation_failed"] if failure else [])
        rows.append({
            "query_id": qid,
            "query": query["query"],
            "status": status,
            "metric_deltas": metric_deltas,
            "baseline_missed_known_relevant": document_refs(relevant - before_found, grades),
            "selected_missed_known_relevant": document_refs(relevant - after_found, grades),
            "missed_relevant_added": document_refs(before_found - after_found, grades),
            "missed_relevant_fixed": document_refs(after_found - before_found, grades),
            "baseline_retrieved_unjudged_count": unjudged_count(qid, before, grades),
            "selected_retrieved_unjudged_count": unjudged_count(qid, after, grades),
            "stale_judgment_count": stale_count,
            "incomplete_categories": incomplete_categories,
            "error_categories": error_categories,
            "errors": [failure] if failure else [],
            "qrels_limit": "Known-relevant judged targets only; absent and explicit-unjudged documents are unknown, not nonrelevant.",
        })
    return rows


def tune(connection: Connection, concept_value: Any, passes: Any = 2, *, max_candidates: Any = 30,
         time_budget_seconds: Any = 600, _clock: Any = None) -> dict[str, Any]:
    max_candidates = _bounded_int(max_candidates, 1, TUNE_MAX_CANDIDATES, "max_candidates")
    time_budget_seconds = _bounded_int(time_budget_seconds, 1, TUNE_MAX_SECONDS, "time_budget_seconds")
    clock = _clock or time.monotonic
    started = clock()
    deadline = started + time_budget_seconds
    concept = validate_concept(concept_value)
    def remaining_timeout() -> float:
        remaining = deadline - clock()
        if remaining <= 0:
            raise _TuneTimeBudgetExpired()
        return max(0.001, min(30.0, remaining))
    try:
        schema = _validate_search_fields(connection, concept, timeout=remaining_timeout())
    except _TuneTimeBudgetExpired:
        raise ElasticsearchError("Tuning stopped with stop_reason=time_budget during mapping preflight; no candidate search ran.", 408) from None
    except ElasticsearchError:
        if clock() >= deadline:
            raise ElasticsearchError("Tuning stopped with stop_reason=time_budget during mapping preflight; no candidate search ran.", 408) from None
        raise
    # Kept for compatibility with older clients; the deterministic finite grid
    # supersedes pass-based coordinate iteration.
    _bounded_int(passes, 1, 3, "passes")
    judgments = _judgments(concept["id"], concept)
    stale_count = sum(bool(row.get("stale")) for row in judgments)
    all_judgments = judgments
    judgments = [row for row in judgments if not row.get("stale")]
    judged = [row for row in judgments if row["rating"] is not None]
    pinned_count = sum(bool(row["pinned"]) for row in judgments)
    query_map = {item["id"]: item for item in concept["queries"]}
    if not judged:
        raise ElasticsearchError("튜닝 전에 문서를 0~3으로 평가하세요.")
    unknown_queries = sorted({row["query_id"] for row in judged if row["query_id"] not in query_map})
    if unknown_queries:
        raise ElasticsearchError("평가에 연결된 저장 query가 없습니다: " + ", ".join(unknown_queries[:10]))
    base_settings = dict(concept["settings"])
    metrics_cache: dict[tuple[str | None, str], dict[str, Any]] = {}
    output_cache: dict[tuple[str | None, str], dict[str, list[dict[str, Any]]]] = {}
    rankings_cache: dict[tuple[str, str], dict[str, list[str]]] = {}
    def evaluate_settings(settings: dict[str, Any], split: str) -> dict[str, Any]:
        if clock() >= deadline:
            raise _TuneTimeBudgetExpired()
        cache_key = (split, json.dumps(settings, sort_keys=True, separators=(",", ":")))
        if cache_key in metrics_cache:
            return metrics_cache[cache_key]
        selected = [row for row in judgments if query_map.get(row["query_id"], {}).get("split") == split]
        rankings = {}
        output_rows: dict[str, list[dict[str, Any]]] = {}
        for query_id in sorted({row["query_id"] for row in selected}):
            if clock() >= deadline:
                raise _TuneTimeBudgetExpired()
            query_text = query_map[query_id]["query"]
            temp = {**concept, "settings": settings}
            remaining = deadline - clock()
            if remaining <= 0:
                raise _TuneTimeBudgetExpired()
            remaining = max(0.001, min(30.0, remaining))
            result = _hits(connection, concept["corpus"]["index"], query_text, settings["candidate_size"], temp,
                           filters=concept["filters"], timeout=remaining)
            rankings[query_id] = [
                _metric_document_key(hit.get("_index", concept["corpus"]["index"]), hit["_id"])
                for hit in result["hits"]
            ]
            output_rows[query_id] = [{"index": hit.get("_index"), "id": hit.get("_id"), "rank": hit.get("rank"), "source_sha256": hit.get("source_sha256")} for hit in result["hits"][:settings["size"]]]
        metrics = _graded_metrics(rankings, selected, settings["size"])
        metrics["unjudged_count"] = sum(row["rating"] is None for row in judgments if split is None or query_map.get(row["query_id"], {}).get("split") == split)
        metrics["ndcg_policy"] = "condensed judged-only organic ranking; unjudged documents are omitted from nDCG and do not imply grade 0"
        metrics["coverage_policy"] = "judged_coverage_at_k and recall_of_judged_relevant_at_k report observed judged coverage separately; pins do not change organic rankings"
        metrics_cache[cache_key] = metrics
        output_cache[cache_key] = output_rows
        rankings_cache[cache_key] = rankings
        return metrics
    train_positive_count = sum(row["rating"] > 0 for row in judged if query_map[row["query_id"]]["split"] == "train")
    if not train_positive_count:
        raise ElasticsearchError("튜닝에는 train split의 양수(1~3) graded relevance가 하나 이상 필요합니다.")
    try:
        baseline = evaluate_settings(base_settings, "train")
    except _TuneTimeBudgetExpired:
        raise ElasticsearchError("Tuning stopped with stop_reason=time_budget before baseline train evaluation completed.", 408) from None
    except ElasticsearchError:
        if clock() >= deadline:
            raise ElasticsearchError("Tuning stopped with stop_reason=time_budget before baseline train evaluation completed.", 408) from None
        raise
    if not baseline["query_count"]:
        raise ElasticsearchError("튜닝에는 train split의 유효한 graded judgment가 하나 이상 필요합니다.")
    train_query_ids = sorted({row["query_id"] for row in judged if query_map[row["query_id"]]["split"] == "train"})
    candidates, candidate_truncated = _tune_candidates(base_settings, train_query_ids, max_candidates)
    candidate_trace: list[dict[str, Any]] = []
    candidate_rankings: dict[str, dict[str, list[str]]] = {}
    stop_reason = "completed"
    baseline_validation: dict[str, Any] | None = None
    baseline_validation_error: str | None = None
    selection = {"selected_candidate_id": "baseline", "reason": "validation_unavailable"}
    baseline_tie_seen = False
    for position, settings in enumerate(candidates):
        candidate_id = "baseline" if position == 0 else f"candidate-{position:03d}"
        entry: dict[str, Any] = {"candidate_id": candidate_id, "settings": settings, "train_metrics": None,
                                 "validation_metrics": None, "evaluation_status": "pending"}
        candidate_trace.append(entry)
        try:
            if position == 0:
                train_metrics = baseline
            else:
                train_metrics = evaluate_settings(settings, "train")
            entry["train_metrics"] = train_metrics
            candidate_rankings[candidate_id] = rankings_cache.get(("train", json.dumps(settings, sort_keys=True, separators=(",", ":"))), {})
            val_judged = [row for row in judged if query_map[row["query_id"]]["split"] == "validation"]
            val_positive = any(row["rating"] > 0 for row in val_judged)
            if not val_judged:
                entry["evaluation_status"] = "validation_unavailable"
                entry["validation_error"] = "no_validation_judgments"
                if position == 0:
                    selection = {"selected_candidate_id": "baseline", "reason": "validation_unavailable"}
                continue
            if not val_positive:
                entry["evaluation_status"] = "validation_no_positive_judgments"
                entry["validation_error"] = "no_validation_positive_judgments"
                if position == 0:
                    selection = {"selected_candidate_id": "baseline", "reason": "validation_unavailable"}
                continue
            val_metrics = evaluate_settings(settings, "validation")
            entry["validation_metrics"] = val_metrics
            entry["evaluation_status"] = "evaluated"
            candidate_rankings[candidate_id] = {**candidate_rankings.get(candidate_id, {}), "validation": rankings_cache.get(("validation", json.dumps(settings, sort_keys=True, separators=(",", ":"))), {})}
            if position == 0:
                baseline_validation = val_metrics
                entry["validation_metrics"] = val_metrics
                selection = {"selected_candidate_id": "baseline", "reason": "baseline_retained_tie"}
            elif baseline_validation is not None:
                baseline_key = (baseline_validation["ndcg_at_k"], baseline_validation["judged_coverage_at_k"])
                candidate_key = (val_metrics["ndcg_at_k"], val_metrics["judged_coverage_at_k"])
                baseline_tie_seen = baseline_tie_seen or candidate_key == baseline_key
                selected_metrics = next((row.get("validation_metrics") for row in candidate_trace if row["candidate_id"] == selection["selected_candidate_id"]), None)
                selected_key = ((selected_metrics or {}).get("ndcg_at_k", float("-inf")),
                                (selected_metrics or {}).get("judged_coverage_at_k", float("-inf")))
                if candidate_key > baseline_key and candidate_key > selected_key:
                    selection = {"selected_candidate_id": candidate_id, "reason": "candidate_selected"}
        except _TuneTimeBudgetExpired:
            entry["evaluation_status"] = "not_evaluated_time_budget"
            stop_reason = "time_budget"
            break
        except Exception as exc:
            if clock() >= deadline:
                entry["evaluation_status"] = "not_evaluated_time_budget"
                stop_reason = "time_budget"
                break
            entry["evaluation_status"] = "failed"
            entry["error"] = _public_failure_message(exc, "candidate_evaluation_failed")
            if position == 0:
                baseline_validation_error = entry["error"]
                selection = {"selected_candidate_id": "baseline", "reason": "validation_failed"}
    if clock() >= deadline:
        stop_reason = "time_budget"
    if stop_reason != "time_budget" and candidate_truncated:
        stop_reason = "candidate_budget"
    incomplete_candidate = stop_reason == "time_budget" or any(row.get("evaluation_status") in {"failed", "not_evaluated_time_budget"} for row in candidate_trace)
    if incomplete_candidate:
        selection = {"selected_candidate_id": "baseline",
                     "reason": "validation_unavailable" if selection["reason"] == "validation_unavailable" else "validation_failed"}
    elif selection["selected_candidate_id"] == "baseline" and selection["reason"] not in {"validation_unavailable", "validation_failed"}:
        selection = {"selected_candidate_id": "baseline", "reason": "baseline_retained_tie" if baseline_tie_seen else "no_candidate_improved"}
    selected_id = selection["selected_candidate_id"]
    selected_entry = next((row for row in candidate_trace if row["candidate_id"] == selected_id), candidate_trace[0])
    best_settings = dict(selected_entry["settings"])
    best_metrics = selected_entry["train_metrics"] or baseline
    validation_tuned = selected_entry["validation_metrics"]
    validation_metrics = {"baseline": baseline_validation, "tuned": validation_tuned} if baseline_validation and validation_tuned else None
    explicit_unjudged_count = sum(row["rating"] is None for row in judgments)
    unjudged_retrieved_count = best_metrics["unjudged_retrieved_count"]
    train_metrics = {"baseline": baseline, "tuned": best_metrics}
    concept_fingerprint = _json_hash(concept)
    train_baseline_key = ("train", json.dumps(base_settings, sort_keys=True, separators=(",", ":")))
    train_tuned_key = ("train", json.dumps(best_settings, sort_keys=True, separators=(",", ":")))
    validation_baseline_key = ("validation", json.dumps(base_settings, sort_keys=True, separators=(",", ":")))
    validation_tuned_key = ("validation", json.dumps(best_settings, sort_keys=True, separators=(",", ":")))
    safe_concept = {key: value for key, value in concept.items() if not key.startswith("_")}
    judgment_snapshot = [{key: row[key] for key in ("concept_id", "query_id", "document_index", "document_id", "rating", "pinned", "reason", "query_fingerprint", "stale") if key in row} for row in all_judgments]
    output_snapshot: dict[str, Any] = {"train": {"baseline": output_cache.get(train_baseline_key, {}), "tuned": output_cache.get(train_tuned_key, {})}}
    if validation_metrics is not None:
        output_snapshot["validation"] = {"baseline": output_cache.get(validation_baseline_key, {}), "tuned": output_cache.get(validation_tuned_key, {})}
    for entry in candidate_trace:
        settings_key = json.dumps(entry["settings"], sort_keys=True, separators=(",", ":"))
        entry["fingerprints"] = {
            "settings": _json_hash(entry["settings"]),
            "train_metrics": _json_hash(entry["train_metrics"]) if entry["train_metrics"] is not None else None,
            "validation_metrics": _json_hash(entry["validation_metrics"]) if entry["validation_metrics"] is not None else None,
            "train_output": _json_hash(output_cache.get(("train", settings_key), {})),
            "validation_output": _json_hash(output_cache.get(("validation", settings_key), {})),
        }
    baseline_rankings = rankings_cache.get(validation_baseline_key, {})
    selected_rankings = rankings_cache.get(validation_tuned_key, {}) if validation_metrics is not None else baseline_rankings
    diagnostic_failure = baseline_validation_error or next((row.get("error") for row in candidate_trace if row.get("evaluation_status") == "failed"), None)
    if stop_reason == "time_budget" and not diagnostic_failure:
        diagnostic_failure = "Validation work stopped at the configured time budget; remaining candidates were not evaluated."
    validation_diagnostics = _validation_diagnostics(baseline_validation, validation_tuned, all_judgments, query_map,
        baseline_rankings, selected_rankings, base_settings["size"], failure=diagnostic_failure)
    try:
        index_timeout = remaining_timeout()
    except _TuneTimeBudgetExpired:
        index_timeout = None
    if index_timeout is not None:
        index_identity, identity_warning = _index_identity(connection, concept["corpus"]["index"], timeout=index_timeout)
    else:
        index_identity = {"requested_index": concept["corpus"]["index"], "uuids": [], "available": False}
        identity_warning = "Elasticsearch index UUID lookup was skipped because no time remained after candidate evaluation."
    elapsed_ms = max(0, int((clock() - started) * 1000))
    tuning_budget = {"max_candidates": max_candidates, "time_budget_seconds": time_budget_seconds,
                     "candidates_evaluated": sum(row.get("train_metrics") is not None for row in candidate_trace),
                     "elapsed_ms": elapsed_ms, "stop_reason": stop_reason}
    run_body = {"settings": best_settings, "filters": concept["filters"], "effective_filters": concept["filters"], "baseline": baseline, "tuned": best_metrics, "train": train_metrics, "validation": validation_metrics, "candidate_trace": candidate_trace, "selection": selection, "validation_diagnostics": validation_diagnostics, "tuning_budget": tuning_budget, "judged_count": len(judged), "explicit_unjudged_count": explicit_unjudged_count, "unjudged_retrieved_count": unjudged_retrieved_count, "pinned_count": pinned_count, "input_snapshot": {"concept": safe_concept, "judgments": judgment_snapshot}, "output_snapshot": output_snapshot, "reproducibility": {"index": concept["corpus"]["index"], "index_identity": index_identity, "mapping_fingerprint": _json_hash(schema["fields"]), "query_fingerprint": _json_hash(concept["queries"]), "concept_fingerprint": concept_fingerprint, "filters_fingerprint": _json_hash(concept["filters"]), "judgment_fingerprint": _json_hash(all_judgments), "settings_fingerprint": _json_hash(base_settings), "candidate_trace_fingerprint": _json_hash(candidate_trace), "output_snapshot_fingerprint": _json_hash(output_snapshot), "algorithm": TUNE_ALGORITHM_VERSION}}
    run_id = _store_run(concept["id"], "tune", run_body)
    warnings = []
    if validation_metrics is None:
        warnings.append("Validation judgments are unavailable; results are training-only and do not establish generalization.")
    if identity_warning:
        warnings.append(identity_warning)
    warnings.append("nDCG uses a condensed judged-only organic ranking. Unjudged documents are not treated as irrelevant; explicit unjudged rows and unjudged retrieved documents are counted separately. Pins affect placement only and do not alter organic ranks.")
    if stale_count:
        warnings.append(f"{stale_count} judgments were excluded because their saved query text has changed or was removed.")
    warning_codes = ["judged_only_ndcg"]
    if validation_metrics is None:
        warning_codes.append("validation_unavailable")
    if identity_warning:
        warning_codes.append("index_identity_unavailable")
    if stale_count:
        warning_codes.append("stale_judgments")
    result = {"run_id": run_id, **run_body, "warnings": warnings, "warning_codes": warning_codes}
    result["plain_summary"] = _plain_tune_summary(result)
    return result


def _plain_tune_summary(result: dict[str, Any]) -> dict[str, Any]:
    train = result.get("train", {})
    before, after = train.get("baseline", {}), train.get("tuned", {})
    before_ndcg = float(before.get("ndcg_at_k", 0))
    after_ndcg = float(after.get("ndcg_at_k", 0))
    before_found, after_found = int(before.get("relevant_found_at_k", 0)), int(after.get("relevant_found_at_k", 0))
    positive_count = int(after.get("positive_judged_count", 0))
    query_count = int(after.get("queries_with_positive_judgments", 0))
    if after_found > before_found:
        headline = f"관련 있다고 평가한 문서가 기준선 {before_found}/{positive_count}개에서 조정 후 {after_found}/{positive_count}개 검색 결과에 나타났습니다 ({query_count}개 학습 질의)."
    elif after_found < before_found:
        headline = f"관련 있다고 평가한 문서가 기준선 {before_found}/{positive_count}개에서 조정 후 {after_found}/{positive_count}개 검색 결과에 나타났습니다 ({query_count}개 학습 질의)."
    else:
        headline = f"관련 있다고 평가한 문서는 기준선과 조정 후 모두 {after_found}/{positive_count}개가 검색 결과에 나타났습니다 ({query_count}개 학습 질의)."
    regressions = []
    before_rows = {row.get("query_id"): row for row in before.get("queries", [])}
    for row in after.get("queries", []):
        prior = before_rows.get(row.get("query_id"))
        if prior and row.get("ndcg_at_k", 0) < prior.get("ndcg_at_k", 0):
            regressions.append(str(row.get("query_id")))
    details = [f"학습 자료: {after.get('query_count', 0)}개 질의와 {after.get('judged_count', 0)}개 문서 평가가 있습니다. 관련 있다고 표시한 문서가 있는 질의는 {query_count}개입니다.", f"검색 결과에 나타난 관련 평가 문서: 기준선 {before_found}/{positive_count}, 조정 후 {after_found}/{positive_count}. 상위 결과에서 이미 평가한 문서의 비율: {before.get('judged_coverage_at_k', 0):.3f} → {after.get('judged_coverage_at_k', 0):.3f}.", f"보조 순위 지표 nDCG@{after.get('k', 10)}: {before_ndcg:.3f} → {after_ndcg:.3f} (평가한 문서만으로 계산)."]
    if regressions:
        details.append("학습 자료에서 nDCG가 낮아진 질의: " + ", ".join(regressions[:20]) + (" …" if len(regressions) > 20 else "."))
    else:
        details.append("학습 자료에서 nDCG 하락이 확인된 개별 질의는 없습니다.")
    validation = result.get("validation")
    caveats = ["이 결과는 제공된 query와 judgment 범위의 비교이며 검색 결과가 정답이거나 실제 RAG 답변이 좋아진다는 보장은 없습니다.", "미평가 문서는 nDCG에서 제외되며 무관으로 간주되지 않습니다."]
    if validation:
        val_before, val_after = validation.get("baseline", {}), validation.get("tuned", {})
        details.append(f"검증 자료: {val_after.get('query_count', 0)}개 질의에서 nDCG@{val_after.get('k', 10)}가 {val_before.get('ndcg_at_k', 0):.3f}에서 {val_after.get('ndcg_at_k', 0):.3f}로 변했습니다.")
        val_regressions = [str(row.get("query_id")) for row in val_after.get("queries", []) if row.get("ndcg_at_k", 0) < next((old.get("ndcg_at_k", 0) for old in val_before.get("queries", []) if old.get("query_id") == row.get("query_id")), 0)]
        if val_regressions:
            details.append("검증 자료에서 nDCG가 낮아진 질의: " + ", ".join(val_regressions[:20]) + (" …" if len(val_regressions) > 20 else "."))
        caveats.append("검증 점수는 제한된 후보 중 설정을 선택하는 데만 사용했으며, 이 validation query set에 한정됩니다.")
    else:
        caveats.append("검증 judgment가 없어 일반화 성능을 확인하지 않았습니다.")
    scope = f"학습 query {after.get('query_count', 0)}개, graded judgment {after.get('judged_count', 0)}개, 결과 내 미평가 문서 {result.get('unjudged_retrieved_count', 0)}개."
    return {"headline": headline, "details": details, "scope": scope, "caveats": caveats}


def list_runs(concept_id: str = "", limit: Any = 50) -> dict[str, Any]:
    limit = _bounded_int(limit, 1, 100, "limit")
    with _connect_db() as db:
        if concept_id:
            rows = db.execute("SELECT id,concept_id,created_at,kind,body FROM runs WHERE concept_id=? ORDER BY created_at DESC LIMIT ?", (concept_id, limit)).fetchall()
        else:
            rows = db.execute("SELECT id,concept_id,created_at,kind,body FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    runs = []
    for row in rows:
        body = json.loads(row["body"])
        input_snapshot = body.get("input_snapshot")
        if isinstance(input_snapshot, dict) and isinstance(input_snapshot.get("judgments"), list):
            input_snapshot = dict(input_snapshot)
            input_snapshot["judgments_truncated_count"] = max(0, len(input_snapshot["judgments"]) - 500)
            input_snapshot["judgments"] = input_snapshot["judgments"][:500]
        budget = [1000]
        def trim_output(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: trim_output(item) for key, item in value.items()}
            if isinstance(value, list):
                keep = min(len(value), budget[0])
                budget[0] -= keep
                return [trim_output(item) for item in value[:keep]]
            return value
        output_snapshot = trim_output(body.get("output_snapshot"))
        runs.append({"run_id": row["id"], "concept_id": row["concept_id"], "created_at": row["created_at"], "kind": row["kind"], "query": body.get("query"), "settings": body.get("settings"), "effective_filters": body.get("effective_filters", body.get("filters", [])), "metrics": body.get("tuned", body.get("candidate")), "snapshot": {key: body[key] for key in ("query_id", "baseline_ids", "candidate_ids", "train", "validation", "judged_count", "explicit_unjudged_count", "unjudged_retrieved_count", "pinned_count", "candidate_trace", "selection", "validation_diagnostics", "tuning_budget") if key in body}, "input_snapshot": input_snapshot, "output_snapshot": output_snapshot, "output_snapshot_truncated": budget[0] == 0, "reproducibility": body.get("reproducibility", {})})
    return {"runs": runs}


_RUN_EXPORT_PRIVATE_KEYS = {
    "authorization", "auth", "headers", "credentials", "password", "passwd", "token",
    "api_key", "apikey", "secret", "provider", "provider_id", "account", "account_id",
    "username", "user_name", "database", "database_path", "db_path", "local_path",
    "file_path", "source", "document_source", "source_document",
}
_RUN_EXPORT_SECRET_PATTERNS = (
    re.compile(r"(?i)(\bauthorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s,;]+"),
    re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\s*[:=]\s*)[^\s,;]+"),
)


def _run_export_safe(value: Any) -> Any:
    """Copy stored JSON while excluding credential, path, and source-body fields."""
    if isinstance(value, dict):
        def is_private_key(key: Any) -> bool:
            name = str(key).lower()
            compact = re.sub(r"[^a-z0-9]", "", name)
            private_fragments = (
                "authorization", "credential", "password", "passwd", "token", "apikey",
                "secret", "provider", "account", "username", "databasepath", "dbpath",
                "localpath", "filepath",
            )
            return name in _RUN_EXPORT_PRIVATE_KEYS or any(fragment in compact for fragment in private_fragments) or compact in {
                "source", "documentsource", "sourcedocument", "sourcebody", "rawsource",
            }
        return {
            key: _run_export_safe(item)
            for key, item in value.items()
            if not is_private_key(key)
        }
    if isinstance(value, list):
        return [_run_export_safe(item) for item in value]
    if isinstance(value, str):
        for pattern in _RUN_EXPORT_SECRET_PATTERNS:
            value = pattern.sub(r"\1[REDACTED]", value)
    return value


def _count_run_rows(value: Any) -> int:
    """Count ranked result rows in a persisted output snapshot."""
    if isinstance(value, list):
        return len(value) + sum(_count_run_rows(item) for item in value)
    if isinstance(value, dict):
        return sum(_count_run_rows(item) for item in value.values())
    return 0


def export_run(concept_id: str, run_id: str) -> dict[str, Any]:
    """Export one exact persisted experiment run without querying Elasticsearch."""
    concept_id, run_id = str(concept_id).strip(), str(run_id).strip()
    if not concept_id or len(concept_id) > 128:
        raise ElasticsearchError("concept_id 값이 올바르지 않습니다.")
    if not run_id or len(run_id) > 128:
        raise ElasticsearchError("run_id 값이 올바르지 않습니다.")
    with _connect_db() as db:
        concept = db.execute("SELECT id FROM concepts WHERE id=?", (concept_id,)).fetchone()
        if not concept:
            raise ElasticsearchError("저장된 concept id를 찾을 수 없습니다.", 404)
        row = db.execute(
            "SELECT id,concept_id,created_at,kind,body FROM runs WHERE id=? AND concept_id=?",
            (run_id, concept_id),
        ).fetchone()
    if not row:
        raise ElasticsearchError("선택한 개념의 실험 run을 찾을 수 없습니다.", 404)

    stored = json.loads(row["body"])
    allowed_fields = {
        "query", "query_id", "effective_filters", "settings", "filters", "baseline",
        "candidate", "tuned", "train", "validation", "judged_count",
        "explicit_unjudged_count", "unjudged_retrieved_count", "pinned_count",
        "candidate_trace", "selection", "validation_diagnostics", "tuning_budget",
        "input_snapshot", "output_snapshot", "baseline_ids", "candidate_ids",
        "reproducibility",
    }
    exported = _run_export_safe({key: value for key, value in stored.items() if key in allowed_fields})
    input_snapshot = exported.get("input_snapshot", {})
    judgments = input_snapshot.get("judgments", []) if isinstance(input_snapshot, dict) else []
    output_snapshot = exported.get("output_snapshot", {})
    warnings = [
        "This artifact contains the selected run's stored evidence only; it does not rerun queries or verify the current Elasticsearch index.",
        "Ranked result IDs and source hashes are preserved; fetched source document bodies and credentials are excluded.",
        "User-authored query and judgment reason text is retained; only common credential patterns are redacted, so review this artifact for sensitive free text before sharing.",
    ]
    if row["kind"] == "preview":
        warnings.append("Search scores are ranking scores, not probabilities; lexical evidence and rank changes are not relevance judgments.")
    if row["kind"] == "tune":
        warnings.append("nDCG uses judged documents only; unjudged documents are not treated as irrelevant, and pins do not alter organic rankings.")
    if row["kind"] == "tune" and not exported.get("validation"):
        warnings.append("Validation evidence is unavailable in this run; the recorded result is training-only.")
    artifact = {
        "format": "es-rag-experiment-run",
        "version": 1,
        "exported_at": _now(),
        "run": {
            "run_id": row["id"],
            "concept_id": row["concept_id"],
            "created_at": row["created_at"],
            "kind": row["kind"],
            **exported,
        },
        "completeness": {
            "truncated": False,
            "judgment_count": len(judgments) if isinstance(judgments, list) else 0,
            "output_entry_count": _count_run_rows(output_snapshot),
        },
        "limitations": warnings,
    }
    # Hash the privacy-filtered content envelope, not the export timestamp or
    # digest field. This lets repeated exports identify identical saved evidence.
    fingerprint_basis = {
        key: value for key, value in artifact.items()
        if key not in {"exported_at", "content_fingerprint"}
    }
    artifact["content_fingerprint"] = _json_hash(fingerprint_basis)
    return artifact
