"""Private, per-account lexical knowledge documents stored in the state DB."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
import base64
import csv
import io
from importlib.metadata import PackageNotFoundError, version as package_version
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from . import concepts
from . import storage
from . import embeddings, token_preview, chunking
from .es_client import Connection, ElasticsearchError, private_alias, private_read_scope, private_sync_scope, request, validate_index

MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_ACCOUNT_BYTES = 20 * 1024 * 1024
MAX_DOCUMENTS = 100
CHUNK_CODEPOINTS = 1800
CHUNK_OVERLAP = 200
MAX_TITLE_CODEPOINTS = 200
MAX_SOURCE_CODEPOINTS = 200
MAX_SEARCH_QUERY_CODEPOINTS = 1000
MAX_IMPORT_ROWS = 100
MAX_ARCHIVE_DOCUMENTS = MAX_DOCUMENTS
ARCHIVE_FORMAT = "es-rag-knowledge"
ARCHIVE_VERSION = 1
DEFAULT_SEARCH_LIMIT = 10
CONCEPT_PREVIEW_LIMIT = 20
CONCEPT_RECIPE_VERSION = "knowledge-concept-fts-v1"
try:
    _FASTEMBED_VERSION = package_version("fastembed")
except PackageNotFoundError:
    _FASTEMBED_VERSION = "not-installed"
LEGACY_E5_VECTOR_RECIPE = {
    "model": embeddings.MODEL_NAME,
    "fastembed_version": _FASTEMBED_VERSION,
    "dimensions": embeddings.MODEL_DIMENSIONS,
    "similarity": "cosine",
    "passage_prefix": "passage: ",
    "query_prefix": "query: ",
    "tokenizer_revision": token_preview.REVISION,
    "max_tokens": token_preview.MAX_TOKENS,
    "chunking": "tokenizer-offset contiguous non-overlap slices of original BM25 chunk; UTF-8-independent Python codepoint offsets",
    "chunking_version": "e5-token-slices-v1",
}
# Retain the historical public constant for E5 compatibility fixtures. New
# generations use _private_profile_recipe() for full tokenizer provenance.
PRIVATE_VECTOR_RECIPE = LEGACY_E5_VECTOR_RECIPE
_WORD_RE = re.compile(r"[^\W]+", flags=re.UNICODE)
_SYNC_LOCKS: dict[str, threading.Lock] = {}
_SYNC_LOCKS_GUARD = threading.Lock()


def _private_profile_recipe(profile_id: str) -> dict[str, Any]:
    """Bind a private vector generation to its tokenizer and passage slicing recipe."""
    recipe = embeddings.profile_recipe(profile_id)
    try:
        tokenizer_runtime = package_version("tokenizers")
    except PackageNotFoundError:
        tokenizer_runtime = None
    if profile_id == embeddings.DEFAULT_PROFILE_ID:
        tokenizer_repository = token_preview.REPOSITORY
        tokenizer_revision = token_preview.REVISION
        tokenizer_sha256 = token_preview.ASSETS["tokenizer.json"]
        chunking_version = "e5-token-slices-v1"
    else:
        tokenizer_repository = recipe["source_repo"]
        tokenizer_revision = recipe.get("source_revision")
        tokenizer_sha256 = None
        chunking_version = "profile-token-slices-v1"
    recipe["tokenizer"] = {
        "repository": tokenizer_repository,
        "revision": tokenizer_revision,
        "tokenizer_json_sha256": tokenizer_sha256,
        "runtime_version": tokenizer_runtime,
    }
    recipe["chunking_recipe"] = {
        "version": chunking_version,
        "strategy": "tokenizer-offset-contiguous-nonoverlap",
        "context_tokens": recipe["context_tokens"],
        "overlap_tokens": 0,
        "offset_unit": "python-codepoints-half-open",
    }
    canonical = json.dumps(
        {key: value for key, value in recipe.items() if key != "recipe_fingerprint"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    recipe["recipe_fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return recipe


class KnowledgeError(Exception):
    """Safe API error with an HTTP status; never includes submitted content."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, field: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise KnowledgeError(f"{field} must be a string")
    value = value.strip()
    if required and not value:
        raise KnowledgeError(f"{field} is required")
    if len(value) > maximum:
        raise KnowledgeError(f"{field} must be at most {maximum} characters")
    return value


def _content_bytes(content: Any) -> tuple[str, int]:
    if not isinstance(content, str) or not content.strip():
        raise KnowledgeError("content must be a non-empty string")
    size = len(content.encode("utf-8"))
    if size > MAX_DOCUMENT_BYTES:
        raise KnowledgeError("document exceeds the 1 MiB limit")
    return content, size


