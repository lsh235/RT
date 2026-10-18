from __future__ import annotations

import sqlite3

import pytest

from es_rag_tuner import db_maintenance, storage
from es_rag_tuner.es_client import ElasticsearchError
from es_rag_tuner.server import _error_code, _public_token_preview_result, _safe_domain_message, _sample_bulk_failures
from es_rag_tuner.concepts import _public_failure_message


def _legacy_state(path):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE concepts (id TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE concept_versions (version_id TEXT PRIMARY KEY, concept_id TEXT NOT NULL, version_number INTEGER NOT NULL, body TEXT NOT NULL, fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 1, UNIQUE(concept_id, version_number));
        CREATE TABLE judgments (concept_id TEXT NOT NULL, query_id TEXT NOT NULL, document_index TEXT NOT NULL, document_id TEXT NOT NULL, rating INTEGER, pinned INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY (concept_id, query_id, document_index, document_id));
        CREATE TABLE runs (id TEXT PRIMARY KEY, concept_id TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE knowledge_es_state (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL DEFAULT 'stale', generation INTEGER NOT NULL DEFAULT 0, indexed_chunks INTEGER NOT NULL DEFAULT 0, local_fingerprint TEXT NOT NULL DEFAULT '', synced_fingerprint TEXT NOT NULL DEFAULT '', last_synced_at TEXT, error TEXT NOT NULL DEFAULT '');
        INSERT INTO concepts VALUES ('c1','{"queries":[{"id":"q1"}]}','2026-10-01');
        INSERT INTO judgments VALUES ('c1','q1','idx','doc1',2,0,'keep','2026-10-01');
        INSERT INTO knowledge_es_state(id,state,generation,indexed_chunks,local_fingerprint,synced_fingerprint,error) VALUES (1,'synced',7,4,'local-fp','remote-fp','');
        """
    )
    db.commit()
    db.close()


def _connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def test_legacy_state_migration_is_transactional_idempotent_and_preserves_rows(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_state(path)
    db = _connect(path)
    storage.migrate(db, "state")
    storage.migrate(db, "state")
    snapshot = path.with_name(path.name + ".pre-state-v1.bak")
    assert snapshot.is_file()
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert db.execute("SELECT body FROM concepts WHERE id='c1'").fetchone()[0] == '{"queries":[{"id":"q1"}]}'
    judgment = db.execute("SELECT rating,reason,query_fingerprint FROM judgments WHERE document_id='doc1'").fetchone()
    assert tuple(judgment) == (2, "keep", "")
    state = db.execute("SELECT state,generation,indexed_chunks,local_fingerprint,synced_fingerprint FROM knowledge_es_state WHERE id=1").fetchone()
    assert tuple(state) == ("synced", 7, 4, "local-fp", "remote-fp")
    assert [tuple(row) for row in db.execute("SELECT version FROM app_schema_migrations WHERE component='state' ORDER BY version")] == [(1,), (2,)]
    assert {row[1] for row in db.execute("PRAGMA table_info(knowledge_es_state)")} >= {"vector_state", "vector_recipe", "vector_chunks"}
    db.close()


def test_migration_failure_rolls_back_ddl_and_ledger(tmp_path):
    path = tmp_path / "interrupted.sqlite3"
    db = _connect(path)
    db.execute("CREATE TABLE app_schema_migrations (component TEXT NOT NULL, version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(component,version))")
    db.execute("CREATE TRIGGER fail_state_ledger BEFORE INSERT ON app_schema_migrations WHEN NEW.component='state' BEGIN SELECT RAISE(ABORT,'injected'); END")
    db.commit()
    before_schema = [tuple(row) for row in db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    before_rows = [tuple(row) for row in db.execute("SELECT component,version FROM app_schema_migrations")]
    with pytest.raises(sqlite3.IntegrityError):
        storage.migrate(db, "state")
    assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='concepts'").fetchone() is None
    assert db.execute("SELECT count(*) FROM app_schema_migrations").fetchone()[0] == 0
    assert [tuple(row) for row in db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")] == before_schema
    assert [tuple(row) for row in db.execute("SELECT component,version FROM app_schema_migrations")] == before_rows
    db.close()
    snapshot = sqlite3.connect(path.with_name(path.name + ".pre-state-v1.bak"))
    assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert [tuple(row) for row in snapshot.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")] == before_schema
    snapshot.close()


def test_future_schema_version_fails_closed(tmp_path):
    path = tmp_path / "future.sqlite3"
    db = _connect(path)
    db.execute("CREATE TABLE app_schema_migrations (component TEXT NOT NULL, version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(component,version))")
    db.execute("INSERT INTO app_schema_migrations(component,version) VALUES('state',99)")
    db.commit()
    with pytest.raises(storage.SchemaError, match="newer"):
        storage.migrate(db, "state")
    db.close()


def test_malformed_legacy_layout_fails_before_mutation(tmp_path):
    path = tmp_path / "malformed.sqlite3"
    db = _connect(path)
    db.execute("CREATE TABLE concepts (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
    db.commit()
    with pytest.raises(storage.SchemaError, match="incomplete"):
        storage.migrate(db, "state")
    assert db.execute("SELECT name FROM sqlite_master WHERE name='app_schema_migrations'").fetchone() is None
    db.close()


def test_backup_and_restore_use_verified_private_snapshots(tmp_path):
    base = tmp_path / "base.sqlite3"
    secondary = tmp_path / "accounts" / "user-2.sqlite3"
    secondary.parent.mkdir()
    base_db = sqlite3.connect(base)
    storage.migrate(base_db, "control")
    storage.migrate(base_db, "state")
    base_db.execute("INSERT INTO auth_users VALUES('user-1','admin','Admin','hash','admin',1,1,1)")
    base_db.execute("INSERT INTO auth_migrations VALUES('legacy_state_claim','user-1',1)")
    base_db.execute("INSERT INTO concepts VALUES('c1','{}','now')")
    base_db.execute("INSERT INTO concept_versions VALUES('v1','c1',1,'{}','fp','now',1)")
    base_db.execute("INSERT INTO judgments(concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at,query_fingerprint) VALUES('c1','q1','idx','d1',2,0,'keep','now','qfp')")
    base_db.execute("INSERT INTO runs VALUES('r1','c1','now','eval','{}')")
    base_db.execute("INSERT INTO knowledge_documents(id,title,source_label,content,content_bytes,created_at,updated_at) VALUES('doc1','Title','Source','private body',12,'now','now')")
    base_db.execute("INSERT INTO knowledge_chunks VALUES('chunk1','doc1',0,0,12,'private body')")
    base_db.execute("INSERT INTO knowledge_fts(content,title,source_label,document_id,chunk_id) VALUES('private body','Title','Source','doc1','chunk1')")
    base_db.execute("INSERT INTO knowledge_judgments VALUES('c1','q1','doc1','qfp','dfp','Source',3,'now')")
    base_db.execute("UPDATE knowledge_es_state SET state='synced',generation=4,indexed_chunks=1,local_fingerprint='local',synced_fingerprint='remote',vector_state='indexed',vector_recipe='recipe',vector_chunks=1 WHERE id=1")
    base_db.commit()
    base_db.close()

    secondary_db = sqlite3.connect(secondary)
    storage.migrate(secondary_db, "state")
    secondary_db.execute("CREATE TABLE state_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner_id TEXT NOT NULL)")
    secondary_db.execute("INSERT INTO state_owner(singleton,owner_id) VALUES(1,'user-2')")
    secondary_db.execute("INSERT INTO concepts VALUES('c2','{" + '"private":"secondary"' + "}','now')")
    secondary_db.commit()
    secondary_db.close()

    for source in (base, secondary):
        db = sqlite3.connect(source)
        db.execute("PRAGMA journal_mode=WAL")
        db.commit()
        db.close()
    backup_base, backup_secondary = tmp_path / "base-backup.sqlite3", tmp_path / "secondary-backup.sqlite3"
    restored_base, restored_secondary = tmp_path / "base-restored.sqlite3", tmp_path / "secondary-restored.sqlite3"
    db_maintenance.backup_database(base, backup_base)
    db_maintenance.backup_database(secondary, backup_secondary)
    assert backup_base.stat().st_mode & 0o777 == 0o600
    with pytest.raises(db_maintenance.MaintenanceError, match="confirmation"):
        db_maintenance.restore_database(backup_base, restored_base, offline_confirmed=False)
    db_maintenance.restore_database(backup_base, restored_base, offline_confirmed=True)
    db_maintenance.restore_database(backup_secondary, restored_secondary, offline_confirmed=True)
    check = sqlite3.connect(restored_base)
    for query, expected in (
        ("SELECT owner_id FROM auth_migrations WHERE name='legacy_state_claim'", ("user-1",)),
        ("SELECT body FROM concepts WHERE id='c1'", ("{}",)),
        ("SELECT body FROM concept_versions WHERE version_id='v1'", ("{}",)),
        ("SELECT rating FROM judgments WHERE document_id='d1'", (2,)),
        ("SELECT body FROM runs WHERE id='r1'", ("{}",)),
        ("SELECT content FROM knowledge_documents WHERE id='doc1'", ("private body",)),
        ("SELECT content FROM knowledge_chunks WHERE id='chunk1'", ("private body",)),
        ("SELECT content FROM knowledge_fts WHERE chunk_id='chunk1'", ("private body",)),
        ("SELECT rating FROM knowledge_judgments WHERE document_id='doc1'", (3,)),
        ("SELECT generation,vector_recipe FROM knowledge_es_state WHERE id=1", (4, "recipe")),
    ):
        assert check.execute(query).fetchone() == expected
    assert check.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    check.close()
    secondary_check = sqlite3.connect(restored_secondary)
    assert secondary_check.execute("SELECT owner_id FROM state_owner").fetchone() == ("user-2",)
    assert secondary_check.execute("SELECT body FROM concepts WHERE id='c2'").fetchone() == ('{"private":"secondary"}',)
    secondary_check.close()
    assert restored_base.stat().st_mode & 0o777 == 0o600


def test_generic_sqlite_database_is_not_accepted_as_workbench_backup(tmp_path):
    source = tmp_path / "unrelated.sqlite3"
    db = sqlite3.connect(source)
    db.execute("CREATE TABLE private_rows (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
    db.execute("INSERT INTO private_rows VALUES('r1','retained')")
    db.commit()
    db.close()
    with pytest.raises(db_maintenance.MaintenanceError, match="recognized workbench"):
        db_maintenance.backup_database(source, tmp_path / "backup.sqlite3")


def test_remote_elasticsearch_error_body_is_not_returned_to_api():
    private_marker = "PRIVATE_DOCUMENT_BODY_7fd3"
    remote_error = ElasticsearchError(private_marker, 400, safe_for_user=False)
    response = {"error": _safe_domain_message(remote_error), "code": _error_code(remote_error.status or 400, "RETRIEVAL")}
    assert response["code"] == "INVALID_REQUEST"
    assert private_marker not in response["error"]
    wrapped = _public_failure_message(remote_error, "The retrieval failed.")
    assert wrapped == "The retrieval failed."


def test_partial_bulk_response_does_not_echo_remote_private_error():
    private_marker = "PRIVATE_DOCUMENT_BODY_9c22"
    failures = _sample_bulk_failures([{"index": {"_id": "sample-1", "status": 400, "error": {"reason": private_marker}}}])
    assert failures == [{"id": "sample-1", "status": 400, "code": "REMOTE_ITEM_REJECTED", "error": "문서 적재를 완료하지 못했습니다."}]
    assert private_marker not in str(failures)


def test_token_preview_status_does_not_expose_local_paths_or_exception_details():
    response = _public_token_preview_result({"available": False, "cache_path": "/home/private/cache", "reason": "cannot open /home/private/tokenizer.json"})
    assert "cache_path" not in response
    assert "/home/private" not in str(response)


def test_restore_refuses_sidecars_and_corrupt_backup(tmp_path):
    source = tmp_path / "backup.sqlite3"
    destination = tmp_path / "live.sqlite3"
    db = sqlite3.connect(source)
    storage.migrate(db, "control")
    db.close()
    destination.write_bytes(b"old target")
    (tmp_path / "live.sqlite3-wal").touch()
    with pytest.raises(db_maintenance.MaintenanceError, match="sidecars"):
        db_maintenance.restore_database(source, destination, offline_confirmed=True)
    (tmp_path / "live.sqlite3-wal").unlink()
    source.write_bytes(b"not sqlite")
    with pytest.raises(db_maintenance.MaintenanceError, match="recognized"):
        db_maintenance.restore_database(source, destination, offline_confirmed=True)
    assert destination.read_bytes() == b"old target"


def test_restore_rejects_symlink_destination_without_mutating_link_or_target(tmp_path):
    source = tmp_path / "backup.sqlite3"
    db = sqlite3.connect(source)
    storage.migrate(db, "control")
    db.close()

    target = tmp_path / "protected-target.sqlite3"
    original_target = b"keep these target bytes"
    target.write_bytes(original_target)
    destination = tmp_path / "restore-link.sqlite3"
    destination.symlink_to(target)

    with pytest.raises(db_maintenance.MaintenanceError, match="Symlink paths"):
        db_maintenance.restore_database(source, destination, offline_confirmed=True)

    assert destination.is_symlink()
    assert destination.resolve() == target
    assert target.read_bytes() == original_target


def test_restore_replace_failure_keeps_existing_destination(tmp_path, monkeypatch):
    source = tmp_path / "backup.sqlite3"
    destination = tmp_path / "destination.sqlite3"
    db = sqlite3.connect(source)
    storage.migrate(db, "control")
    db.close()
    destination.write_bytes(b"existing target")

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(db_maintenance.os, "replace", fail_replace)
    with pytest.raises(db_maintenance.MaintenanceError, match="installed"):
        db_maintenance.restore_database(source, destination, offline_confirmed=True)
    assert destination.read_bytes() == b"existing target"
    assert not list(tmp_path.glob(".es-rag-sqlite-*.tmp"))
