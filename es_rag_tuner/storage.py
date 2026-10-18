"""Versioned SQLite schema migrations for local state files.

The control database and each account database have independent migration
ledgers. Migrations run inside a savepoint so a failed DDL or data change can be
rolled back without leaving a partially upgraded file.
"""

from __future__ import annotations

import sqlite3
import os
import tempfile
import threading
import hashlib
from pathlib import Path


class SchemaError(RuntimeError):
    """A local database is malformed or newer than this application supports."""


_STATE_REQUIRED = {
    "concepts": {"id", "body", "updated_at"},
    "concept_versions": {"version_id", "concept_id", "version_number", "body", "fingerprint", "created_at", "is_current"},
    "judgments": {"concept_id", "query_id", "document_index", "document_id", "rating", "pinned", "reason", "updated_at"},
    "runs": {"id", "concept_id", "created_at", "kind", "body"},
    "knowledge_documents": {"id", "title", "source_label", "content", "content_bytes", "created_at", "updated_at"},
    "knowledge_chunks": {"id", "document_id", "ordinal", "start_offset", "end_offset", "content"},
    "knowledge_chunk_policy": {"id", "policy_json", "policy_sha256", "updated_at"},
    "knowledge_reindex_jobs": {"id", "state", "policy_json", "policy_sha256", "created_at", "updated_at", "total_documents", "completed_documents", "failed_documents_json", "source_fingerprint", "target_generation", "safe_error", "cancel_requested"},
    "knowledge_judgments": {"concept_id", "query_id", "document_id", "query_fingerprint", "document_fingerprint", "source_label", "rating", "updated_at"},
    "knowledge_es_state": {"id", "state", "generation", "indexed_chunks", "local_fingerprint", "synced_fingerprint", "last_synced_at", "error"},
    "state_owner": {"singleton", "owner_id"},
}
_CONTROL_REQUIRED = {
    "auth_users": {"id", "username", "display_name", "password_hash", "role", "enabled", "primary_state", "created_at"},
    "auth_sessions": {"session_hash", "user_id", "created_at", "expires_at"},
    "auth_login_attempts": {"username_key", "window_start", "failures", "blocked_until"},
    "auth_migrations": {"name", "owner_id", "completed_at"},
}
_KNOWN_TABLES = set(_STATE_REQUIRED) | set(_CONTROL_REQUIRED) | {
    "app_schema_migrations", "knowledge_fts", "knowledge_fts_data", "knowledge_fts_idx",
    "knowledge_fts_config", "knowledge_fts_docsize", "knowledge_fts_content",
}
_MIGRATION_LOCKS: dict[str, threading.RLock] = {}
_MIGRATION_LOCKS_GUARD = threading.Lock()


def file_lock_for_path(path: str | os.PathLike[str]) -> threading.RLock:
    """Return the process-local lock shared by opens and migrations for a DB file."""
    lock_key = str(Path(path).expanduser().resolve())
    with _MIGRATION_LOCKS_GUARD:
        return _MIGRATION_LOCKS.setdefault(lock_key, threading.RLock())


def _file_lock(db: sqlite3.Connection) -> threading.RLock:
    row = db.execute("PRAGMA database_list").fetchone()
    filename = str(row[2]) if row else ""
    if filename:
        return file_lock_for_path(filename)
    lock_key = f"memory:{id(db)}"
    with _MIGRATION_LOCKS_GUARD:
        return _MIGRATION_LOCKS.setdefault(lock_key, threading.RLock())


def configure_journal_mode(db: sqlite3.Connection, mode: str = "WAL") -> None:
    """Configure the supported local journal mode under the schema setup lock."""
    if mode != "WAL":
        raise ValueError("unsupported journal mode")
    with _file_lock(db):
        db.execute("PRAGMA journal_mode=WAL")


def _tables(db: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    # All callers use these constant table names, never user input.
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}


def _check_known_layout(db: sqlite3.Connection, *, component: str) -> None:
    tables = _tables(db)
    if tables - _KNOWN_TABLES:
        raise SchemaError("Local database contains an unknown schema; migration was not applied")
    required = dict(_STATE_REQUIRED)
    if component == "control":
        required.update(_CONTROL_REQUIRED)
    for table, columns in required.items():
        if table in tables and not columns.issubset(_columns(db, table)):
            raise SchemaError("Local database schema is incomplete; migration was not applied")
    if "knowledge_fts" in tables:
        columns = _columns(db, "knowledge_fts")
        if not {"content", "title", "source_label", "document_id", "chunk_id"}.issubset(columns):
            raise SchemaError("Local search index schema is incomplete; migration was not applied")