def _split(content: str, policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    selected = policy or chunking.normalize_policy({"strategy": "character", "size": CHUNK_CODEPOINTS, "overlap": CHUNK_OVERLAP})
    return [{"ordinal": item["ordinal"], "start": item["start_offset"], "end": item["end_offset"],
             "content": item["content"], "token_count": item.get("token_count")}
            for item in chunking.split_text(content, selected)]

def _saved_policy(db: sqlite3.Connection) -> tuple[dict[str, Any], str]:
    row = db.execute("SELECT policy_json,policy_sha256 FROM knowledge_chunk_policy WHERE id=1").fetchone()
    if not row:
        policy = chunking.normalize_policy({"strategy": "character", "size": CHUNK_CODEPOINTS, "overlap": CHUNK_OVERLAP})
        return policy, chunking.policy_fingerprint(policy)
    policy = chunking.normalize_policy(json.loads(row["policy_json"]))
    return policy, str(row["policy_sha256"])

def _chunk_identity(document_id: str, revision: int, policy_hash: str, chunk: dict[str, Any]) -> str:
    identity = f"{document_id}:{revision}:{policy_hash}:{chunk['ordinal']}:{chunk['start']}:{chunk['end']}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()

def _store_chunks(db: sqlite3.Connection, document_id: str, title: str, source: str, content: str, revision: int, policy: dict[str, Any], policy_hash: str) -> list[dict[str, Any]]:
    result = []
    for chunk in _split(content, policy):
        chunk_id = _chunk_identity(document_id, revision, policy_hash, chunk)
        db.execute("INSERT INTO knowledge_chunks(id,document_id,ordinal,start_offset,end_offset,content,source_revision,policy_sha256,token_count) VALUES(?,?,?,?,?,?,?,?,?)", (chunk_id, document_id, chunk["ordinal"], chunk["start"], chunk["end"], chunk["content"], revision, policy_hash, chunk.get("token_count")))
        db.execute("INSERT INTO knowledge_fts(content,title,source_label,document_id,chunk_id) VALUES(?,?,?,?,?)", (chunk["content"], title, source, document_id, chunk_id))
        result.append({**chunk, "id": chunk_id, "source_revision": revision, "policy_sha256": policy_hash})
    return result


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    title = _text(payload.get("title"), "title", MAX_TITLE_CODEPOINTS)
    source = _text(payload.get("source_label", ""), "source_label", MAX_SOURCE_CODEPOINTS, required=False)
    content, size = _content_bytes(payload.get("content"))
    return {"title": title, "source_label": source, "content_bytes": size, "chunks": _split(content)}


def preview_chunks(payload: dict[str, Any]) -> dict[str, Any]:
    content, size = _content_bytes(payload.get("content"))
    if set(payload) - {"content", "strategy", "size", "overlap"}:
        raise KnowledgeError("chunk preview accepts content and chunk policy fields only")
    try:
        policy = chunking.normalize_policy({"strategy": payload.get("strategy", "character"), "size": payload.get("size", 1800), "overlap": payload.get("overlap", 200)})
        info = chunking.tokenizer_info()
        tokenizer = token_preview._load_tokenizer() if policy.get("strategy") == "token" and info.get("available") else None
        chunks = chunking.split_text(content, policy, tokenizer=tokenizer)
    except Exception as exc:
        message = str(exc)
        raise KnowledgeError(message if len(message) < 300 else "Chunk policy or tokenizer is unavailable") from None
    return {"content_bytes": size, "policy": policy, "policy_sha256": chunking.policy_fingerprint(policy), "tokenizer": info, "chunks": chunks}


def set_chunk_policy(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        policy = chunking.normalize_policy(payload.get("policy"))
    except Exception as exc:
        raise KnowledgeError(str(exc)) from None
    policy_json = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    fingerprint = chunking.policy_fingerprint(policy)
    with concepts._connect_db() as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE knowledge_chunk_policy SET policy_json=?,policy_sha256=?,updated_at=? WHERE id=1", (policy_json, fingerprint, _now()))
        if db.execute("SELECT 1 FROM knowledge_chunks WHERE policy_sha256<>? LIMIT 1", (fingerprint,)).fetchone():
            _mark_es_stale(db)
    return {"policy": policy, "policy_sha256": fingerprint}


def get_chunk_policy() -> dict[str, Any]:
    with concepts._connect_db() as db:
        _schema(db)
        policy, fingerprint = _saved_policy(db)
    return {"policy": policy, "policy_sha256": fingerprint}


def _schema(db: sqlite3.Connection) -> None:
    storage.migrate(db, "state")
    # Schema bootstrap must not leave an implicit transaction open: save/delete
    # start their own BEGIN IMMEDIATE transaction after this helper returns.
    db.commit()


def _mark_es_stale(db: sqlite3.Connection) -> None:
    db.execute("UPDATE knowledge_es_state SET state='stale',error='' WHERE id=1")


def _metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {"document_id": row["id"], "title": row["title"], "source_label": row["source_label"],
            "content_bytes": row["content_bytes"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "source_name": row["source_name"], "source_record": row["source_record"],
            "source_sha256": row["source_sha256"], "content_sha256": row["content_sha256"], "revision": row["revision"]}


def _chunks(db: sqlite3.Connection, document_id: str) -> list[dict[str, Any]]:
    return [{"id": row["id"], "ordinal": row["ordinal"], "start": row["start_offset"],
             "end": row["end_offset"], "content": row["content"], "source_revision": row["source_revision"],
             "policy_sha256": row["policy_sha256"], "token_count": row["token_count"]}
            for row in db.execute("SELECT id,ordinal,start_offset,end_offset,content,source_revision,policy_sha256,token_count FROM knowledge_chunks WHERE document_id=? ORDER BY ordinal", (document_id,))]


def list_documents() -> dict[str, Any]:
    with concepts._connect_db() as db:
        _schema(db)
        rows = db.execute("SELECT id,title,source_label,content_bytes,created_at,updated_at,source_name,source_record,source_sha256,content_sha256,revision FROM knowledge_documents ORDER BY updated_at DESC,id").fetchall()
        return {"documents": [_metadata(row) for row in rows]}


def get_document(payload: dict[str, Any]) -> dict[str, Any]:
    document_id = _text(payload.get("document_id"), "document_id", 64)
    with concepts._connect_db() as db:
        _schema(db)
        row = db.execute("SELECT id,title,source_label,content,content_bytes,created_at,updated_at,source_name,source_record,source_sha256,content_sha256,revision FROM knowledge_documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            raise KnowledgeError("Knowledge document not found", 404)
        return {**_metadata(row), "content": row["content"], "chunks": _chunks(db, document_id)}


def save_document(payload: dict[str, Any]) -> dict[str, Any]:
    title = _text(payload.get("title"), "title", MAX_TITLE_CODEPOINTS)
    source = _text(payload.get("source_label", ""), "source_label", MAX_SOURCE_CODEPOINTS, required=False)
    content, size = _content_bytes(payload.get("content"))
    document_id = payload.get("document_id")
    if document_id is not None:
        document_id = _text(document_id, "document_id", 64)
    now = _now()
    with concepts._connect_db() as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        policy, policy_hash = _saved_policy(db)
        current = None
        if document_id:
            current = db.execute("SELECT id,created_at,title,source_label,content,content_sha256,revision FROM knowledge_documents WHERE id=?", (document_id,)).fetchone()
            if not current:
                raise KnowledgeError("Knowledge document not found", 404)
        usage = db.execute("SELECT COALESCE(SUM(content_bytes),0) AS bytes,COUNT(*) AS documents FROM knowledge_documents").fetchone()
        remaining = usage["bytes"] - (db.execute("SELECT content_bytes FROM knowledge_documents WHERE id=?", (document_id,)).fetchone()[0] if current else 0)
        if remaining + size > MAX_ACCOUNT_BYTES:
            raise KnowledgeError("account knowledge storage exceeds the 20 MiB limit", 413)
        if not current and usage["documents"] >= MAX_DOCUMENTS:
            raise KnowledgeError("account knowledge storage is limited to 100 documents", 413)
        if current:
            changed = (current["title"], current["source_label"], current["content"]) != (title, source, content)
            revision = int(current["revision"]) + (1 if changed else 0)
            db.execute("UPDATE knowledge_documents SET title=?,source_label=?,content=?,content_bytes=?,content_sha256=?,revision=?,updated_at=? WHERE id=?", (title, source, content, size, hashlib.sha256(content.encode("utf-8")).hexdigest(), revision, now, document_id))
            db.execute("DELETE FROM knowledge_fts WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,))
        else:
            document_id = str(uuid.uuid4())
            revision = 1
            db.execute("INSERT INTO knowledge_documents(id,title,source_label,content,content_bytes,created_at,updated_at,content_sha256,revision) VALUES(?,?,?,?,?,?,?,?,1)", (document_id, title, source, content, size, now, now, hashlib.sha256(content.encode("utf-8")).hexdigest()))
        chunk_rows = _store_chunks(db, document_id, title, source, content, revision, policy, policy_hash)
        _mark_es_stale(db)
        row = db.execute("SELECT id,title,source_label,content_bytes,created_at,updated_at,source_name,source_record,source_sha256,content_sha256,revision FROM knowledge_documents WHERE id=?", (document_id,)).fetchone()
        return {"document": _metadata(row), "chunks": chunk_rows}


def delete_document(payload: dict[str, Any]) -> dict[str, Any]:
    document_id = _text(payload.get("document_id"), "document_id", 64)
    with concepts._connect_db() as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM knowledge_documents WHERE id=?", (document_id,)).fetchone():
            raise KnowledgeError("Knowledge document not found", 404)
        db.execute("DELETE FROM knowledge_fts WHERE document_id=?", (document_id,))
        db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,))
        db.execute("DELETE FROM knowledge_documents WHERE id=?", (document_id,))
        _mark_es_stale(db)
        return {"deleted": True, "document_id": document_id}


def _usage(db: sqlite3.Connection) -> dict[str, int]:
    row = db.execute("SELECT COUNT(*) AS documents,COALESCE(SUM(content_bytes),0) AS bytes FROM knowledge_documents").fetchone()
    return {"documents": int(row["documents"]), "bytes": int(row["bytes"])}


def _import_error(code: str, message: str, row_number: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "message": message}
    if row_number is not None:
        result["row_number"] = row_number
    return result


def _import_input(payload: dict[str, Any]) -> tuple[str, bytes, dict[str, str], str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    filename = payload.get("filename")
    if not isinstance(filename, str) or not filename.strip() or len(filename) > 255 or any(ch in filename for ch in ("/", "\\", "\x00")) or filename in {".", ".."}:
        raise KnowledgeError("filename must be a short file name without path separators")
    filename = filename.strip()
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    formats = {"txt": "txt", "md": "md", "csv": "csv", "jsonl": "jsonl"}
    if suffix not in formats:
        raise KnowledgeError("supported import formats are .txt, .md, .csv, and .jsonl")
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or len(encoded) > ((MAX_DOCUMENT_BYTES + 2) // 3) * 4 + 8:
        raise KnowledgeError("import file exceeds the 1 MiB limit or is invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        raise KnowledgeError("content_base64 must contain valid Base64 data") from None
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise KnowledgeError("import file exceeds the 1 MiB limit")
    file_hash = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise KnowledgeError("import file must use valid UTF-8 encoding") from None
    fields = payload.get("fields", {})
    if not isinstance(fields, dict) or set(fields) - {"title", "content", "source"}:
        raise KnowledgeError("fields must map title, content, and optional source")
    needs_mapping = suffix in {"csv", "jsonl"} and (not isinstance(fields.get("title"), str) or not fields["title"] or not isinstance(fields.get("content"), str) or not fields["content"])
    if suffix in {"csv", "jsonl"} and ("source" in fields and not isinstance(fields["source"], str)):
        raise KnowledgeError("source field mapping must be a string")
    stem = filename.rsplit(".", 1)[0]
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    available: list[str] = []
    if suffix in {"txt", "md"}:
        available = ["title", "content", "source"]
        records = [{"row_number": 1, "title": stem, "content": text, "source_label": filename}]
    elif suffix == "csv":
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            available = list(reader.fieldnames or [])
            if not available or len(available) > 200 or len(set(available)) != len(available) or any(not name for name in available):
                raise csv.Error("invalid header")
            for row_number, row in enumerate(reader, 2):
                if row_number > MAX_IMPORT_ROWS + 1:
                    raise KnowledgeError("import files are limited to 100 data rows")
                if None in row or any(value is None for value in row.values()):
                    errors.append(_import_error("INVALID_CSV_ROW", "Row has a different number of fields.", row_number))
                    continue
                if not needs_mapping:
                    records.append({"row_number": row_number, "title": row.get(fields["title"], ""), "content": row.get(fields["content"], ""), "source_label": row.get(fields.get("source", ""), "") if fields.get("source") else ""})
        except csv.Error:
            raise KnowledgeError("CSV header or quoting is malformed") from None
    else:
        available = []
        for row_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            if row_number > MAX_IMPORT_ROWS:
                raise KnowledgeError("import files are limited to 100 data rows")
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                errors.append(_import_error("INVALID_JSONL_ROW", "Row is not valid JSON.", row_number))
                continue
            if not isinstance(row, dict):
                errors.append(_import_error("INVALID_JSONL_ROW", "Each JSONL row must be an object.", row_number))
                continue
            available = sorted(set(available) | {str(key) for key in row})
            if len(available) > 200:
                raise KnowledgeError("JSONL files are limited to 200 distinct field names")
            if not needs_mapping:
                records.append({"row_number": row_number, "title": row.get(fields["title"], ""), "content": row.get(fields["content"], ""), "source_label": row.get(fields.get("source", ""), "") if fields.get("source") else ""})
    normalized: list[dict[str, Any]] = []
    for record in records:
        row_number = int(record["row_number"])
        title, content, source = record["title"], record["content"], record["source_label"]
        if not isinstance(title, str) or not isinstance(content, str) or not isinstance(source, str):
            errors.append(_import_error("INVALID_FIELD", "Mapped title, content, and source values must be text.", row_number))
            continue
        title, source = title.strip(), (source.strip() or filename)
        if not title or not content.strip():
            errors.append(_import_error("EMPTY_RECORD", "Mapped title and content must not be empty.", row_number))
            continue
        if len(title) > MAX_TITLE_CODEPOINTS or len(source) > MAX_SOURCE_CODEPOINTS:
            errors.append(_import_error("FIELD_TOO_LONG", "Mapped title or source exceeds its character limit.", row_number))
            continue
        size = len(content.encode("utf-8"))
        if size > MAX_DOCUMENT_BYTES:
            errors.append(_import_error("DOCUMENT_TOO_LARGE", "Document exceeds the 1 MiB limit.", row_number))
            continue
        normalized.append({"row_number": row_number, "title": title, "content": content, "source_label": source,
                           "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "content_bytes": size})
    return filename, raw, fields, file_hash, normalized, errors, available


def _annotate_duplicates(db: sqlite3.Connection, records: list[dict[str, Any]], filename: str) -> list[dict[str, Any]]:
    result = []
    seen: dict[str, int] = {}
    for record in records:
        item = dict(record)
        digest = item["content_sha256"]
        row = db.execute("SELECT id,revision FROM knowledge_documents WHERE content_sha256=? OR (source_name=? AND source_record=?) ORDER BY CASE WHEN source_name=? AND source_record=? THEN 0 ELSE 1 END,id LIMIT 1", (digest, filename, str(item["row_number"]), filename, str(item["row_number"]))).fetchone()
        if row:
            item["duplicate"] = {"document_id": row["id"], "revision": int(row["revision"])}
        elif digest in seen:
            item["duplicate"] = {"document_id": None, "revision": None, "row_number": seen[digest]}
        else:
            seen[digest] = int(item["row_number"])
        result.append(item)
    return result


def import_preview(payload: dict[str, Any]) -> dict[str, Any]:
    filename, _raw, fields, file_hash, records, errors, available = _import_input(payload)
    with concepts._connect_db() as db:
        _schema(db)
        records = _annotate_duplicates(db, records, filename)
        usage = _usage(db)
    needs_mapping = filename.rsplit(".", 1)[-1].lower() in {"csv", "jsonl"} and (not fields.get("title") or not fields.get("content"))
    return {"file_sha256": file_hash, "format": filename.rsplit(".", 1)[-1].lower(), "fields_available": available,
            "valid_records": records, "errors": errors, "usage": usage,
            "limits": {"documents": MAX_DOCUMENTS, "bytes": MAX_ACCOUNT_BYTES, "account_bytes": MAX_ACCOUNT_BYTES, "document_bytes": MAX_DOCUMENT_BYTES, "rows": MAX_IMPORT_ROWS},
            "needs_field_mapping": bool(needs_mapping)}


def _private_state_summary(db: sqlite3.Connection) -> dict[str, Any]:
    state = db.execute("SELECT state,generation,indexed_chunks,vector_state,vector_chunks,vector_profile_id,vector_profile_recipe FROM knowledge_es_state WHERE id=1").fetchone()
    return dict(state) if state else {"state": "stale", "generation": 0, "indexed_chunks": 0, "vector_state": "not_indexed", "vector_chunks": 0, "vector_profile_id": embeddings.DEFAULT_PROFILE_ID, "vector_profile_recipe": ""}


def import_commit(payload: dict[str, Any]) -> dict[str, Any]:
    filename, _raw, fields, file_hash, records, errors, _available = _import_input(payload)
    if filename.rsplit(".", 1)[-1].lower() in {"csv", "jsonl"} and (not fields.get("title") or not fields.get("content")):
        raise KnowledgeError("CSV and JSONL imports require title and content field mappings")
    actions = payload.get("duplicate_actions", [])
    if not isinstance(actions, list):
        raise KnowledgeError("duplicate_actions must be an array")
    action_by_row: dict[int, str] = {}
    for item in actions:
        if not isinstance(item, dict) or isinstance(item.get("row_number"), bool) or not isinstance(item.get("row_number"), int) or item.get("action") not in {"skip", "replace"} or item["row_number"] in action_by_row:
            raise KnowledgeError("duplicate_actions contains an invalid or repeated choice")
        action_by_row[item["row_number"]] = item["action"]
    outcomes: list[dict[str, Any]] = []
    with concepts._connect_db() as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        policy, policy_hash = _saved_policy(db)
        duplicate_rows: set[int] = set()
        preview_seen: set[str] = set()
        for record in records:
            row_number = int(record["row_number"])
            existing = db.execute("SELECT 1 FROM knowledge_documents WHERE content_sha256=? OR (source_name=? AND source_record=?) LIMIT 1", (record["content_sha256"], filename, str(row_number))).fetchone()
            if existing or record["content_sha256"] in preview_seen:
                duplicate_rows.add(row_number)
            preview_seen.add(record["content_sha256"])
        valid_rows = {int(record["row_number"]) for record in records}
        if set(action_by_row) - valid_rows or set(action_by_row) != duplicate_rows:
            raise KnowledgeError("duplicate_actions must provide exactly one explicit choice for each duplicate row")
        seen_hashes: dict[str, str] = {}
        any_change = False
        for record in records:
            row_number = record["row_number"]
            duplicate = db.execute("SELECT id,title,source_label,content,content_bytes,created_at,revision,source_name,source_record,source_sha256 FROM knowledge_documents WHERE content_sha256=? OR (source_name=? AND source_record=?) ORDER BY CASE WHEN source_name=? AND source_record=? THEN 0 ELSE 1 END,id LIMIT 1", (record["content_sha256"], filename, str(row_number), filename, str(row_number))).fetchone()
            duplicate_id = duplicate["id"] if duplicate else seen_hashes.get(record["content_sha256"])
            if duplicate_id:
                action = action_by_row.get(row_number)
                if action not in {"skip", "replace"}:
                    raise KnowledgeError("Every duplicate row requires an explicit skip or replace choice")
                if action == "skip":
                    outcomes.append({"row_number": row_number, "outcome": "skipped", "document_id": duplicate_id})
                    continue
                if duplicate is None:
                    duplicate = db.execute("SELECT id,title,source_label,content,content_bytes,created_at,revision,source_name,source_record,source_sha256 FROM knowledge_documents WHERE id=?", (duplicate_id,)).fetchone()
            else:
                action = None
            now = _now()
            if duplicate:
                current_tuple = (duplicate["title"], duplicate["source_label"], duplicate["content"], duplicate["source_name"], duplicate["source_record"], duplicate["source_sha256"])
                next_tuple = (record["title"], record["source_label"], record["content"], filename, str(row_number), file_hash)
                if current_tuple == next_tuple:
                    outcomes.append({"row_number": row_number, "outcome": "unchanged", "document_id": duplicate_id, "revision": int(duplicate["revision"])})
                    seen_hashes[record["content_sha256"]] = duplicate_id
                    continue
                usage = _usage(db)
                if usage["bytes"] - int(duplicate["content_bytes"]) + record["content_bytes"] > MAX_ACCOUNT_BYTES:
                    errors.append(_import_error("ACCOUNT_QUOTA_EXCEEDED", "Account storage would exceed the 20 MiB limit.", row_number))
                    outcomes.append({"row_number": row_number, "outcome": "failed", "document_id": duplicate_id, "code": "ACCOUNT_QUOTA_EXCEEDED"})
                    continue
                changed = current_tuple != next_tuple
                revision = int(duplicate["revision"]) + (1 if changed else 0)
                db.execute("UPDATE knowledge_documents SET title=?,source_label=?,content=?,content_bytes=?,updated_at=?,source_name=?,source_record=?,source_sha256=?,content_sha256=?,revision=? WHERE id=?", (record["title"], record["source_label"], record["content"], record["content_bytes"], now, filename, str(row_number), file_hash, record["content_sha256"], revision, duplicate_id))
                db.execute("DELETE FROM knowledge_fts WHERE document_id=?", (duplicate_id,))
                db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (duplicate_id,))
                outcome = "replaced"
            else:
                usage = _usage(db)
                if usage["documents"] >= MAX_DOCUMENTS or usage["bytes"] + record["content_bytes"] > MAX_ACCOUNT_BYTES:
                    code = "DOCUMENT_LIMIT" if usage["documents"] >= MAX_DOCUMENTS else "ACCOUNT_QUOTA_EXCEEDED"
                    errors.append(_import_error(code, "Account knowledge storage limit would be exceeded.", row_number))
                    outcomes.append({"row_number": row_number, "outcome": "failed", "code": code})
                    continue
                duplicate_id = str(uuid.uuid4())
                revision = 1
                db.execute("INSERT INTO knowledge_documents(id,title,source_label,content,content_bytes,created_at,updated_at,source_name,source_record,source_sha256,content_sha256,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)", (duplicate_id, record["title"], record["source_label"], record["content"], record["content_bytes"], now, now, filename, str(row_number), file_hash, record["content_sha256"]))
                outcome = "created"
            _store_chunks(db, duplicate_id, record["title"], record["source_label"], record["content"], revision, policy, policy_hash)
            outcomes.append({"row_number": row_number, "outcome": outcome, "document_id": duplicate_id, "revision": revision})
            seen_hashes[record["content_sha256"]] = duplicate_id
            any_change = True
        if any_change:
            _mark_es_stale(db)
        usage = _usage(db)
        state = _private_state_summary(db)
    partial = bool(errors) or any(item["outcome"] == "failed" for item in outcomes)
    return {"file_sha256": file_hash, "outcomes": outcomes, "errors": errors, "partial": partial, "usage": usage,
            "limits": {"documents": MAX_DOCUMENTS, "bytes": MAX_ACCOUNT_BYTES, "account_bytes": MAX_ACCOUNT_BYTES, "document_bytes": MAX_DOCUMENT_BYTES},
            "private_es_state": state}


def export_archive(_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with concepts._connect_db() as db:
        _schema(db)
        documents = [dict(row) for row in db.execute("SELECT id,title,source_label,content,content_bytes,created_at,updated_at,source_name,source_record,source_sha256,content_sha256,revision FROM knowledge_documents ORDER BY id")]
        judgments = [dict(row) for row in db.execute("SELECT j.concept_id,j.query_id,j.document_id,j.query_fingerprint,j.document_fingerprint,j.source_label,j.rating,j.updated_at FROM knowledge_judgments j JOIN knowledge_documents d ON d.id=j.document_id ORDER BY j.concept_id,j.query_id,j.document_id")]
    return {"format": ARCHIVE_FORMAT, "version": ARCHIVE_VERSION, "created_at": _now(), "documents": documents, "judgments": judgments}


def _archive_value(payload: dict[str, Any]) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    archive = payload.get("archive")
    if not isinstance(archive, dict) or set(archive) != {"format", "version", "created_at", "documents", "judgments"}:
        raise KnowledgeError("archive has an invalid structure")
    if archive.get("format") != ARCHIVE_FORMAT or isinstance(archive.get("version"), bool) or archive.get("version") != ARCHIVE_VERSION or not isinstance(archive.get("created_at"), str):
        raise KnowledgeError("archive format or version is not supported")
    documents, judgments = archive.get("documents"), archive.get("judgments")
    if not isinstance(documents, list) or not isinstance(judgments, list) or len(documents) > MAX_ARCHIVE_DOCUMENTS or len(judgments) > MAX_ARCHIVE_DOCUMENTS * 100:
        raise KnowledgeError("archive exceeds document or judgment limits")
    archive_hash = _hash(archive)
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_bytes = 0
    normalized_docs: list[dict[str, Any]] = []
    for position, raw in enumerate(documents, 1):
        if not isinstance(raw, dict):
            errors.append(_import_error("INVALID_ARCHIVE_DOCUMENT", "Document entry must be an object.", position))
            continue
        try:
            if set(raw) != {"id", "title", "source_label", "content", "content_bytes", "created_at", "updated_at", "source_name", "source_record", "source_sha256", "content_sha256", "revision"}:
                raise ValueError
            document_id = _text(raw.get("id"), "document id", 64)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", document_id) or document_id in seen_ids:
                raise ValueError
            title = _text(raw.get("title"), "title", MAX_TITLE_CODEPOINTS)
            source = _text(raw.get("source_label", ""), "source_label", MAX_SOURCE_CODEPOINTS, required=False)
            content, size = _content_bytes(raw.get("content"))
            content_bytes = raw.get("content_bytes")
            if isinstance(content_bytes, bool) or not isinstance(content_bytes, int) or content_bytes != size or raw.get("content_sha256") != hashlib.sha256(content.encode("utf-8")).hexdigest():
                raise ValueError
            source_name = raw.get("source_name", "")
            source_record = raw.get("source_record", "")
            source_sha = raw.get("source_sha256", "")
            if not isinstance(source_name, str) or len(source_name) > 255 or any(ch in source_name for ch in ("/", "\\", "\x00")) or not isinstance(source_record, str) or (source_record and not re.fullmatch(r"\d{1,8}", source_record)) or not isinstance(source_sha, str) or (source_sha and not re.fullmatch(r"[0-9a-f]{64}", source_sha)):
                raise ValueError
            revision = raw.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError
            created_at, updated_at = raw.get("created_at"), raw.get("updated_at")
            if not isinstance(created_at, str) or not isinstance(updated_at, str) or len(created_at) > 64 or len(updated_at) > 64:
                raise ValueError
            normalized_docs.append({"id": document_id, "title": title, "source_label": source, "content": content, "content_bytes": size,
                                    "created_at": created_at, "updated_at": updated_at, "source_name": source_name,
                                    "source_record": source_record, "source_sha256": source_sha,
                                    "content_sha256": raw["content_sha256"], "revision": revision})
            total_bytes += size
            seen_ids.add(document_id)
        except (KnowledgeError, KeyError, ValueError, TypeError):
            errors.append(_import_error("INVALID_ARCHIVE_DOCUMENT", "Document entry failed validation.", position))
    if total_bytes > MAX_ACCOUNT_BYTES:
        errors.append(_import_error("ARCHIVE_QUOTA_EXCEEDED", "Archive content exceeds the 20 MiB account limit."))
    if len(seen_ids) != len(documents):
        # Row errors above are sufficient; avoid accepting a partial untrusted archive.
        pass
    normalized_judgments: list[dict[str, Any]] = []
    seen_judgments: set[tuple[str, str, str]] = set()
    for position, raw in enumerate(judgments, 1):
        try:
            if not isinstance(raw, dict) or set(raw) != {"concept_id", "query_id", "document_id", "query_fingerprint", "document_fingerprint", "source_label", "rating", "updated_at"}:
                raise ValueError
            concept_id = _text(raw["concept_id"], "concept_id", 128)
            query_id = _text(raw["query_id"], "query_id", 128)
            document_id = _text(raw["document_id"], "document_id", 64)
            if document_id not in seen_ids or any(not isinstance(raw[key], str) or not re.fullmatch(r"[0-9a-f]{64}", raw[key]) for key in ("query_fingerprint", "document_fingerprint")):
                raise ValueError
            source = _text(raw["source_label"], "source_label", MAX_SOURCE_CODEPOINTS, required=False)
            rating = raw["rating"]
            if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or not 0 <= rating <= 3):
                raise ValueError
            if not isinstance(raw["updated_at"], str) or len(raw["updated_at"]) > 64:
                raise ValueError
            key = (concept_id, query_id, document_id)
            if key in seen_judgments:
                raise ValueError
            seen_judgments.add(key)
            normalized_judgments.append({**raw, "concept_id": concept_id, "query_id": query_id, "document_id": document_id, "source_label": source})
        except (KnowledgeError, KeyError, ValueError, TypeError):
            errors.append(_import_error("INVALID_ARCHIVE_JUDGMENT", "Judgment entry failed validation.", position))
    if errors:
        return {"archive": archive, "archive_sha256": archive_hash, "documents": normalized_docs, "judgments": normalized_judgments, "errors": errors}, archive_hash, errors
    return {"archive": archive, "archive_sha256": archive_hash, "documents": normalized_docs, "judgments": normalized_judgments, "errors": []}, archive_hash, []


def _archive_reference_errors(db: sqlite3.Connection, prepared: dict[str, Any]) -> list[dict[str, Any]]:
    saved_context: dict[tuple[str, str], str] = {}
    for row in db.execute("SELECT body FROM concepts"):
        try:
            concept = concepts.validate_concept(json.loads(row[0]))
            for query in concept["queries"]:
                saved_context[(concept["id"], query["id"])] = concepts._query_judgment_fingerprint(query)
        except Exception:
            continue
    documents = {doc["id"]: doc for doc in prepared["documents"]}
    errors: list[dict[str, Any]] = []
    for position, judgment in enumerate(prepared["judgments"], 1):
        expected_query = saved_context.get((judgment["concept_id"], judgment["query_id"]))
        document = documents.get(judgment["document_id"])
        if expected_query is None:
            errors.append(_import_error("MISSING_JUDGMENT_REFERENCE", "Judgment references an unavailable saved query.", position))
        elif expected_query != judgment["query_fingerprint"]:
            errors.append(_import_error("STALE_JUDGMENT_REFERENCE", "Judgment does not match the current saved query.", position))
        if document is not None and _hash({"title": document["title"], "source_label": document["source_label"], "content": document["content"]}) != judgment["document_fingerprint"]:
            errors.append(_import_error("STALE_JUDGMENT_DOCUMENT", "Judgment does not match the archived document.", position))
    return errors


def restore_preview(payload: dict[str, Any]) -> dict[str, Any]:
    prepared, archive_hash, errors = _archive_value(payload)
    with concepts._connect_db() as db:
        _schema(db)
        errors.extend(_archive_reference_errors(db, prepared))
        current = {str(row[0]): row for row in db.execute("SELECT id,content_bytes,revision FROM knowledge_documents")}
        conflicts = [{"document_id": item["id"], "title": item["title"], "revision": int(current[item["id"]]["revision"]), "archive_revision": item["revision"]}
                     for item in prepared["documents"] if item["id"] in current]
        adds = [item for item in prepared["documents"] if item["id"] not in current]
        current_usage = _usage(db)
        projected = {"documents": current_usage["documents"] + len(adds),
                     "bytes": current_usage["bytes"] - sum(int(current[item["id"]]["content_bytes"]) for item in prepared["documents"] if item["id"] in current) + sum(item["content_bytes"] for item in prepared["documents"])}
    quota_impact = {"usage": projected, "limits": {"documents": MAX_DOCUMENTS, "bytes": MAX_ACCOUNT_BYTES},
                    "exceeds": projected["documents"] > MAX_DOCUMENTS or projected["bytes"] > MAX_ACCOUNT_BYTES}
    return {"archive_sha256": archive_hash, "errors": errors, "conflicts": conflicts, "quota": quota_impact,
            "quota_impact": quota_impact, "usage": projected, "limits": quota_impact["limits"]}


def restore_commit(payload: dict[str, Any]) -> dict[str, Any]:
    prepared, archive_hash, errors = _archive_value(payload)
    if errors:
        raise KnowledgeError("archive failed validation; no data was restored")
    if payload.get("expected_sha256") != archive_hash:
        raise KnowledgeError("archive changed after preview; preview it again")
    actions = payload.get("actions", [])
    if not isinstance(actions, list):
        raise KnowledgeError("actions must be an array")
    action_by_id: dict[str, str] = {}
    for item in actions:
        if not isinstance(item, dict) or not isinstance(item.get("document_id"), str) or item.get("action") not in {"skip", "replace"} or item["document_id"] in action_by_id:
            raise KnowledgeError("actions contains an invalid or repeated choice")
        action_by_id[item["document_id"]] = item["action"]
    docs_out: list[dict[str, Any]] = []
    judgments_out: list[dict[str, Any]] = []
    with concepts._connect_db() as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        policy, policy_hash = _saved_policy(db)
        db_conflicts = {row[0] for row in db.execute("SELECT id FROM knowledge_documents")}
        doc_archive_ids = {doc["id"] for doc in prepared["documents"]}
        if set(action_by_id) - (db_conflicts & doc_archive_ids):
            raise KnowledgeError("actions contains a document that is not a restore conflict")
        saved_context: dict[tuple[str, str], str] = {}
        for row in db.execute("SELECT body FROM concepts"):
            try:
                concept = concepts.validate_concept(json.loads(row[0]))
                for query in concept["queries"]:
                    saved_context[(concept["id"], query["id"])] = concepts._query_judgment_fingerprint(query)
            except Exception:
                continue
        archive_documents = {doc["id"]: doc for doc in prepared["documents"]}
        for judgment in prepared["judgments"]:
            query_fingerprint = saved_context.get((judgment["concept_id"], judgment["query_id"]))
            document = archive_documents[judgment["document_id"]]
            document_fingerprint = _hash({"title": document["title"], "source_label": document["source_label"], "content": document["content"]})
            if query_fingerprint is None:
                raise KnowledgeError("archive contains a judgment for an unavailable saved query")
            if query_fingerprint != judgment["query_fingerprint"] or document_fingerprint != judgment["document_fingerprint"]:
                raise KnowledgeError("archive judgment references changed after preview")
        for doc in prepared["documents"]:
            existing = db.execute("SELECT id,title,source_label,content,content_bytes,created_at,updated_at,source_name,source_record,source_sha256,content_sha256,revision FROM knowledge_documents WHERE id=?", (doc["id"],)).fetchone()
            if existing and action_by_id.get(doc["id"]) not in {"skip", "replace"}:
                raise KnowledgeError("Every restore conflict requires an explicit skip or replace choice")
            if existing and action_by_id[doc["id"]] == "skip":
                docs_out.append({"document_id": doc["id"], "outcome": "skipped"})
                continue
            usage = _usage(db)
            if existing:
                new_count, new_bytes = usage["documents"], usage["bytes"] - int(existing["content_bytes"]) + doc["content_bytes"]
                existing_state = tuple(existing[key] for key in (
                    "title", "source_label", "content", "created_at", "updated_at",
                    "source_name", "source_record", "source_sha256", "content_sha256",
                ))
                archive_state = tuple(doc[key] for key in (
                    "title", "source_label", "content", "created_at", "updated_at",
                    "source_name", "source_record", "source_sha256", "content_sha256",
                ))
                revision = int(existing["revision"]) + (1 if existing_state != archive_state else 0)
                outcome = "replaced"
            else:
                new_count, new_bytes = usage["documents"] + 1, usage["bytes"] + doc["content_bytes"]
                revision = doc["revision"]
                outcome = "created"
            if new_count > MAX_DOCUMENTS or new_bytes > MAX_ACCOUNT_BYTES:
                raise KnowledgeError("restore would exceed this account's storage limits")
            if existing:
                db.execute("UPDATE knowledge_documents SET title=?,source_label=?,content=?,content_bytes=?,created_at=?,updated_at=?,source_name=?,source_record=?,source_sha256=?,content_sha256=?,revision=? WHERE id=?", (doc["title"], doc["source_label"], doc["content"], doc["content_bytes"], doc["created_at"], doc["updated_at"], doc["source_name"], doc["source_record"], doc["source_sha256"], doc["content_sha256"], revision, doc["id"]))
                db.execute("DELETE FROM knowledge_fts WHERE document_id=?", (doc["id"],))
                db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (doc["id"],))
            else:
                db.execute("INSERT INTO knowledge_documents(id,title,source_label,content,content_bytes,created_at,updated_at,source_name,source_record,source_sha256,content_sha256,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (doc["id"], doc["title"], doc["source_label"], doc["content"], doc["content_bytes"], doc["created_at"], doc["updated_at"], doc["source_name"], doc["source_record"], doc["source_sha256"], doc["content_sha256"], revision))
            _store_chunks(db, doc["id"], doc["title"], doc["source_label"], doc["content"], revision, policy, policy_hash)
            docs_out.append({"document_id": doc["id"], "outcome": outcome, "revision": revision})
        applied_docs = {item["document_id"] for item in docs_out if item["outcome"] != "skipped"}
        for document_id in applied_docs:
            db.execute("DELETE FROM knowledge_judgments WHERE document_id=?", (document_id,))
        for judgment in prepared["judgments"]:
            if judgment["document_id"] not in applied_docs:
                judgments_out.append({"document_id": judgment["document_id"], "concept_id": judgment["concept_id"], "query_id": judgment["query_id"], "outcome": "skipped"})
                continue
            expected_query_fp = saved_context[(judgment["concept_id"], judgment["query_id"])]
            if judgment["query_fingerprint"] != expected_query_fp:
                raise KnowledgeError("archive judgment does not match the current saved query")
            db.execute("INSERT INTO knowledge_judgments(concept_id,query_id,document_id,query_fingerprint,document_fingerprint,source_label,rating,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(concept_id,query_id,document_id) DO UPDATE SET query_fingerprint=excluded.query_fingerprint,document_fingerprint=excluded.document_fingerprint,source_label=excluded.source_label,rating=excluded.rating,updated_at=excluded.updated_at", (judgment["concept_id"], judgment["query_id"], judgment["document_id"], judgment["query_fingerprint"], judgment["document_fingerprint"], judgment["source_label"], judgment["rating"], judgment["updated_at"]))
            judgments_out.append({"document_id": judgment["document_id"], "concept_id": judgment["concept_id"], "query_id": judgment["query_id"], "outcome": "restored"})
        changed = any(item["outcome"] != "skipped" for item in docs_out)
        if changed:
            _mark_es_stale(db)
        usage, state = _usage(db), _private_state_summary(db)
    partial = any(item["outcome"] == "skipped" for item in docs_out)
    limits = {"documents": MAX_DOCUMENTS, "bytes": MAX_ACCOUNT_BYTES}
    return {"archive_sha256": archive_hash, "documents": docs_out, "judgments": judgments_out,
            "document_outcomes": docs_out, "judgment_outcomes": judgments_out, "partial": partial,
            "usage": usage, "limits": limits, "private_es_state": state}


def _owner_alias() -> str:
    owner = concepts._OWNER_ID.get()
    if not owner:
        raise KnowledgeError("Authenticated account scope is required", 401)
    return validate_index(private_alias(owner))


def _profile_state(db: sqlite3.Connection) -> tuple[str, dict[str, Any]]:
    row = db.execute("SELECT vector_profile_id,vector_profile_recipe FROM knowledge_es_state WHERE id=1").fetchone()
    profile_id = str(row["vector_profile_id"] or embeddings.DEFAULT_PROFILE_ID) if row else embeddings.DEFAULT_PROFILE_ID
    try:
        embeddings.profile_spec(profile_id)
    except (ValueError, TypeError):
        # Unknown saved profiles fail closed; never reinterpret their vectors as E5.
        return profile_id, {}
    try:
        recipe = json.loads(row["vector_profile_recipe"]) if row and row["vector_profile_recipe"] else _private_profile_recipe(profile_id)
    except Exception:
        recipe = {}
    return profile_id, recipe if isinstance(recipe, dict) else {}


def _save_profile_selection(profile_id: str) -> dict[str, Any]:
    try:
        recipe = _private_profile_recipe(profile_id)
    except (ValueError, TypeError) as exc:
        raise KnowledgeError("Unknown private embedding profile") from None
    encoded = json.dumps(recipe, sort_keys=True, separators=(",", ":"))
    with concepts._connect_db() as db:
        _schema(db)
        row = db.execute("SELECT vector_profile_id,vector_profile_recipe FROM knowledge_es_state WHERE id=1").fetchone()
        previous_id = str(row["vector_profile_id"] or embeddings.DEFAULT_PROFILE_ID)
        previous_recipe = str(row["vector_profile_recipe"] or "")
        if previous_id != profile_id or (previous_recipe and previous_recipe != encoded):
            db.execute("UPDATE knowledge_es_state SET vector_profile_id=?,vector_profile_recipe=?,vector_state='stale' WHERE id=1", (profile_id, encoded))
        elif not previous_recipe:
            db.execute("UPDATE knowledge_es_state SET vector_profile_id=?,vector_profile_recipe=? WHERE id=1", (profile_id, encoded))
    return recipe


def _recipe_profile_id(recipe: Any) -> str | None:
    if not isinstance(recipe, dict):
        return None
    if recipe.get("profile_id") in {profile["profile_id"] for profile in embeddings.list_profiles()}:
        return str(recipe["profile_id"])
    # Historical generations predate the profile id but uniquely identify E5.
    if recipe == LEGACY_E5_VECTOR_RECIPE:
        return embeddings.DEFAULT_PROFILE_ID
    return None


def _vector_mapping_matches(mapping: dict[str, Any], profile_id: str, recipe: dict[str, Any]) -> bool:
    spec = embeddings.profile_spec(profile_id)
    field = mapping.get("properties", {}).get("rag_embedding", {})
    mapped_recipe = mapping.get("_meta", {}).get("private_vector_recipe")
    if field.get("type") != "dense_vector" or field.get("dims") != spec["dimensions"] or field.get("similarity") != spec["similarity"] or field.get("index") is not True:
        return False
    if mapped_recipe == recipe:
        return True
    return profile_id == embeddings.DEFAULT_PROFILE_ID and mapped_recipe == LEGACY_E5_VECTOR_RECIPE


def es_status(connection: Connection | None = None) -> dict[str, Any]:
    alias = _owner_alias()
    with concepts._connect_db() as db:
        _schema(db)
        state = dict(db.execute("SELECT * FROM knowledge_es_state WHERE id=1").fetchone())
        chunks = int(db.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0])
        docs = int(db.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0])
        profile_id, selected_recipe = _profile_state(db)
    # GET without ES credentials reports persisted sync metadata and local
    # fingerprint only. Search/sync pass a connection and verify the alias.
    expected_alias_state = True
    if connection is not None:
        try:
            targets = request(connection, "GET", f"_alias/{quote(alias, safe='')}")
            expected_target = f"{alias}-g{int(state['generation'])}"
            expected_alias_state = (not chunks and not targets) or (chunks > 0 and set(targets) == {expected_target})
        except ElasticsearchError as exc:
            if exc.status != 404:
                raise
            expected_alias_state = chunks == 0
    fingerprint = _local_fingerprint()
    in_sync = expected_alias_state and state["state"] == "in_sync" and fingerprint == state["synced_fingerprint"]
    if not chunks and int(state["generation"]) == 0 and state["state"] == "stale":
        status = "not_synced"
    else:
        status = "in_sync" if in_sync else (state["state"] if state["state"] in {"syncing", "error"} else "stale")
    vector_state = state["vector_state"]
    if status != "in_sync" and chunks:
        vector_state = "stale"
    recipe_ok = False
    if state["vector_recipe"]:
        try:
            active_recipe = json.loads(state["vector_recipe"])
            recipe_ok = bool(selected_recipe) and active_recipe == selected_recipe
            if not recipe_ok and profile_id == embeddings.DEFAULT_PROFILE_ID and active_recipe == LEGACY_E5_VECTOR_RECIPE:
                recipe_ok = True
            if _recipe_profile_id(active_recipe) != profile_id:
                recipe_ok = False
        except Exception:
            recipe_ok = False
    if vector_state == "in_sync" and not recipe_ok:
        vector_state = "stale"
    if not chunks:
        vector_state = "empty"
    if vector_state == "in_sync" and connection is not None:
        try:
            mappings = request(connection, "GET", f"{quote(alias, safe='')}/_mapping")
            mapping = next(iter(mappings.values())).get("mappings", {})
            mapped_recipe = mapping.get("_meta", {}).get("private_vector_recipe")
            if not _vector_mapping_matches(mapping, profile_id, selected_recipe):
                vector_state = "mapping_unavailable"
        except Exception:
            vector_state = "mapping_unavailable"
    runtime = embeddings.runtime_status(profile_id) if profile_id in {item["profile_id"] for item in embeddings.list_profiles()} else {"profile_id": profile_id, "status": "unknown_profile"}
    if profile_id == embeddings.DEFAULT_PROFILE_ID:
        tokenizer_status = token_preview.status()
    else:
        try:
            tokenizer_runtime = package_version("tokenizers")
        except PackageNotFoundError:
            tokenizer_runtime = None
        tokenizer_installed = tokenizer_runtime is not None
        tokenizer_status = {
            "available": bool(runtime.get("model_cached") and tokenizer_installed),
            "tokenizers_installed": tokenizer_installed,
            "tokenizers_version": tokenizer_runtime,
            "cached": bool(runtime.get("model_cached")),
            "model": runtime.get("model_name"),
            "revision": runtime.get("source_revision"),
            "max_tokens": selected_recipe.get("context_tokens"),
        }
    return {"state": status, "alias": alias, "local_documents": docs, "local_chunks": chunks, "indexed_chunks": state["indexed_chunks"], "last_synced_at": state["last_synced_at"], "error": state["error"], "vector_state": vector_state, "vector_chunks": state["vector_chunks"], "vector_profile_id": profile_id, "vector_profile_recipe": selected_recipe, "vector_profile_status": runtime, "vector_recipe": selected_recipe, "tokenizer": tokenizer_status}


def _local_fingerprint() -> str:
    with concepts._connect_db() as db:
        _schema(db)
        return _fingerprint_db(db)


def _fingerprint_db(db: sqlite3.Connection) -> str:
    rows = db.execute("SELECT d.id,d.title,d.source_label,c.id,c.ordinal,c.content FROM knowledge_documents d JOIN knowledge_chunks c ON c.document_id=d.id ORDER BY d.id,c.ordinal").fetchall()
    return _hash([tuple(row) for row in rows])


def _profile_tokenizer(profile_id: str) -> Any:
    if profile_id == embeddings.DEFAULT_PROFILE_ID:
        status = token_preview.status()
        if not status.get("available"):
            status = token_preview.prepare()
        if not status.get("available"):
            raise KnowledgeError(status.get("reason") or "Install the token-preview extra and prepare the pinned tokenizer before vector sync.", 503)
        # E5 slicing uses the pinned preview's exact offsets directly.
        return None
    profile = embeddings.profile_recipe(profile_id)
    revision = profile.get("source_revision")
    if not revision:
        raise KnowledgeError("The selected embedding profile is not cached locally; explicit vector sync must prepare it before tokenizing passages.", 503)
    try:
        from tokenizers import Tokenizer
        tokenizer_path = embeddings.cached_file_path(profile_id, "tokenizer.json")
        if tokenizer_path is None:
            raise FileNotFoundError("cached tokenizer is missing")
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        # Model tokenizer.json may carry a max-length truncation rule. Passage
        # boundaries and query-length checks need the full token sequence so
        # overlong input is split or rejected explicitly, never undercounted.
        tokenizer.no_truncation()
        return tokenizer
    except Exception:
        raise KnowledgeError("The selected profile tokenizer is unavailable in its verified local model cache; no generation was published.", 503) from None


def _profile_text_chunks(source: str, profile_id: str, tokenizer: Any, context_tokens: int) -> list[tuple[int, int]]:
    if profile_id == embeddings.DEFAULT_PROFILE_ID:
        offset = 0
        chunks = []
        while offset < len(source):
            remainder = source[offset:]
            preview = token_preview.preview_input(embeddings.format_embedding_input(remainder, "passage", profile_id))
            if not preview.get("available"):
                raise KnowledgeError("Pinned tokenizer could not safely inspect a passage; no vector generation was published.", 503)
            cut = len(remainder) if not preview.get("truncated") else int(preview.get("cut_char_offset", 0)) - len("passage: ")
            if cut <= 0 or cut > len(remainder):
                raise KnowledgeError("Pinned tokenizer could not produce a safe passage boundary; no vector generation was published.", 503)
            piece = remainder[:cut]
            checked = token_preview.preview_input(embeddings.format_embedding_input(piece, "passage", profile_id))
            if not checked.get("available") or checked.get("truncated"):
                raise KnowledgeError("A private passage exceeds the verified profile context; no vector generation was published.", 503)
            chunks.append((offset, offset + len(piece)))
            offset += len(piece)
        return chunks

    spans = _encode_offsets(tokenizer, source)
    if not spans:
        raise KnowledgeError("The selected tokenizer returned no source offsets; no vector generation was published.", 503)
    chunks: list[tuple[int, int]] = []
    token_index = 0
    start_offset = 0
    while token_index < len(spans):
        end_index = min(len(spans), token_index + context_tokens)
        end_offset = spans[end_index - 1][1]
        while end_offset > start_offset and _profile_token_count(tokenizer, embeddings.format_embedding_input(source[start_offset:end_offset], "passage", profile_id)) > context_tokens:
            end_index -= 1
            if end_index <= token_index:
                raise KnowledgeError("The selected profile context is too small for a passage; no generation was published.", 503)
            end_offset = spans[end_index - 1][1]
        if end_offset <= start_offset:
            raise KnowledgeError("The selected tokenizer did not advance through the source; no generation was published.", 503)
        chunks.append((start_offset, end_offset))
        if end_offset >= len(source):
            break
        token_index = end_index
        start_offset = end_offset
    if chunks[-1][1] < len(source):
        end = len(source)
        if _profile_token_count(tokenizer, embeddings.format_embedding_input(source[chunks[-1][0]:end], "passage", profile_id)) > context_tokens:
            raise KnowledgeError("Trailing source text exceeds the selected profile context; no generation was published.", 503)
        chunks[-1] = (chunks[-1][0], end)
    return chunks


def _encode_offsets(tokenizer: Any, text: str) -> list[tuple[int, int]]:
    try:
        encoded = tokenizer.encode(text, add_special_tokens=True)
    except TypeError:
        encoded = tokenizer.encode(text)
    return [tuple(map(int, offset)) for offset in encoded.offsets if tuple(offset) != (0, 0)]


def _profile_token_count(tokenizer: Any, text: str) -> int:
    try:
        encoded = tokenizer.encode(text, add_special_tokens=True)
    except TypeError:
        encoded = tokenizer.encode(text)
    return len(encoded.ids)


def _vector_passages(rows: list[sqlite3.Row], profile_id: str = embeddings.DEFAULT_PROFILE_ID,
                     tokenizer: Any = None) -> list[dict[str, Any]]:
    """Split each BM25 chunk into complete profile-context source slices."""
    spec = embeddings.profile_spec(profile_id)
    tokenizer = tokenizer or _profile_tokenizer(profile_id)
    passages: list[dict[str, Any]] = []
    for row in rows:
        source = str(row["content"])
        slices = _profile_text_chunks(source, profile_id, tokenizer, int(spec["context_tokens"]))
        for ordinal, (start, end) in enumerate(slices):
            passages.append({"document_id": row["document_id"], "chunk_id": row["chunk_id"], "ordinal": row["ordinal"], "passage_ordinal": ordinal, "start_offset": int(row["start_offset"]) + start, "end_offset": int(row["start_offset"]) + end, "text": source[start:end]})
        if not slices or slices[0][0] != 0 or slices[-1][1] != len(source) or any(left[1] != right[0] for left, right in zip(slices, slices[1:])):
            raise KnowledgeError("Private vector chunk coverage check failed; no vector generation was published.", 503)
    return passages


class _ReindexCancelled(Exception):
    pass


class _BulkFailure(Exception):
    def __init__(self, failures: list[dict[str, Any]]):
        super().__init__("one or more staged chunks failed")
        self.failures = failures


def _sync_es(connection: Connection, *, vector: bool = False, allow_model_download: bool = False,
             profile_id: str | None = None,
             progress: Any = None, cancel_check: Any = None, publish_lock: threading.Lock | None = None,
             on_published: Any = None) -> dict[str, Any]:
    alias = _owner_alias()
    owner = concepts._OWNER_ID.get()
    fingerprint = _local_fingerprint()
    with concepts._connect_db() as db:
        _schema(db)
        state = dict(db.execute("SELECT * FROM knowledge_es_state WHERE id=1").fetchone())
        generation = int(state["generation"]) + 1
        rows = db.execute("SELECT d.id document_id,d.title,d.source_label,c.id chunk_id,c.ordinal,c.start_offset,c.end_offset,c.content FROM knowledge_documents d JOIN knowledge_chunks c ON c.document_id=d.id ORDER BY d.id,c.ordinal").fetchall()
    passages: list[dict[str, Any]] = []
    vectors: list[list[float]] = []
    recipe: Any = ""
    profile_id = profile_id or state.get("vector_profile_id") or embeddings.DEFAULT_PROFILE_ID
    if vector:
        try:
            profile = embeddings.profile_spec(profile_id)
        except (ValueError, TypeError):
            raise KnowledgeError("Unknown private embedding profile") from None
    else:
        profile = None
    if vector:
        if allow_model_download is not True:
            raise KnowledgeError(f"Vector sync requires explicit consent to download/cache the {profile['model_name']} profile if it is not already cached.", 400)
        _save_profile_selection(profile_id)
        tokenizer = None
        if profile_id == embeddings.DEFAULT_PROFILE_ID:
            tokenizer_status = token_preview.status()
            if not tokenizer_status.get("available"):
                tokenizer_status = token_preview.prepare()
            if not tokenizer_status.get("available"):
                raise KnowledgeError(tokenizer_status.get("reason") or "Install the token-preview extra and prepare the pinned tokenizer before vector sync.", 503)
            tokenizer = _profile_tokenizer(profile_id)
        elif rows:
            try:
                embeddings._model(profile_id, local_files_only=False)
                tokenizer = _profile_tokenizer(profile_id)
            except ElasticsearchError:
                raise KnowledgeError(f"The {profile['model_name']} profile could not be prepared. Check its optional runtime/cache and retry; no generation was published.", 503) from None
        passages = _vector_passages(rows, profile_id, tokenizer) if rows else []
        try:
            vectors = embeddings.embed_texts([item["text"] for item in passages], "passage", local_files_only=False, profile_id=profile_id)
        except ElasticsearchError:
            if not embeddings.runtime_status(profile_id).get("runtime_installed"):
                raise KnowledgeError("FastEmbed is not installed. Install `.[private-vector]` and retry vector sync; BM25 remains available.", 503) from None
            raise KnowledgeError(f"The local {profile['model_name']} profile could not embed passages. Check its cache and retry; no new generation was published.", 503) from None
        if len(vectors) != len(passages):
            raise KnowledgeError("The embedding runtime returned an incomplete vector batch; no new generation was published.", 503)
        recipe = _private_profile_recipe(profile_id)
        with concepts._connect_db() as db:
            _schema(db)
            db.execute("UPDATE knowledge_es_state SET vector_profile_id=?,vector_profile_recipe=? WHERE id=1", (profile_id, json.dumps(recipe, sort_keys=True, separators=(",", ":"))))
    with concepts._connect_db() as db:
        _schema(db)
        db.execute("UPDATE knowledge_es_state SET state='syncing',generation=?,error='' WHERE id=1", (generation,))
    target = validate_index(f"{alias}-g{generation}")
    old: dict[str, Any] = {}
    alias_swapped = False
    publication_lock_held = False
    try:
        properties = {"owner_id": {"type": "keyword"}, "document_id": {"type": "keyword"}, "chunk_id": {"type": "keyword"}, "title": {"type": "text"}, "source_label": {"type": "text"}, "rag_chunk_text": {"type": "text"}, "ordinal": {"type": "integer"}, "start_offset": {"type": "integer"}, "end_offset": {"type": "integer"}, "passage_ordinal": {"type": "integer"}}
        if vector:
            properties["rag_embedding"] = {"type": "dense_vector", "dims": profile["dimensions"], "index": True, "similarity": profile["similarity"]}
        mappings = {"properties": properties}
        if vector:
            mappings["_meta"] = {"private_vector_recipe": recipe}
        request(connection, "PUT", quote(target, safe=''), {"mappings": mappings})
        staged_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if rows:
            items = []
            if vector:
                rows_by_chunk = {row["chunk_id"]: row for row in rows}
                for passage, embedding in zip(passages, vectors):
                    parent = rows_by_chunk[passage["chunk_id"]]
                    items.append(({"_index": target, "_id": f"{passage['chunk_id']}-{passage['passage_ordinal']}"}, {"owner_id": owner, "document_id": passage["document_id"], "chunk_id": passage["chunk_id"], "title": parent["title"], "source_label": parent["source_label"], "rag_chunk_text": passage["text"], "ordinal": passage["ordinal"], "passage_ordinal": passage["passage_ordinal"], "start_offset": passage["start_offset"], "end_offset": passage["end_offset"], "rag_embedding": embedding}))
            else:
                for row in rows:
                    items.append(({"_index": target, "_id": row["chunk_id"]}, {"owner_id": owner, "document_id": row["document_id"], "chunk_id": row["chunk_id"], "title": row["title"], "source_label": row["source_label"], "rag_chunk_text": row["content"], "ordinal": row["ordinal"], "start_offset": row["start_offset"], "end_offset": row["end_offset"]}))
            staged_items = items
            batch_size = 200
            for batch_start in range(0, len(items), batch_size):
                if cancel_check and cancel_check():
                    raise _ReindexCancelled()
                batch = items[batch_start:batch_start + batch_size]
                lines = []
                for action, document in batch:
                    lines.append(json.dumps({"index": action}, separators=(",", ":")))
                    lines.append(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
                bulk = request(connection, "POST", "_bulk", "\n".join(lines) + "\n", content_type="application/x-ndjson")
                failures = [item for result in bulk.get("items", []) for item in result.values() if int(item.get("status", 500)) >= 300]
                if bulk.get("errors") or failures or len(bulk.get("items", [])) != len(batch):
                    detail_by_id = {str(action.get("_id")): document for action, document in batch}
                    failed_chunks = []
                    for result in failures:
                        chunk_id = str(result.get("_id", ""))
                        document = detail_by_id.get(chunk_id, {})
                        failed_chunks.append({"document_id": document.get("document_id", ""), "chunk_id": chunk_id,
                                              "status": int(result.get("status", 500)), "message": "Elasticsearch rejected this staged chunk."})
                    raise _BulkFailure(failed_chunks[:50])
                if progress:
                    progress(min(batch_start + len(batch), len(items)), len(items))
        request(connection, "POST", f"{quote(target, safe='')}/_refresh")
        visible = request(connection, "POST", f"{quote(target, safe='')}/_search", {"size": 0, "track_total_hits": True, "query": {"match_all": {}}})
        total = visible.get("hits", {}).get("total", 0)
        visible_count = int(total.get("value", 0)) if isinstance(total, dict) else int(total)
        expected_count = len(passages) if vector else len(rows)
        if visible_count != expected_count:
            raise ElasticsearchError("Staged knowledge generation is not fully visible after refresh", 503)
        for verify_start in range(0, len(staged_items), 200):
            batch = staged_items[verify_start:verify_start + 200]
            expected_by_id = {str(action["_id"]): document for action, document in batch}
            verified = request(connection, "POST", f"{quote(target, safe='')}/_mget", {
                "docs": [{"_id": item_id, "_source": ["owner_id", "document_id", "chunk_id", "ordinal", "start_offset", "end_offset", "passage_ordinal"]}
                          for item_id in expected_by_id]
            })
            actual_by_id = {str(doc.get("_id")): doc for doc in verified.get("docs", [])}
            for item_id, expected in expected_by_id.items():
                actual = actual_by_id.get(item_id)
                source = actual.get("_source", {}) if actual else {}
                keys = ("owner_id", "document_id", "chunk_id", "ordinal", "start_offset", "end_offset")
                if not actual or not actual.get("found") or any(source.get(key) != expected.get(key) for key in keys):
                    raise ElasticsearchError("Staged knowledge generation contains a missing or mismatched chunk identity", 503)
                if "passage_ordinal" in expected and source.get("passage_ordinal") != expected.get("passage_ordinal"):
                    raise ElasticsearchError("Staged knowledge generation contains a mismatched passage identity", 503)
        if vector:
            staged_mappings = request(connection, "GET", f"{quote(target, safe='')}/_mapping")
            staged_mapping = next(iter(staged_mappings.values())).get("mappings", {})
            if not _vector_mapping_matches(staged_mapping, profile_id, recipe):
                raise ElasticsearchError("Staged private vector mapping or recipe does not match the requested generation", 503)
        try:
            old = request(connection, "GET", f"_alias/{quote(alias, safe='')}")
        except ElasticsearchError as exc:
            if exc.status != 404:
                raise
        if old:
            valid_old_targets = []
            for name in old:
                match = re.fullmatch(re.escape(alias) + r"-g([0-9]+)", str(name))
                if not match or int(match.group(1)) > generation - 1:
                    raise ElasticsearchError("Existing private alias target is outside the owned generation history", 409)
                valid_old_targets.append(name)
            if len(valid_old_targets) != 1:
                raise ElasticsearchError("Existing private alias has an unexpected target set", 409)
        if _local_fingerprint() != fingerprint:
            raise ElasticsearchError("Local knowledge changed during indexing; retry synchronization", 409)
        if cancel_check and cancel_check():
            raise _ReindexCancelled()
        if publish_lock is not None:
            publish_lock.acquire()
            publication_lock_held = True
            if cancel_check and cancel_check():
                raise _ReindexCancelled()
        actions = [{"remove": {"index": name, "alias": alias}} for name in old]
        if rows:
            actions.append({"add": {"index": target, "alias": alias, "is_write_index": True}})
        if actions:
            request(connection, "POST", "_aliases", {"actions": actions})
            alias_swapped = True
        with concepts._connect_db() as db:
            _schema(db)
            db.execute("BEGIN IMMEDIATE")
            current = _fingerprint_db(db)
            if current != fingerprint:
                raise ElasticsearchError("Local knowledge changed during indexing; retry synchronization", 409)
            db.execute("UPDATE knowledge_es_state SET state='in_sync',generation=?,indexed_chunks=?,local_fingerprint=?,synced_fingerprint=?,last_synced_at=?,error='',vector_state=?,vector_recipe=?,vector_chunks=?,vector_profile_id=?,vector_profile_recipe=? WHERE id=1", (generation, len(rows), fingerprint, fingerprint, _now(), "in_sync" if vector else "not_indexed", json.dumps(recipe, sort_keys=True, separators=(",", ":")) if vector else "", len(passages) if vector else 0, profile_id, json.dumps(recipe, sort_keys=True, separators=(",", ":")) if vector else state.get("vector_profile_recipe", "")))
        result = es_status(connection)
        if on_published:
            on_published()
        if publication_lock_held:
            publish_lock.release()
            publication_lock_held = False
        return result
    except Exception as exc:
        if alias_swapped:
            rollback = ([{"remove": {"index": target, "alias": alias}}] if rows else [])
            rollback.extend({"add": {"index": name, "alias": alias, **(meta.get("aliases", {}).get(alias, {}))}} for name, meta in old.items())
            try:
                request(connection, "POST", "_aliases", {"actions": rollback})
            except Exception:
                pass
        if publication_lock_held:
            publish_lock.release()
            publication_lock_held = False
        try:
            request(connection, "DELETE", quote(target, safe=''))
        except Exception:
            pass
        if isinstance(exc, _ReindexCancelled):
            with concepts._connect_db() as db:
                _schema(db)
                db.execute("UPDATE knowledge_es_state SET state='stale',error='Reindex cancelled; prior generation remains selected' WHERE id=1")
            raise
        with concepts._connect_db() as db:
            _schema(db)
            safe_error = f"Elasticsearch sync failed (HTTP {exc.status})" if isinstance(exc, ElasticsearchError) and exc.status else "Elasticsearch sync failed"
            db.execute("UPDATE knowledge_es_state SET state='error',error=? WHERE id=1", (safe_error,))
        wrapped = KnowledgeError("Private knowledge sync failed; the previous generation remains selected. Retry synchronization.", 503)
        if isinstance(exc, _BulkFailure):
            wrapped.failed_documents = exc.failures
        raise wrapped from None


def sync_es(connection: Connection, *, vector: bool = False, allow_model_download: bool = False,
             profile_id: str | None = None) -> dict[str, Any]:
    owner = concepts._OWNER_ID.get()
    if not owner:
        raise KnowledgeError("Authenticated account scope is required", 401)
    with _SYNC_LOCKS_GUARD:
        lock = _SYNC_LOCKS.setdefault(owner, threading.Lock())
    if not lock.acquire(blocking=False):
        raise KnowledgeError("A private knowledge sync is already running for this account. Retry after it finishes.", 409)
    try:
        with private_sync_scope():
            return _sync_es(connection, vector=vector, allow_model_download=allow_model_download, profile_id=profile_id)
    finally:
        lock.release()


_JOB_STATES = {"queued", "running", "cancelling", "cancelled", "interrupted", "failed", "complete"}
_ACTIVE_JOB_IDS: set[str] = set()
_ACTIVE_JOB_IDS_GUARD = threading.Lock()
_JOB_PUBLISH_LOCKS: dict[str, threading.Lock] = {}
_JOB_PUBLISH_LOCKS_GUARD = threading.Lock()


def _job_publish_lock(job_id: str) -> threading.Lock:
    with _JOB_PUBLISH_LOCKS_GUARD:
        return _JOB_PUBLISH_LOCKS.setdefault(job_id, threading.Lock())


def _recover_jobs(db: sqlite3.Connection) -> None:
    with _ACTIVE_JOB_IDS_GUARD:
        active = tuple(_ACTIVE_JOB_IDS)
    if active:
        placeholders = ",".join("?" for _ in active)
        db.execute(f"UPDATE knowledge_reindex_jobs SET state='interrupted',safe_error='The server stopped before publication. Retry this job to resume from local source documents.',updated_at=? WHERE state IN ('queued','running','cancelling') AND id NOT IN ({placeholders})", (_now(), *active))
    else:
        db.execute("UPDATE knowledge_reindex_jobs SET state='interrupted',safe_error='The server stopped before publication. Retry this job to resume from local source documents.',updated_at=? WHERE state IN ('queued','running','cancelling')", (_now(),))


def _job_record(row: sqlite3.Row) -> dict[str, Any]:
    return {"job_id": row["id"], "state": row["state"], "completed": int(row["completed_documents"]),
            "total": int(row["total_documents"]), "failed_documents": json.loads(row["failed_documents_json"] or "[]"),
            "generation": row["target_generation"], "safe_error": row["safe_error"], "updated_at": row["updated_at"]}


def reindex_status(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = _text(payload.get("job_id"), "job_id", 64)
    with concepts._connect_db() as db:
        _schema(db)
        _recover_jobs(db)
        row = db.execute("SELECT * FROM knowledge_reindex_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise KnowledgeError("Reindex job not found", 404)
    return _job_record(row)


def reindex_latest(_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with concepts._connect_db() as db:
        _schema(db)
        _recover_jobs(db)
        row = db.execute("SELECT * FROM knowledge_reindex_jobs ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
    return {"job": _job_record(row) if row else None}


def _job_update(job_id: str, **values: Any) -> None:
    allowed = {"state", "completed_documents", "failed_documents_json", "target_generation", "safe_error", "cancel_requested"}
    if set(values) - allowed:
        raise ValueError("unsupported job update")
    values["updated_at"] = _now()
    assignments = ",".join(f"{key}=?" for key in values)
    with concepts._connect_db() as db:
        _schema(db)
        db.execute(f"UPDATE knowledge_reindex_jobs SET {assignments} WHERE id=?", (*values.values(), job_id))


def _document_source_fingerprint(rows: list[sqlite3.Row]) -> str:
    return _hash([(row["id"], int(row["revision"]), row["title"], row["source_label"], row["content"]) for row in rows])


def _run_reindex(owner: str, job_id: str, connection: Connection) -> None:
    with _ACTIVE_JOB_IDS_GUARD:
        _ACTIVE_JOB_IDS.add(job_id)
    current_document_id: str | None = None
    try:
        with concepts.owner_scope(owner):
            with _SYNC_LOCKS_GUARD:
                lock = _SYNC_LOCKS.setdefault(owner, threading.Lock())
            if not lock.acquire(blocking=False):
                _job_update(job_id, state="failed", safe_error="Another private sync is running for this account. Retry after it finishes.")
                return
            try:
                with concepts._connect_db() as db:
                    _schema(db)
                    job = db.execute("SELECT * FROM knowledge_reindex_jobs WHERE id=?", (job_id,)).fetchone()
                    policy = chunking.normalize_policy(json.loads(job["policy_json"]))
                    fingerprint = chunking.policy_fingerprint(policy)
                    if fingerprint != job["policy_sha256"]:
                        raise KnowledgeError("Saved chunk policy fingerprint is invalid; retry with a new job.")
                    tokenizer = None
                    if policy.get("strategy") == "token":
                        info = chunking.tokenizer_info()
                        if not info.get("available"):
                            raise KnowledgeError(info.get("reason") or "Pinned tokenizer is unavailable; install and prepare the pinned tokenizer before retrying.", 503)
                        tokenizer = token_preview._load_tokenizer()
                    rows = db.execute("SELECT id,title,source_label,content,revision FROM knowledge_documents ORDER BY id").fetchall()
                    source_fingerprint = _document_source_fingerprint(rows)
                    if source_fingerprint != job["source_fingerprint"]:
                        raise KnowledgeError("Local documents changed after this job was queued. Start a new reindex to publish current sources.", 409)
                    if db.execute("SELECT cancel_requested FROM knowledge_reindex_jobs WHERE id=?", (job_id,)).fetchone()[0]:
                        _job_update(job_id, state="cancelled", safe_error="Cancelled before indexing; the previous generation remains selected.")
                        return
                    db.execute("BEGIN IMMEDIATE")
                    current_sources = db.execute("SELECT id,title,source_label,content,revision FROM knowledge_documents ORDER BY id").fetchall()
                    if _document_source_fingerprint(current_sources) != source_fingerprint:
                        raise KnowledgeError("Local documents changed while preparing reindex chunks. The previous generation remains selected; start a new job.", 409)
                    for doc in rows:
                        current_document_id = str(doc["id"])
                        db.execute("DELETE FROM knowledge_fts WHERE document_id=?", (doc["id"],))
                        db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (doc["id"],))
                        chunks = chunking.split_text(doc["content"], policy, tokenizer=tokenizer)
                        for chunk in chunks:
                            chunk_id = hashlib.sha256(f"{doc['id']}:{doc['revision']}:{fingerprint}:{chunk['ordinal']}:{chunk['start_offset']}:{chunk['end_offset']}".encode()).hexdigest()
                            db.execute("INSERT INTO knowledge_chunks(id,document_id,ordinal,start_offset,end_offset,content,source_revision,policy_sha256,token_count) VALUES(?,?,?,?,?,?,?,?,?)", (chunk_id, doc["id"], chunk["ordinal"], chunk["start_offset"], chunk["end_offset"], chunk["content"], doc["revision"], fingerprint, chunk.get("token_count")))
                            db.execute("INSERT INTO knowledge_fts(content,title,source_label,document_id,chunk_id) VALUES(?,?,?,?,?)", (chunk["content"], doc["title"], doc["source_label"], doc["id"], chunk_id))
                    current_document_id = None
                    db.commit()
                _job_update(job_id, state="running", completed_documents=0, target_generation="")
                state = {}
                with concepts._connect_db() as db:
                    state = dict(db.execute("SELECT generation FROM knowledge_es_state WHERE id=1").fetchone())
                _job_update(job_id, target_generation=f"{_owner_alias()}-g{int(state['generation']) + 1}")

                def cancelled() -> bool:
                    with concepts._connect_db() as db:
                        current_job = db.execute("SELECT cancel_requested,source_fingerprint FROM knowledge_reindex_jobs WHERE id=?", (job_id,)).fetchone()
                        current_docs = db.execute("SELECT id,title,source_label,content,revision FROM knowledge_documents ORDER BY id").fetchall()
                    if _document_source_fingerprint(current_docs) != current_job["source_fingerprint"]:
                        raise KnowledgeError("Local documents changed during reindex. The previous generation remains selected; start a new job.", 409)
                    return bool(current_job["cancel_requested"])

                def progress(done_chunks: int, total_chunks: int) -> None:
                    if cancelled():
                        raise _ReindexCancelled()
                    with concepts._connect_db() as db:
                        counts = [int(row["chunk_count"]) for row in db.execute("SELECT d.id,COUNT(c.id) AS chunk_count FROM knowledge_documents d LEFT JOIN knowledge_chunks c ON c.document_id=d.id GROUP BY d.id ORDER BY d.id")]
                    completed = 0
                    consumed = 0
                    for count in counts:
                        consumed += count
                        if consumed <= done_chunks:
                            completed += 1
                        else:
                            break
                    _job_update(job_id, completed_documents=completed)

                try:
                    with private_sync_scope():
                        _sync_es(connection, progress=progress, cancel_check=cancelled,
                                 publish_lock=_job_publish_lock(job_id),
                                 on_published=lambda: _job_update(job_id, state="complete", completed_documents=len(rows), safe_error=""))
                except _ReindexCancelled:
                    _job_update(job_id, state="cancelled", safe_error="Cancelled before alias publication; the previous generation remains selected.")
            finally:
                lock.release()
    except Exception as exc:
        safe = str(exc)[:300] if isinstance(exc, KnowledgeError) else "Reindex failed before publication. Check the private Elasticsearch connection and retry."
        failures = getattr(exc, "failed_documents", None) or ([{"document_id": current_document_id, "message": safe}] if current_document_id else [])
        # The main worker scope has unwound before this handler runs. Rebind the
        # authenticated owner so failure state is persisted to the same account DB.
        with concepts.owner_scope(owner):
            _job_update(job_id, state="failed", safe_error=safe,
                        failed_documents_json=json.dumps(failures, separators=(",", ":")))
    finally:
        with _ACTIVE_JOB_IDS_GUARD:
            _ACTIVE_JOB_IDS.discard(job_id)


def reindex_start(payload: dict[str, Any], connection: Connection) -> dict[str, Any]:
    owner = concepts._OWNER_ID.get()
    if not owner:
        raise KnowledgeError("Authenticated account scope is required", 401)
    if set(payload) - {"connection", "policy"}:
        raise KnowledgeError("Reindex accepts only connection and policy; account and alias are server-derived")
    with concepts._connect_db() as db:
        _schema(db)
        _recover_jobs(db)
        active = db.execute("SELECT 1 FROM knowledge_reindex_jobs WHERE state IN ('queued','running','cancelling') LIMIT 1").fetchone()
        if active:
            raise KnowledgeError("A reindex job is already active for this account", 409)
        if payload.get("policy") is None:
            policy, fingerprint = _saved_policy(db)
        else:
            try:
                policy = chunking.normalize_policy(payload["policy"])
            except Exception as exc:
                raise KnowledgeError(str(exc)) from None
            fingerprint = chunking.policy_fingerprint(policy)
            db.execute("UPDATE knowledge_chunk_policy SET policy_json=?,policy_sha256=?,updated_at=? WHERE id=1", (json.dumps(policy, sort_keys=True, separators=(",", ":")), fingerprint, _now()))
            if db.execute("SELECT 1 FROM knowledge_chunks WHERE policy_sha256<>? LIMIT 1", (fingerprint,)).fetchone():
                _mark_es_stale(db)
        if policy.get("strategy") == "token" and not chunking.tokenizer_info().get("available"):
            raise KnowledgeError(chunking.tokenizer_info().get("reason") or "Pinned tokenizer is unavailable", 503)
        rows = db.execute("SELECT id,title,source_label,content,revision FROM knowledge_documents ORDER BY id").fetchall()
        source_fingerprint = _document_source_fingerprint(rows)
        job_id = str(uuid.uuid4())
        now = _now()
        policy_json = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        db.execute("INSERT INTO knowledge_reindex_jobs(id,state,policy_json,policy_sha256,created_at,updated_at,total_documents,completed_documents,failed_documents_json,source_fingerprint,target_generation,safe_error,cancel_requested) VALUES(?,'queued',?,?,?,?,?,0,'[]',?,'','',0)", (job_id, policy_json, fingerprint, now, now, len(rows), source_fingerprint))
    thread = threading.Thread(target=_run_reindex, args=(owner, job_id, connection), name=f"knowledge-reindex-{job_id[:8]}", daemon=True)
    with _ACTIVE_JOB_IDS_GUARD:
        _ACTIVE_JOB_IDS.add(job_id)
    thread.start()
    return {"job_id": job_id, "state": "queued", "total": len(rows), "generation": "", "alias": _owner_alias()}


def reindex_cancel(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = _text(payload.get("job_id"), "job_id", 64)
    lock = _job_publish_lock(job_id)
    with lock:
        with concepts._connect_db() as db:
            _schema(db)
            row = db.execute("SELECT state FROM knowledge_reindex_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KnowledgeError("Reindex job not found", 404)
        if row["state"] in {"complete", "failed", "interrupted", "cancelled"}:
            return reindex_status({"job_id": job_id})
        _job_update(job_id, state="cancelling", cancel_requested=1, safe_error="Cancellation requested; the prior generation remains selected until publication completes.")
    return reindex_status({"job_id": job_id})


def reindex_retry(payload: dict[str, Any], connection: Connection) -> dict[str, Any]:
    job_id = _text(payload.get("job_id"), "job_id", 64)
    with concepts._connect_db() as db:
        _schema(db)
        previous = db.execute("SELECT policy_json FROM knowledge_reindex_jobs WHERE id=?", (job_id,)).fetchone()
    if not previous:
        raise KnowledgeError("Reindex job not found", 404)
    return reindex_start({"connection": payload.get("connection"), "policy": json.loads(previous["policy_json"])}, connection)


def search_es(connection: Connection, query: str, limit: int = 10) -> dict[str, Any]:
    with private_read_scope():
        status = es_status(connection)
        if status["local_chunks"] == 0:
            return {"state": "empty", "mode": "bm25", "results": []}
        if status["state"] != "in_sync":
            return {"state": "stale", "mode": "bm25", "results": [], "local_chunks": status["local_chunks"], "message": "Private knowledge index is stale or unavailable; synchronize it before searching."}
        alias = _owner_alias()
        owner = concepts._OWNER_ID.get()
        body = {"size": max(1, min(20, int(limit))), "track_total_hits": True,
                "query": {"bool": {"must": [{"multi_match": {"query": query, "type": "best_fields", "fields": ["rag_chunk_text^1", "title^3", "source_label^1.5"]}}], "filter": [{"term": {"owner_id": owner}}]}},
                "_source": ["document_id", "chunk_id", "title", "source_label", "rag_chunk_text", "ordinal"]}
        result = request(connection, "POST", f"{quote(alias, safe='')}/_search", body)
        final_status = es_status(connection)
        if final_status["state"] != "in_sync":
            return {"state": "stale", "mode": "bm25", "results": [], "local_chunks": final_status["local_chunks"], "message": "Private knowledge changed during search; results were withheld. Synchronize before searching again."}
        hits = result.get("hits", {}).get("hits", [])
        return {"state": "in_sync", "mode": "bm25", "results": [{"_index": alias, "_id": hit.get("_id"), "_score": hit.get("_score"), "_source": hit.get("_source", {}), "private_knowledge": True} for hit in hits]}


def search_es_mode(connection: Connection, query: str, mode: str, limit: int = 10,
                   profile_id: str | None = None) -> dict[str, Any]:
    if mode == "bm25":
        return search_es(connection, query, limit)
    if mode not in {"vector", "hybrid"}:
        raise KnowledgeError("Private search mode must be bm25, vector, or hybrid")
    with private_read_scope():
        status = es_status(connection)
        if profile_id is not None and profile_id != status.get("vector_profile_id"):
            return {"state": "profile_mismatch", "mode": mode, "results": [], "message": "The requested vector profile does not match the profile saved for this account."}
        if status["local_chunks"] == 0:
            return {"state": "empty", "mode": mode, "results": [], "message": "No private knowledge documents are saved."}
        if status["state"] != "in_sync":
            return {"state": "stale", "mode": mode, "results": [], "message": "Private knowledge changed or its Elasticsearch generation is unavailable; synchronize before searching."}
        if status["vector_state"] != "in_sync":
            return {"state": status["vector_state"], "mode": mode, "results": [], "message": "Private vectors are not current. Install the semantic and token-preview extras, prepare the model/tokenizer with consent, then run vector sync."}
        owner = concepts._OWNER_ID.get()
        if not owner:
            raise KnowledgeError("Authenticated account scope is required", 401)
        alias = _owner_alias()
        selected_profile = str(status["vector_profile_id"])
        try:
            profile_spec = embeddings.profile_spec(selected_profile)
        except (ValueError, TypeError):
            return {"state": "profile_unavailable", "mode": mode, "results": [], "message": "The saved private embedding profile is unknown. Select a supported profile and sync again."}
        model_status = embeddings.runtime_status(selected_profile)
        if not model_status.get("runtime_installed"):
            return {"state": "model_unavailable", "mode": mode, "results": [], "message": "Install the private-vector extra before searching private vectors. Private BM25 remains available."}
        if not model_status.get("model_cached"):
            return {"state": "model_unavailable", "mode": mode, "results": [], "message": f"The {profile_spec['model_name']} model cache is missing. Run explicit vector sync again and consent to restore it; search will not download it."}
        if selected_profile == embeddings.DEFAULT_PROFILE_ID:
            tokenizer_status = token_preview.status()
            if not tokenizer_status.get("available"):
                return {"state": "tokenizer_unavailable", "mode": mode, "results": [], "message": "The pinned E5 tokenizer cache is missing or unavailable. Run explicit vector sync again to verify or prepare it."}
            query_check = token_preview.preview_input(embeddings.format_embedding_input(query, "query", selected_profile))
            if not query_check.get("available"):
                return {"state": "tokenizer_unavailable", "mode": mode, "results": [], "message": "The pinned E5 tokenizer could not safely check the query; private vector results are withheld."}
            if query_check.get("truncated"):
                return {"state": "query_too_long", "mode": mode, "results": [], "message": "This query exceeds the E5 512-token limit. Shorten the query; it will not be silently truncated."}
        else:
            try:
                tokenizer = _profile_tokenizer(selected_profile)
                query_count = _profile_token_count(tokenizer, embeddings.format_embedding_input(query, "query", selected_profile))
            except KnowledgeError:
                return {"state": "tokenizer_unavailable", "mode": mode, "results": [], "message": "The selected profile tokenizer is unavailable locally. Run explicit vector sync to prepare and verify it."}
            if query_count > int(profile_spec["context_tokens"]):
                return {"state": "query_too_long", "mode": mode, "results": [], "message": f"This query exceeds the selected profile's {profile_spec['context_tokens']}-token context. Shorten it; it will not be silently truncated."}
        query_vector = embeddings.embed_texts([query], "query", local_files_only=True, profile_id=selected_profile)[0]
        source_fields = ["document_id", "chunk_id", "title", "source_label", "rag_chunk_text", "ordinal", "start_offset", "end_offset"]
        vector_body = {"size": max(1, min(20, int(limit))), "knn": {"field": "rag_embedding", "query_vector": query_vector, "k": max(1, min(20, int(limit))), "num_candidates": min(10000, max(50, int(limit) * 10)), "filter": {"term": {"owner_id": owner}}}, "_source": source_fields}
        vector_result = request(connection, "POST", f"{quote(alias, safe='')}/_search", vector_body)
        vector_hits = vector_result.get("hits", {}).get("hits", [])
        if mode == "vector":
            hits = vector_hits
        else:
            lexical_body = {"size": max(1, min(20, int(limit))), "track_total_hits": True, "query": {"bool": {"must": [{"multi_match": {"query": query, "type": "best_fields", "fields": ["rag_chunk_text^1", "title^3", "source_label^1.5"]}}], "filter": [{"term": {"owner_id": owner}}]}}, "_source": source_fields}
            lexical_result = request(connection, "POST", f"{quote(alias, safe='')}/_search", lexical_body)
            lexical_hits = lexical_result.get("hits", {}).get("hits", [])
            hits = _private_rrf(lexical_hits, vector_hits, max(1, min(20, int(limit))), 60)
        final = es_status(connection)
        if final["state"] != "in_sync" or final["vector_state"] != "in_sync":
            return {"state": "stale", "mode": mode, "results": [], "message": "Private knowledge changed during search; results were withheld. Synchronize before searching again."}
        return {"state": "in_sync", "mode": mode, "results": [{"_index": alias, "_id": hit.get("_id"), "_score": hit.get("_score"), "_source": hit.get("_source", {}), "private_knowledge": True, **({"retrieval_scores": hit["retrieval_scores"]} if "retrieval_scores" in hit else {}), **({"lane_ranks": hit["lane_ranks"]} if "lane_ranks" in hit else {})} for hit in hits]}


def _private_rrf(lexical: list[dict[str, Any]], vector: list[dict[str, Any]], limit: int, rank_constant: int) -> list[dict[str, Any]]:
    fused: dict[tuple[str, str], dict[str, Any]] = {}
    for lane, hits in (("bm25", lexical), ("vector", vector)):
        for rank, hit in enumerate(hits, 1):
            key = (str(hit.get("_index", "")), str(hit.get("_id", "")))
            item = fused.setdefault(key, {**hit, "_private_rrf": 0.0, "retrieval_scores": {"bm25": None, "vector": None}, "lane_ranks": {}})
            item["_private_rrf"] += 1.0 / (rank_constant + rank)
            item["lane_ranks"][lane] = rank
            item["retrieval_scores"][lane] = hit.get("_score")
    ordered = sorted(fused.values(), key=lambda hit: (-hit["_private_rrf"], str(hit.get("_id", ""))))[:limit]
    for item in ordered:
        # Match the shared RRF contract: the exposed score is rank-derived.
        # Raw Elasticsearch scores are retained only under named components.
        item["_score"] = item.pop("_private_rrf")
    return ordered


def search(payload: dict[str, Any]) -> dict[str, Any]:
    query = _text(payload.get("query"), "query", MAX_SEARCH_QUERY_CODEPOINTS)
    limit = payload.get("limit", DEFAULT_SEARCH_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise KnowledgeError("limit must be an integer from 1 to 20")
    # Treat arbitrary beginner text as literal Unicode terms. Every term is
    # quoted before being passed to FTS5; operators and column syntax cannot run.
    terms = _WORD_RE.findall(query)
    if not terms:
        return {"query": query, "results": []}
    match_query = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
    with concepts._connect_db() as db:
        _schema(db)
        rows = db.execute("""SELECT f.chunk_id,f.document_id,f.content AS chunk,d.title,d.source_label,d.updated_at,
                   bm25(knowledge_fts,1.0,3.0,1.5,0.0,0.0) AS score
                   FROM knowledge_fts f JOIN knowledge_documents d ON d.id=f.document_id
                   WHERE knowledge_fts MATCH ? ORDER BY score ASC,d.updated_at DESC,f.chunk_id LIMIT ?""", (match_query, limit)).fetchall()
        results = []
        for row in rows:
            text = row["chunk"]
            excerpt = text[:280] + ("…" if len(text) > 280 else "")
            results.append({"document_id": row["document_id"], "title": row["title"], "source_label": row["source_label"],
                            "chunk_id": row["chunk_id"], "chunk": text, "excerpt": excerpt, "score": row["score"]})
        return {"query": query, "results": results}


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _literal_match(terms: list[str]) -> str:
    # Each term is quoted independently. Concept text can never introduce FTS syntax.
    unique = list(dict.fromkeys(term.casefold() for term in terms if term))
    if len(unique) > 200:
        raise KnowledgeError("A local concept search is limited to 200 unique literal terms; shorten the saved query or concept text.")
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in unique)


def _document_fingerprint(row: sqlite3.Row) -> str:
    return _hash({"title": row["title"], "source_label": row["source_label"], "content": row["content"]})


def _query_terms(query: str) -> list[str]:
    return _WORD_RE.findall(query)


def _contains_phrase(text: str, phrase: tuple[str, ...]) -> bool:
    tokens = tuple(token.casefold() for token in _query_terms(text))
    width = len(phrase)
    return bool(width) and any(tokens[offset:offset + width] == phrase for offset in range(len(tokens) - width + 1))


def _rank_local(db: sqlite3.Connection, terms: list[str], limit: int,
                excluded_phrases: list[tuple[str, ...]] | None = None) -> tuple[int, list[dict[str, Any]]]:
    match = _literal_match(terms)
    if not match:
        return 0, []
    rows = db.execute("""SELECT f.chunk_id,f.document_id,f.content AS chunk,d.title,d.source_label,d.content AS document_content,d.updated_at,
               bm25(knowledge_fts,1.0,3.0,1.5,0.0,0.0) AS score
               FROM knowledge_fts f JOIN knowledge_documents d ON d.id=f.document_id
               WHERE knowledge_fts MATCH ? ORDER BY score ASC,d.id ASC,f.chunk_id ASC""", (match,)).fetchall()
    best: dict[str, sqlite3.Row] = {}
    exclusion_cache: dict[str, bool] = {}
    for row in rows:
        if excluded_phrases:
            excluded = exclusion_cache.get(row["document_id"])
            if excluded is None:
                searchable = (row["document_content"], row["title"], row["source_label"])
                excluded = any(_contains_phrase(value, phrase) for value in searchable for phrase in excluded_phrases)
                exclusion_cache[row["document_id"]] = excluded
            if excluded:
                continue
        best.setdefault(row["document_id"], row)
    ranked = sorted(best.values(), key=lambda row: (float(row["score"]), row["document_id"], row["chunk_id"]))
    hits = []
    for rank, row in enumerate(ranked[:limit], 1):
        excerpt = row["chunk"][:280] + ("…" if len(row["chunk"]) > 280 else "")
        hits.append({"document_id": row["document_id"], "title": row["title"], "source_label": row["source_label"],
                     "chunk_id": row["chunk_id"], "excerpt": excerpt, "score": float(row["score"]), "rank": rank})
    return len(ranked), hits


def _attach_matched_groups(db: sqlite3.Connection, hits: list[dict[str, Any]],
                           groups: dict[str, list[str]]) -> None:
    """Attach fixed group IDs that match each hit's representative FTS row."""
    if not hits:
        return
    chunk_ids = [hit["chunk_id"] for hit in hits]
    matched_by_chunk = {chunk_id: [] for chunk_id in chunk_ids}
    placeholders = ",".join("?" for _ in chunk_ids)
    # One bounded query per fixed group, never one query per result or corpus scan.
    for group_id, terms in groups.items():
        expression = _literal_match(terms)
        if not expression:
            continue
        rows = db.execute(
            f"SELECT f.chunk_id FROM knowledge_fts f WHERE knowledge_fts MATCH ? AND f.chunk_id IN ({placeholders})",
            (expression, *chunk_ids),
        ).fetchall()
        for row in rows:
            matched_by_chunk[row["chunk_id"]].append(group_id)
    for hit in hits:
        hit["matched_groups"] = matched_by_chunk.get(hit["chunk_id"], [])


def _judgments_for(db: sqlite3.Connection, concept_id: str, query_id: str, query_fingerprint: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    rows = db.execute("SELECT * FROM knowledge_judgments WHERE concept_id=? AND query_id=?", (concept_id, query_id)).fetchall()
    active: dict[str, dict[str, Any]] = {}
    stale: list[dict[str, Any]] = []
    for saved in rows:
        row = dict(saved)
        document = db.execute("SELECT id,title,source_label,content FROM knowledge_documents WHERE id=?", (row["document_id"],)).fetchone()
        is_stale = (row["query_fingerprint"] != query_fingerprint or document is None or _document_fingerprint(document) != row["document_fingerprint"])
        row["stale"] = is_stale
        if is_stale:
            stale.append(row)
        else:
            active[row["document_id"]] = row
    return active, stale


def _metrics(hits: list[dict[str, Any]], active: dict[str, dict[str, Any]], stale: list[dict[str, Any]], all_rows: list[dict[str, Any]], k: int = CONCEPT_PREVIEW_LIMIT) -> dict[str, Any]:
    grades = {doc_id: int(row["rating"]) for doc_id, row in active.items() if row["rating"] is not None}
    ranked = hits[:k]
    judged_ranked = [hit for hit in ranked if hit["document_id"] in grades]
    dcg = sum((2 ** grades[hit["document_id"]] - 1) / math.log2(position + 1)
              for position, hit in enumerate(judged_ranked, 1))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1))
    positive = sum(grade > 0 for grade in grades.values())
    found = sum(grades.get(hit["document_id"], 0) > 0 for hit in ranked)
    judged_retrieved = sum(hit["document_id"] in grades for hit in ranked)
    sources: dict[str, dict[str, int]] = {}
    def bucket(source: str) -> dict[str, int]:
        return sources.setdefault(source or "(empty)", {"judged": 0, "positive": 0, "unjudged": 0, "stale": 0})
    for row in all_rows:
        counts = bucket(row["source_label"])
        if row["stale"]:
            counts["stale"] += 1
        elif row["rating"] is None:
            counts["unjudged"] += 1
        else:
            counts["judged"] += 1
            counts["positive"] += int(int(row["rating"]) > 0)
    return {"k": k, "ndcg_at_k": dcg / idcg if idcg else 0.0,
            "judged_coverage": judged_retrieved / len(ranked) if ranked else 0.0,
            "known_positive_recall": found / positive if positive else 0.0,
            "judged_count": len(grades), "positive_count": positive,
            "unjudged_count": sum(row["rating"] is None and not row["stale"] for row in all_rows),
            "stale_count": len(stale), "source_counts": sources}


def _saved_context(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"concept_id", "query_id"}:
        raise KnowledgeError("request must contain only concept_id and query_id")
    concept_id = _text(payload.get("concept_id"), "concept_id", 128)
    query_id = _text(payload.get("query_id"), "query_id", 128)
    try:
        concept = concepts.get_saved_concept(concept_id)
    except concepts.ElasticsearchError as exc:
        message = str(exc) if exc.safe_for_user else "Saved knowledge context is unavailable."
        raise KnowledgeError(message, exc.status or 400) from None
    query = next((item for item in concept["queries"] if item["id"] == query_id), None)
    if query is None:
        raise KnowledgeError("Saved query not found", 404)
    return concept, query


def concept_preview(payload: dict[str, Any]) -> dict[str, Any]:
    concept, query = _saved_context(payload)
    query_fp = concepts._query_judgment_fingerprint(query)
    base_terms = _query_terms(query["query"])
    excluded = {term.casefold() for value in concept.get("excluded_terms", []) for term in _query_terms(value)}
    excluded_phrases = [tuple(term.casefold() for term in _query_terms(value))
                        for value in concept.get("excluded_terms", []) if _query_terms(value)]
    concept_weight = float(concept.get("settings", {}).get("concept_weight", 1))
    concept_expression_count = sum(bool(value and str(value).strip()) for value in [concept["name"], concept.get("description", ""), *concept.get("aliases", [])])
    concept_expressions = ([concept["name"], concept.get("description", ""), *concept.get("aliases", [])]
                           if concept_weight > 0 else [])
    related_weight = float(concept.get("settings", {}).get("related_weight", 1))
    related_terms = concept.get("related", [])
    related_terms_included = sum(1 for item in related_terms if related_weight > 0 and float(item.get("weight", 1)) > 0)
    eligible_related = [item["term"] for item in related_terms
                        if related_weight > 0 and float(item.get("weight", 1)) > 0]
    concept_group_terms = [term for value in concept_expressions for term in _query_terms(value)
                           if term.casefold() not in excluded]
    related_group_terms = [term for value in eligible_related for term in _query_terms(value)
                           if term.casefold() not in excluded]
    expansion_terms = [*concept_group_terms, *related_group_terms]
    expanded_terms = list(dict.fromkeys([*base_terms, *expansion_terms]))
    with concepts._connect_db() as db:
        _schema(db)
        db.execute("BEGIN")
        total_bytes = db.execute("SELECT id,title,source_label,content FROM knowledge_documents ORDER BY id").fetchall()
        document_fingerprints = [{"id": row["id"], "fingerprint": _document_fingerprint(row)} for row in total_bytes]
        corpus_fingerprint = _hash({"documents": document_fingerprints, "recipe": {"tokenizer": "unicode61", "chunk_codepoints": CHUNK_CODEPOINTS, "chunk_overlap": CHUNK_OVERLAP, "version": CONCEPT_RECIPE_VERSION, "weights": {"content": 1.0, "title": 3.0, "source_label": 1.5}}})
        total_baseline, baseline_hits = _rank_local(db, base_terms, CONCEPT_PREVIEW_LIMIT)
        total_expanded, expanded_hits = _rank_local(db, expanded_terms, CONCEPT_PREVIEW_LIMIT, excluded_phrases)
        for hit in baseline_hits:
            hit["matched_groups"] = ["saved_query"]
        _attach_matched_groups(db, expanded_hits, {
            "saved_query": base_terms,
            "concept_expressions": concept_group_terms,
            "related_terms": related_group_terms,
        })
        judgments, stale = _judgments_for(db, concept["id"], query["id"], query_fp)
        all_rows = []
        for row in db.execute("SELECT * FROM knowledge_judgments WHERE concept_id=? AND query_id=?", (concept["id"], query["id"])).fetchall():
            item = dict(row)
            document = db.execute("SELECT title,source_label,content FROM knowledge_documents WHERE id=?", (item["document_id"],)).fetchone()
            item["stale"] = item["query_fingerprint"] != query_fp or document is None or _document_fingerprint(document) != item["document_fingerprint"]
            all_rows.append(item)
        for hits in (baseline_hits, expanded_hits):
            for hit in hits:
                judgment = judgments.get(hit["document_id"])
                hit["judgment"] = {"rating": judgment["rating"], "stale": False} if judgment else {"rating": next((row["rating"] for row in stale if row["document_id"] == hit["document_id"]), None), "stale": any(row["document_id"] == hit["document_id"] for row in stale)}
        return {"concept_id": concept["id"], "query_id": query["id"], "query": query["query"], "split": query["split"], "corpus_fingerprint": corpus_fingerprint,
                "baseline": {"total": total_baseline, "hits": baseline_hits}, "expanded": {"total": total_expanded, "hits": expanded_hits},
                "metrics": {"baseline": _metrics(baseline_hits, judgments, stale, all_rows), "expanded": _metrics(expanded_hits, judgments, stale, all_rows)},
                "weight_behavior": {"concept_weight": concept_weight, "concept_expression_count": concept_expression_count, "concept_expressions_included": concept_weight > 0, "related_weight": related_weight, "related_terms_total": len(related_terms), "related_terms_included": related_terms_included, "numeric_values_affect_ranking": False},
                "limits": ["Local FTS5 only; no Elasticsearch or embeddings.", "Each baseline or expanded search is limited to 200 unique literal terms; exceeding the limit returns an error instead of dropping terms.", "Expanded terms are literal OR matches; saved weights determine eligibility only and are not numerically reproduced.", "Expanded results exclude documents containing a saved excluded-term token sequence in content, title, or source label; baseline results are unchanged.", "BM25 score is lower-is-better and is not a probability or comparable to Elasticsearch scores.", "One saved query is evaluated; split is context only, with no generalization or automated tuning claim."]}


def judge(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"concept_id", "query_id", "document_id", "rating"}:
        raise KnowledgeError("request must contain only concept_id, query_id, document_id, and rating")
    concept, query = _saved_context({"concept_id": payload.get("concept_id"), "query_id": payload.get("query_id")})
    document_id = _text(payload.get("document_id"), "document_id", 64)
    rating = payload.get("rating")
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or rating < 0 or rating > 3):
        raise KnowledgeError("rating must be an integer from 0 to 3 or null")
    query_fp = concepts._query_judgment_fingerprint(query)
    with concepts._connect_db() as db:
        _schema(db)
        row = db.execute("SELECT id,title,source_label,content FROM knowledge_documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise KnowledgeError("Knowledge document not found", 404)
        doc_fp = _document_fingerprint(row)
        updated = _now()
        db.execute("INSERT INTO knowledge_judgments(concept_id,query_id,document_id,query_fingerprint,document_fingerprint,source_label,rating,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(concept_id,query_id,document_id) DO UPDATE SET query_fingerprint=excluded.query_fingerprint,document_fingerprint=excluded.document_fingerprint,source_label=excluded.source_label,rating=excluded.rating,updated_at=excluded.updated_at", (concept["id"], query["id"], document_id, query_fp, doc_fp, row["source_label"], rating, updated))
    return {"judgment": {"concept_id": concept["id"], "query_id": query["id"], "document_id": document_id, "rating": rating, "stale": False, "updated_at": updated}}
