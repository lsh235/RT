"""Offline local SQLite backup and restore helpers.

Each SQLite file is handled independently. Use one backup per base/account
database; Elasticsearch indices and remote data are intentionally excluded.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from .storage import SchemaError, validate_app_database


class MaintenanceError(ValueError):
    pass


def _path(value: str | Path) -> Path:
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise MaintenanceError("Symlink paths are not accepted for database maintenance")
    return path


def _integrity_check(path: Path) -> None:
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            result = [str(row[0]) for row in db.execute("PRAGMA integrity_check")]
        finally:
            db.close()
    except sqlite3.Error:
        raise MaintenanceError("SQLite database could not be opened or verified") from None
    if result != ["ok"]:
        raise MaintenanceError("SQLite integrity check failed")


def _snapshot(source: Path, destination: Path) -> None:
    source_db = None
    destination_db = None
    try:
        source_db = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        destination_db = sqlite3.connect(destination, timeout=10)
        source_db.backup(destination_db)
        destination_db.commit()
    except sqlite3.Error:
        raise MaintenanceError("SQLite snapshot could not be completed") from None
    finally:
        if destination_db is not None:
            destination_db.close()
        if source_db is not None:
            source_db.close()


def _atomic_snapshot(source: Path, destination: Path) -> None:
    if source == destination:
        raise MaintenanceError("Source and destination must be different files")
    if not source.is_file():
        raise MaintenanceError("Source SQLite file does not exist")
    if not destination.parent.is_dir():
        raise MaintenanceError("Destination directory must already exist")
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".es-rag-sqlite-", suffix=".tmp", dir=destination.parent)
        temp_path = Path(temp_name)
        os.fchmod(fd, 0o600)
        os.close(fd)
        _snapshot(source, temp_path)
        temp_path.chmod(0o600)
        _integrity_check(temp_path)
        try:
            validate_app_database(temp_path)
        except SchemaError:
            raise MaintenanceError("SQLite snapshot does not contain a recognized workbench schema") from None
        os.replace(temp_path, destination)
        destination.chmod(0o600)
    except OSError:
        raise MaintenanceError("SQLite file could not be installed at the requested path") from None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def backup_database(source: str | Path, destination: str | Path) -> Path:
    """Create and verify an atomic, restrictive-mode snapshot of one DB file."""
    source_path, destination_path = _path(source), _path(destination)
    try:
        validate_app_database(source_path)
    except SchemaError:
        raise MaintenanceError("Backup does not contain a recognized workbench schema") from None
    _integrity_check(source_path)
    _atomic_snapshot(source_path, destination_path)
    return destination_path


def restore_database(source: str | Path, destination: str | Path, *, offline_confirmed: bool) -> Path:
    """Restore one verified snapshot; caller must confirm the app is stopped."""
    if offline_confirmed is not True:
        raise MaintenanceError("Restore requires explicit confirmation that the workbench is stopped")
    source_path, destination_path = _path(source), _path(destination)
    if not source_path.is_file():
        raise MaintenanceError("Backup SQLite file does not exist")
    if destination_path.with_name(destination_path.name + "-wal").exists() or destination_path.with_name(destination_path.name + "-shm").exists():
        raise MaintenanceError("Restore destination has SQLite sidecars; stop the workbench and retry")
    try:
        validate_app_database(source_path)
    except SchemaError:
        raise MaintenanceError("Backup does not contain a recognized workbench schema") from None
    _integrity_check(source_path)
    _atomic_snapshot(source_path, destination_path)
    return destination_path