def _ensure_ledger(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS app_schema_migrations (component TEXT NOT NULL, version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(component,version))")


def _integrity_check(path: Path) -> None:
    check = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        if [str(row[0]) for row in check.execute("PRAGMA integrity_check")] != ["ok"]:
            raise SchemaError("SQLite recovery snapshot failed integrity validation")
    finally:
        check.close()


def _backup_before_migration(db: sqlite3.Connection, component: str) -> None:
    """Retain one SQLite-consistent, restrictive snapshot before file mutation."""
    names = _tables(db)
    applied: set[int] = set()
    if "app_schema_migrations" in names:
        if not {"component", "version", "applied_at"}.issubset(_columns(db, "app_schema_migrations")):
            raise SchemaError("Local migration ledger is malformed")
        applied = {int(row[0]) for row in db.execute("SELECT version FROM app_schema_migrations WHERE component=?", (component,))}
        if applied == set(_MIGRATIONS[component]):
            return
    pending = next((version for version in sorted(_MIGRATIONS[component]) if version not in applied), None)
    if pending is None:
        return
    row = db.execute("PRAGMA database_list").fetchone()
    filename = str(row[2]) if row else ""
    if not filename:  # In-memory synthetic connection; no filesystem snapshot exists.
        return
    source = Path(filename).absolute()
    backup = source.with_name(source.name + f".pre-{component}-v{pending}.bak")
    if backup.exists():
        _integrity_check(backup)
        try:
            backup.chmod(0o600)
        except OSError as exc:
            raise SchemaError("Existing recovery snapshot permissions could not be secured") from exc
        return
    fd, temp_name = tempfile.mkstemp(prefix=".pre-migration-", suffix=".tmp", dir=source.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        os.close(fd)
        destination = sqlite3.connect(temp, timeout=10)
        try:
            db.backup(destination)
            destination.commit()
        finally:
            destination.close()
        _integrity_check(temp)
        try:
            os.link(temp, backup)
        except FileExistsError:
            _integrity_check(backup)
        backup.chmod(0o600)
    except (OSError, sqlite3.Error) as exc:
        raise SchemaError("A verified pre-migration SQLite snapshot could not be created") from exc
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        temp.unlink(missing_ok=True)


def _state_v1(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS concepts (id TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS concept_versions (version_id TEXT PRIMARY KEY, concept_id TEXT NOT NULL, version_number INTEGER NOT NULL, body TEXT NOT NULL, fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 1, UNIQUE(concept_id, version_number))")
    db.execute("CREATE TABLE IF NOT EXISTS judgments (concept_id TEXT NOT NULL, query_id TEXT NOT NULL, document_index TEXT NOT NULL, document_id TEXT NOT NULL, rating INTEGER, pinned INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, query_fingerprint TEXT NOT NULL DEFAULT '', PRIMARY KEY (concept_id, query_id, document_index, document_id))")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, concept_id TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL)")
    if "query_fingerprint" not in _columns(db, "judgments"):
        db.execute("ALTER TABLE judgments ADD COLUMN query_fingerprint TEXT NOT NULL DEFAULT ''")
    db.execute("CREATE TABLE IF NOT EXISTS knowledge_documents (id TEXT PRIMARY KEY, title TEXT NOT NULL, source_label TEXT NOT NULL, content TEXT NOT NULL, content_bytes INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS knowledge_documents_updated ON knowledge_documents(updated_at DESC, id)")
    db.execute("CREATE TABLE IF NOT EXISTS knowledge_chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, content TEXT NOT NULL, UNIQUE(document_id, ordinal))")
    db.execute("CREATE INDEX IF NOT EXISTS knowledge_chunks_document ON knowledge_chunks(document_id, ordinal)")
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(content, title, source_label, document_id UNINDEXED, chunk_id UNINDEXED, tokenize='unicode61')")
    db.execute("CREATE TABLE IF NOT EXISTS knowledge_judgments (concept_id TEXT NOT NULL, query_id TEXT NOT NULL, document_id TEXT NOT NULL, query_fingerprint TEXT NOT NULL, document_fingerprint TEXT NOT NULL, source_label TEXT NOT NULL, rating INTEGER, updated_at TEXT NOT NULL, PRIMARY KEY(concept_id,query_id,document_id))")
    db.execute("CREATE TABLE IF NOT EXISTS knowledge_es_state (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL DEFAULT 'stale', generation INTEGER NOT NULL DEFAULT 0, indexed_chunks INTEGER NOT NULL DEFAULT 0, local_fingerprint TEXT NOT NULL DEFAULT '', synced_fingerprint TEXT NOT NULL DEFAULT '', last_synced_at TEXT, error TEXT NOT NULL DEFAULT '', vector_state TEXT NOT NULL DEFAULT 'not_indexed', vector_recipe TEXT NOT NULL DEFAULT '', vector_chunks INTEGER NOT NULL DEFAULT 0)")
    columns = _columns(db, "knowledge_es_state")
    for name, definition in (("vector_state", "TEXT NOT NULL DEFAULT 'not_indexed'"), ("vector_recipe", "TEXT NOT NULL DEFAULT ''"), ("vector_chunks", "INTEGER NOT NULL DEFAULT 0")):
        if name not in columns:
            db.execute(f"ALTER TABLE knowledge_es_state ADD COLUMN {name} {definition}")
    db.execute("INSERT OR IGNORE INTO knowledge_es_state(id,state) VALUES(1,'stale')")


def _control_v1(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')), enabled INTEGER NOT NULL DEFAULT 1, primary_state INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_sessions (session_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_login_attempts (username_key TEXT PRIMARY KEY, window_start INTEGER NOT NULL, failures INTEGER NOT NULL, blocked_until INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_migrations (name TEXT PRIMARY KEY, owner_id TEXT NOT NULL, completed_at INTEGER NOT NULL)")


def _state_v2(db: sqlite3.Connection) -> None:
    """Add import provenance and revision metadata without rewriting documents."""
    columns = _columns(db, "knowledge_documents")
    additions = (
        ("source_name", "TEXT NOT NULL DEFAULT ''"),
        ("source_record", "TEXT NOT NULL DEFAULT ''"),
        ("source_sha256", "TEXT NOT NULL DEFAULT ''"),
        ("content_sha256", "TEXT NOT NULL DEFAULT ''"),
        ("revision", "INTEGER NOT NULL DEFAULT 1"),
    )
    for name, definition in additions:
        if name not in columns:
            db.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {definition}")
    for row in db.execute("SELECT id,content FROM knowledge_documents WHERE content_sha256='' ").fetchall():
        digest = hashlib.sha256(str(row[1]).encode("utf-8")).hexdigest()
        db.execute("UPDATE knowledge_documents SET content_sha256=? WHERE id=?", (digest, row[0]))


def _state_v3(db: sqlite3.Connection) -> None:
    """Add chunk policy/reindex state while preserving legacy chunk content."""
    from .chunking import normalize_policy, policy_fingerprint

    columns = _columns(db, "knowledge_chunks")
    for name, definition in (
        ("source_revision", "INTEGER NOT NULL DEFAULT 1"),
        ("policy_sha256", "TEXT NOT NULL DEFAULT ''"),
        ("token_count", "INTEGER"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {definition}")
    db.execute(
        "UPDATE knowledge_chunks SET source_revision=COALESCE((SELECT revision FROM knowledge_documents WHERE knowledge_documents.id=knowledge_chunks.document_id),1)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS knowledge_chunk_policy (id INTEGER PRIMARY KEY CHECK(id=1), policy_json TEXT NOT NULL, policy_sha256 TEXT NOT NULL, updated_at TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS knowledge_reindex_jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, policy_json TEXT NOT NULL, policy_sha256 TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, total_documents INTEGER NOT NULL DEFAULT 0, completed_documents INTEGER NOT NULL DEFAULT 0, failed_documents_json TEXT NOT NULL DEFAULT '[]', source_fingerprint TEXT NOT NULL DEFAULT '', target_generation TEXT NOT NULL DEFAULT '', safe_error TEXT NOT NULL DEFAULT '', cancel_requested INTEGER NOT NULL DEFAULT 0)")
    policy = normalize_policy({"strategy": "character", "size": 1800, "overlap": 200})
    import json
    policy_json = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    db.execute(
        "INSERT OR IGNORE INTO knowledge_chunk_policy(id,policy_json,policy_sha256,updated_at) VALUES(1,?,?,CURRENT_TIMESTAMP)",
        (policy_json, policy_fingerprint(policy)),
    )


def _state_v4(db: sqlite3.Connection) -> None:
    """Persist the selected private vector profile without changing E5 state."""
    import json

    columns = _columns(db, "knowledge_es_state")
    for name, definition in (
        ("vector_profile_id", "TEXT NOT NULL DEFAULT 'e5-multilingual-large'"),
        ("vector_profile_recipe", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE knowledge_es_state ADD COLUMN {name} {definition}")

    # Recognize the pre-registry E5 recipe as the selected E5 profile. Keep its
    # exact historical recipe as the saved profile recipe so the old alias can
    # still be checked without rewriting its mapping or vectors.
    rows = db.execute("SELECT id,vector_recipe FROM knowledge_es_state").fetchall()
    for row in rows:
        recipe_text = str(row[1] or "")
        if not recipe_text:
            continue
        try:
            recipe = json.loads(recipe_text)
        except (TypeError, json.JSONDecodeError):
            continue
        if (isinstance(recipe, dict) and recipe.get("model") == "intfloat/multilingual-e5-large"
                and recipe.get("dimensions") == 1024 and recipe.get("query_prefix") == "query: "
                and recipe.get("passage_prefix") == "passage: "):
            db.execute("UPDATE knowledge_es_state SET vector_profile_id='e5-multilingual-large',vector_profile_recipe=? WHERE id=?", (recipe_text, row[0]))


_MIGRATIONS = {"state": {1: _state_v1, 2: _state_v2, 3: _state_v3, 4: _state_v4}, "control": {1: _control_v1}}


def migrate(db: sqlite3.Connection, component: str) -> None:
    """Apply all known migrations for one file component atomically/idempotently."""
    if component not in _MIGRATIONS:
        raise ValueError("unknown database component")
    with _file_lock(db):
        _migrate_locked(db, component)


def _migrate_locked(db: sqlite3.Connection, component: str) -> None:
    _check_known_layout(db, component=component)
    _backup_before_migration(db, component)
    started_transaction = not db.in_transaction
    if started_transaction:
        db.execute("BEGIN IMMEDIATE")
    db.execute("SAVEPOINT app_schema_migration")
    try:
        _ensure_ledger(db)
        if not {"component", "version", "applied_at"}.issubset(_columns(db, "app_schema_migrations")):
            raise SchemaError("Local migration ledger is malformed")
        ledger_rows = db.execute("SELECT component,version FROM app_schema_migrations").fetchall()
        for ledger_row in ledger_rows:
            existing_component = str(ledger_row[0])
            if existing_component not in _MIGRATIONS:
                raise SchemaError("Local database has an unknown migration component")
            existing_version = int(ledger_row[1])
            if existing_version < 1 or existing_version > max(_MIGRATIONS[existing_component]):
                raise SchemaError("Local database version is newer than this application supports")
        rows = db.execute("SELECT version FROM app_schema_migrations WHERE component=?", (component,)).fetchall()
        applied = {int(row[0]) for row in rows}
        latest = max(_MIGRATIONS[component])
        if any(version < 1 or version > latest for version in applied):
            raise SchemaError("Local database version is newer than this application supports")
        for version, upgrade in sorted(_MIGRATIONS[component].items()):
            if version in applied:
                continue
            upgrade(db)
            db.execute("INSERT INTO app_schema_migrations(component,version) VALUES(?,?)", (component, version))
        db.execute("RELEASE SAVEPOINT app_schema_migration")
        if started_transaction:
            db.commit()
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT app_schema_migration")
        db.execute("RELEASE SAVEPOINT app_schema_migration")
        if started_transaction:
            db.rollback()
        raise


def validate_app_database(path: str | Path) -> None:
    """Validate a versioned or recognized legacy application DB read-only."""
    database_path = Path(path).expanduser().absolute()
    try:
        db = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            _check_known_layout(db, component="control")
            tables = _tables(db)
            app_tables = tables - {"app_schema_migrations"}
            recognized_tables = tables & (set(_STATE_REQUIRED) | set(_CONTROL_REQUIRED) | {"knowledge_fts"})
            if not app_tables or not recognized_tables:
                raise SchemaError("SQLite file does not contain a recognized workbench schema")
            if "app_schema_migrations" in tables:
                if not {"component", "version", "applied_at"}.issubset(_columns(db, "app_schema_migrations")):
                    raise SchemaError("Local migration ledger is malformed")
                rows = db.execute("SELECT component,version FROM app_schema_migrations").fetchall()
                if not rows:
                    raise SchemaError("Local migration ledger is empty")
                for component, version in rows:
                    component = str(component)
                    if component not in _MIGRATIONS or int(version) < 1 or int(version) > max(_MIGRATIONS[component]):
                        raise SchemaError("Local database version is not recognized")
        finally:
            db.close()
    except sqlite3.Error:
        raise SchemaError("SQLite file could not be opened or validated") from None
