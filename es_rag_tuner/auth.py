"""Local account authentication and opaque server-side sessions."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher, Type
from argon2.exceptions import (  # type: ignore[import-not-found]
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

SESSION_TTL_SECONDS = 12 * 60 * 60
COOKIE_NAME = "es_rag_session"
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1, type=Type.ID)
# One process-local dummy hash keeps unknown-user and wrong-password paths at
# the same Argon2id verification cost without hashing on each login attempt.
_DUMMY_PASSWORD_HASH = _hasher.hash("dummy-password-for-timing")
_csrf_key = secrets.token_bytes(32)


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def database_path() -> Path:
    configured = os.environ.get("ES_RAG_CONCEPT_DB", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / ".local/share/es-rag-workbench/concepts.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    path = database_path()
    db = sqlite3.connect(path, timeout=10, isolation_level="DEFERRED")
    try:
        path.chmod(0o600)
    except OSError:
        db.close()
        raise
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    _schema(db)
    return db


@contextmanager
def _db():
    db = _connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _schema(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')), enabled INTEGER NOT NULL DEFAULT 1, primary_state INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_sessions (session_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_login_attempts (username_key TEXT PRIMARY KEY, window_start INTEGER NOT NULL, failures INTEGER NOT NULL, blocked_until INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS auth_migrations (name TEXT PRIMARY KEY, owner_id TEXT NOT NULL, completed_at INTEGER NOT NULL)")
    db.commit()


def _prepare_legacy_state_claim(db: sqlite3.Connection) -> None:
    expected = {
        "concepts": {"id", "body", "updated_at"},
        "concept_versions": {"version_id", "concept_id", "version_number", "body", "fingerprint", "created_at", "is_current"},
        "judgments": {"concept_id", "query_id", "document_index", "document_id", "rating", "pinned", "reason", "updated_at"},
        "runs": {"id", "concept_id", "created_at", "kind", "body"},
    }
    existing = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, required in expected.items():
        if table not in existing:
            continue
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if not required.issubset(columns):
            raise AuthError(f"Legacy {table} schema is incomplete; refusing to claim saved state", 409)
        if table == "judgments" and "query_fingerprint" not in columns:
            db.execute("ALTER TABLE judgments ADD COLUMN query_fingerprint TEXT NOT NULL DEFAULT ''")


def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"], "role": row["role"]}


def is_configured() -> bool:
    with _db() as db:
        return db.execute("SELECT 1 FROM auth_users WHERE enabled=1 LIMIT 1").fetchone() is not None


def bootstrap_admin(username: str, display_name: str, password: str) -> dict[str, Any]:
    """Create the first admin, assigning the existing state DB to that account."""
    if not isinstance(username, str) or not isinstance(display_name, str):
        raise AuthError("username and display_name must be strings")
    username = username.strip().lower()
    display_name = display_name.strip()
    if not (3 <= len(username) <= 64) or not all(ch.isalnum() or ch in "._-@" for ch in username):
        raise AuthError("username must be 3 to 64 letters, digits, or . _ - @ characters")
    if not display_name or len(display_name) > 100:
        raise AuthError("display_name must be 1 to 100 characters")
    if not isinstance(password, str) or len(password) < 15 or len(password) > 1024:
        raise AuthError("password must be 15 to 1024 characters")
    password_hash = _hasher.hash(password)
    user_id = str(uuid.uuid4())
    with _db() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone():
                raise AuthError("Initial administrator is already configured", 409)
            if db.execute("SELECT 1 FROM auth_migrations WHERE name='legacy_state_claim' LIMIT 1").fetchone():
                raise AuthError("Legacy state claim is already recorded but no administrator exists; refusing to continue", 409)
            _prepare_legacy_state_claim(db)
            # The bootstrap admin claims all legacy rows by owning the existing DB file.
            db.execute("INSERT INTO auth_users(id,username,display_name,password_hash,role,enabled,primary_state,created_at) VALUES(?,?,?,?, 'admin',1,1,?)", (user_id, username, display_name, password_hash, int(time.time())))
            db.execute("INSERT INTO auth_migrations(name,owner_id,completed_at) VALUES('legacy_state_claim',?,?)", (user_id, int(time.time())))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"id": user_id, "username": username, "display_name": display_name, "role": "admin"}


def create_account(username: str, display_name: str, password: str) -> dict[str, Any]:
    if not isinstance(username, str) or not isinstance(display_name, str):
        raise AuthError("username and display_name must be strings")
    username = username.strip().lower()
    display_name = display_name.strip()
    if not (3 <= len(username) <= 64) or not all(ch.isalnum() or ch in "._-@" for ch in username):
        raise AuthError("username must be 3 to 64 letters, digits, or . _ - @ characters")
    if not display_name or len(display_name) > 100:
        raise AuthError("display_name must be 1 to 100 characters")
    if not isinstance(password, str) or len(password) < 15 or len(password) > 1024:
        raise AuthError("password must be 15 to 1024 characters")
    user_id = str(uuid.uuid4())
    with _db() as db:
        try:
            db.execute("INSERT INTO auth_users(id,username,display_name,password_hash,role,enabled,primary_state,created_at) VALUES(?,?,?,?, 'user',1,0,?)", (user_id, username, display_name, _hasher.hash(password), int(time.time())))
        except sqlite3.IntegrityError:
            raise AuthError("An account with that username already exists", 409) from None
    return {"id": user_id, "username": username, "display_name": display_name, "role": "user"}


def list_accounts() -> list[dict[str, Any]]:
    with _db() as db:
        rows = db.execute("SELECT id,username,display_name,role,enabled,created_at FROM auth_users ORDER BY username").fetchall()
    return [{**{key: row[key] for key in ("id", "username", "display_name", "role", "created_at")}, "enabled": bool(row["enabled"])} for row in rows]


def update_account(user_id: str, display_name: str) -> dict[str, Any]:
    if not isinstance(user_id, str) or not isinstance(display_name, str):
        raise AuthError("user_id and display_name must be strings")
    display_name = display_name.strip()
    if not display_name or len(display_name) > 100:
        raise AuthError("display_name must be 1 to 100 characters")
    with _db() as db:
        changed = db.execute("UPDATE auth_users SET display_name=? WHERE id=?", (display_name, str(user_id))).rowcount
        row = db.execute("SELECT id,username,display_name,role FROM auth_users WHERE id=?", (str(user_id),)).fetchone()
    if not changed or not row:
        raise AuthError("Account not found", 404)
    return _public_user(row)


def disable_account(user_id: str) -> None:
    if not isinstance(user_id, str):
        raise AuthError("user_id must be a string")
    with _db() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT role,enabled FROM auth_users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise AuthError("Account not found", 404)
            if row["enabled"] and row["role"] == "admin" and db.execute("SELECT COUNT(*) FROM auth_users WHERE role='admin' AND enabled=1").fetchone()[0] <= 1:
                raise AuthError("The last enabled administrator cannot be disabled", 409)
            db.execute("UPDATE auth_users SET enabled=0 WHERE id=?", (user_id,))
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
            db.commit()
        except Exception:
            db.rollback()
            raise


def _username_key(username: str) -> str:
    return hashlib.sha256(str(username).strip().lower().encode("utf-8")).hexdigest()


def _failed_login(db: sqlite3.Connection, key: str, now: int) -> None:
    row = db.execute("SELECT window_start,failures FROM auth_login_attempts WHERE username_key=?", (key,)).fetchone()
    window, failures = (row["window_start"], row["failures"]) if row else (now, 0)
    if now - window >= 900:
        window, failures = now, 0
    failures += 1
    delay = min(300, 2 ** min(9, max(0, failures - 5))) if failures >= 5 else 0
    db.execute("INSERT INTO auth_login_attempts(username_key,window_start,failures,blocked_until) VALUES(?,?,?,?) ON CONFLICT(username_key) DO UPDATE SET window_start=excluded.window_start,failures=excluded.failures,blocked_until=excluded.blocked_until", (key, window, failures, now + delay))


def login(username: str, password: str) -> tuple[dict[str, Any], str, str]:
    if not isinstance(username, str) or not isinstance(password, str):
        raise AuthError("Invalid username or password", 401)
    username = username.strip().lower()
    key, now = _username_key(username), int(time.time())
    failed = False
    session_id = ""
    with _db() as db:
        attempt = db.execute("SELECT blocked_until FROM auth_login_attempts WHERE username_key=?", (key,)).fetchone()
        row = db.execute("SELECT * FROM auth_users WHERE username=? AND enabled=1", (username,)).fetchone()
        candidate = row["password_hash"] if row else _DUMMY_PASSWORD_HASH
        blocked = attempt is not None and int(attempt["blocked_until"]) > now
        valid = False
        if not blocked:
            length_ok = len(password) <= 1024
            try:
                valid = _hasher.verify(candidate, password if length_ok else "") and length_ok
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                valid = False
        if blocked or not valid or not row:
            if not blocked:
                _failed_login(db, key, now)
            failed = True
        else:
            if _hasher.check_needs_rehash(candidate):
                db.execute("UPDATE auth_users SET password_hash=? WHERE id=?", (_hasher.hash(password), row["id"]))
            db.execute("DELETE FROM auth_login_attempts WHERE username_key=?", (key,))
            session_id = secrets.token_urlsafe(32)
            db.execute("INSERT INTO auth_sessions(session_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)", (hashlib.sha256(session_id.encode()).hexdigest(), row["id"], now, now + SESSION_TTL_SECONDS))
    if failed:
        raise AuthError("Invalid username or password", 401)
    csrf = csrf_token(session_id)
    return _public_user(row), session_id, csrf


def csrf_token(session_id: str) -> str:
    return hmac.new(_csrf_key, session_id.encode("utf-8"), hashlib.sha256).hexdigest()


def login_nonce_token(nonce: str) -> str:
    return hmac.new(_csrf_key, ("login:" + nonce).encode("utf-8"), hashlib.sha256).hexdigest()


def verify_login_csrf(nonce: str | None, supplied: str | None) -> bool:
    if not nonce or not supplied:
        return False
    return hmac.compare_digest(login_nonce_token(nonce), str(supplied))


def authenticate(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    digest, now = hashlib.sha256(session_id.encode("utf-8")).hexdigest(), int(time.time())
    with _db() as db:
        row = db.execute("SELECT u.id,u.username,u.display_name,u.role FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.session_hash=? AND s.expires_at>? AND u.enabled=1", (digest, now)).fetchone()
        if not row:
            db.execute("DELETE FROM auth_sessions WHERE session_hash=? OR expires_at<=?", (digest, now))
            return None
    return _public_user(row)


def verify_csrf(session_id: str | None, supplied: str | None) -> bool:
    if not session_id or not supplied:
        return False
    expected = csrf_token(session_id)
    return hmac.compare_digest(expected, str(supplied))


def logout(session_id: str | None) -> None:
    if not session_id:
        return
    with _db() as db:
        db.execute("DELETE FROM auth_sessions WHERE session_hash=?", (hashlib.sha256(session_id.encode()).hexdigest(),))


def change_password(user_id: str, current_password: str, new_password: str) -> None:
    if not all(isinstance(value, str) for value in (user_id, current_password, new_password)):
        raise AuthError("user_id and password fields must be strings")
    if not isinstance(new_password, str) or len(new_password) < 15 or len(new_password) > 1024:
        raise AuthError("password must be 15 to 1024 characters")
    with _db() as db:
        row = db.execute("SELECT password_hash FROM auth_users WHERE id=? AND enabled=1", (str(user_id),)).fetchone()
        if not row:
            raise AuthError("Current password is incorrect", 401)
        try:
            valid = _hasher.verify(row["password_hash"], str(current_password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise AuthError("Current password is incorrect", 401)
        db.execute("UPDATE auth_users SET password_hash=? WHERE id=?", (_hasher.hash(new_password), str(user_id)))
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (str(user_id),))


def admin_reset_password(actor_id: str, user_id: str, new_password: str) -> None:
    if not all(isinstance(value, str) for value in (actor_id, user_id, new_password)):
        raise AuthError("user_id and password fields must be strings")
    if str(actor_id) == str(user_id):
        raise AuthError("Use the password change flow to change your own password", 400)
    if not isinstance(new_password, str) or len(new_password) < 15 or len(new_password) > 1024:
        raise AuthError("password must be 15 to 1024 characters")
    with _db() as db:
        changed = db.execute("UPDATE auth_users SET password_hash=? WHERE id=? AND enabled=1", (_hasher.hash(new_password), str(user_id))).rowcount
        if not changed:
            raise AuthError("Account not found or not enabled", 404)
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (str(user_id),))


def reset_admin_password(username: str, new_password: str) -> None:
    if not isinstance(username, str) or not isinstance(new_password, str):
        raise AuthError("username and password must be strings")
    username = username.strip().lower()
    if not isinstance(new_password, str) or len(new_password) < 15 or len(new_password) > 1024:
        raise AuthError("password must be 15 to 1024 characters")
    with _db() as db:
        row = db.execute("SELECT id FROM auth_users WHERE username=? AND role='admin' AND enabled=1", (username,)).fetchone()
        if not row:
            raise AuthError("Enabled administrator account not found", 404)
        db.execute("UPDATE auth_users SET password_hash=? WHERE id=?", (_hasher.hash(new_password), row["id"]))
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (row["id"],))


def state_database_path(user_id: str) -> Path:
    """Resolve state by authenticated DB identity, never by request payload."""
    try:
        canonical_id = str(uuid.UUID(str(user_id)))
    except (ValueError, AttributeError, TypeError):
        raise AuthError("Account identity is invalid", 503) from None
    with _db() as db:
        row = db.execute("SELECT primary_state,enabled FROM auth_users WHERE id=?", (canonical_id,)).fetchone()
        claim = db.execute("SELECT owner_id FROM auth_migrations WHERE name='legacy_state_claim'").fetchone() if row and row["primary_state"] else None
    if not row or not row["enabled"]:
        raise AuthError("Account is not active", 401)
    base = database_path()
    if row["primary_state"]:
        if not claim or not hmac.compare_digest(str(claim["owner_id"]), canonical_id):
            raise AuthError("Legacy state ownership marker is inconsistent", 503)
        return base
    path = base.parent / (base.name + ".accounts") / (canonical_id + ".sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
