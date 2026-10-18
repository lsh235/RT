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


_MIGRATIONS = {"state": {1: _state_v1}, "control": {1: _control_v1}}


def migrate(db: sqlite3.Connection, component: str) -> None:
    """Apply all known migrations for one file component atomically/idempotently."""
    if component not in _MIGRATIONS:
        raise ValueError("unknown database component")
    row = db.execute("PRAGMA database_list").fetchone()
    filename = str(row[2]) if row else ""
    lock_key = str(Path(filename).absolute()) if filename else f"memory:{id(db)}"
    with _MIGRATION_LOCKS_GUARD:
        lock = _MIGRATION_LOCKS.setdefault(lock_key, threading.RLock())
    with lock:
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
