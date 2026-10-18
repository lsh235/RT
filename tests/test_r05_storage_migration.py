from __future__ import annotations

import json
import sqlite3

import pytest

from es_rag_tuner import chunking, storage


def _connection(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def _r04_fixture(path):
    db = _connection(path)
    # Construct a true R04/v2 database even though the working tree knows v3.
    v3 = storage._MIGRATIONS["state"].pop(3)
    try:
        storage.migrate(db, "state")
    finally:
        storage._MIGRATIONS["state"][3] = v3
    db.execute("INSERT INTO knowledge_documents(id,title,source_label,content,content_bytes,created_at,updated_at,revision) VALUES('doc-a','A','fixture','private body',12,'now','now',7)")
    db.execute("INSERT INTO knowledge_chunks(id,document_id,ordinal,start_offset,end_offset,content) VALUES('chunk-a','doc-a',0,0,12,'private body')")
    db.execute("INSERT INTO knowledge_fts(content,title,source_label,document_id,chunk_id) VALUES('private body','A','fixture','doc-a','chunk-a')")
    db.execute("INSERT INTO knowledge_judgments(concept_id,query_id,document_id,query_fingerprint,document_fingerprint,source_label,rating,updated_at) VALUES('concept-a','query-a','doc-a','qfp','dfp','fixture',3,'now')")
    db.execute("INSERT INTO concepts(id,body,updated_at) VALUES('concept-a','{}','now')")
    db.execute("INSERT INTO judgments(concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at,query_fingerprint) VALUES('concept-a','query-a','idx','external-doc',2,0,'retain','now','qfp')")
    db.commit()
    return db


def test_state_v3_migration_preserves_r04_rows_backfills_revision_and_is_idempotent(tmp_path):
    path = tmp_path / "account.sqlite3"
    db = _r04_fixture(path)
    before = {
        "documents": [tuple(row) for row in db.execute("SELECT id,title,content,revision FROM knowledge_documents")],
        "chunks": [tuple(row) for row in db.execute("SELECT id,document_id,ordinal,start_offset,end_offset,content FROM knowledge_chunks")],
        "fts": [tuple(row) for row in db.execute("SELECT content,title,source_label,document_id,chunk_id FROM knowledge_fts")],
        "knowledge_judgments": [tuple(row) for row in db.execute("SELECT concept_id,query_id,document_id,rating FROM knowledge_judgments")],
        "judgments": [tuple(row) for row in db.execute("SELECT concept_id,query_id,document_id,rating,reason FROM judgments")],
    }

    storage.migrate(db, "state")
    storage.migrate(db, "state")

    assert {row[1] for row in db.execute("PRAGMA table_info(knowledge_chunks)")} >= {"source_revision", "policy_sha256", "token_count"}
    chunk = db.execute("SELECT source_revision,policy_sha256,token_count,content FROM knowledge_chunks WHERE id='chunk-a'").fetchone()
    assert tuple(chunk) == (7, "", None, "private body")  # empty fingerprint marks a legacy/default chunk
    assert db.execute("SELECT id,policy_sha256 FROM knowledge_chunk_policy").fetchone()[0] == 1
    policy_row = db.execute("SELECT policy_json,policy_sha256 FROM knowledge_chunk_policy WHERE id=1").fetchone()
    policy = json.loads(policy_row[0])
    assert policy == {"strategy": "character", "size": 1800, "overlap": 200}
    assert policy_row[1] == chunking.policy_fingerprint(policy)
    assert db.execute("SELECT COUNT(*) FROM knowledge_reindex_jobs").fetchone()[0] == 0
    assert db.execute("SELECT version FROM app_schema_migrations WHERE component='state' ORDER BY version DESC LIMIT 1").fetchone()[0] == 3
    assert [tuple(row) for row in db.execute("SELECT id,title,content,revision FROM knowledge_documents")] == before["documents"]
    assert [tuple(row) for row in db.execute("SELECT id,document_id,ordinal,start_offset,end_offset,content FROM knowledge_chunks")] == before["chunks"]
    assert [tuple(row) for row in db.execute("SELECT content,title,source_label,document_id,chunk_id FROM knowledge_fts")] == before["fts"]
    assert [tuple(row) for row in db.execute("SELECT concept_id,query_id,document_id,rating FROM knowledge_judgments")] == before["knowledge_judgments"]
    assert [tuple(row) for row in db.execute("SELECT concept_id,query_id,document_id,rating,reason FROM judgments")] == before["judgments"]
    db.close()


def test_injected_v3_failure_rolls_back_to_v2_source_and_can_retry(tmp_path, monkeypatch):
    path = tmp_path / "retry.sqlite3"
    db = _r04_fixture(path)
    before_schema = [tuple(row) for row in db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    before_chunk = tuple(db.execute("SELECT id,document_id,ordinal,start_offset,end_offset,content FROM knowledge_chunks").fetchone())
    real_v3 = storage._MIGRATIONS["state"][3]

    def fail_after_ddl(connection):
        real_v3(connection)
        raise RuntimeError("injected migration failure")

    monkeypatch.setitem(storage._MIGRATIONS["state"], 3, fail_after_ddl)
    with pytest.raises(RuntimeError, match="injected"):
        storage.migrate(db, "state")
    assert [tuple(row) for row in db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")] == before_schema
    assert tuple(db.execute("SELECT id,document_id,ordinal,start_offset,end_offset,content FROM knowledge_chunks").fetchone()) == before_chunk
    assert [row[0] for row in db.execute("SELECT version FROM app_schema_migrations WHERE component='state' ORDER BY version")] == [1, 2]

    monkeypatch.setitem(storage._MIGRATIONS["state"], 3, real_v3)
    storage.migrate(db, "state")
    assert db.execute("SELECT source_revision FROM knowledge_chunks WHERE id='chunk-a'").fetchone()[0] == 7
    db.close()
    snapshot = sqlite3.connect(path.with_name(path.name + ".pre-state-v3.bak"))
    assert snapshot.execute("SELECT content FROM knowledge_documents WHERE id='doc-a'").fetchone()[0] == "private body"
    assert snapshot.execute("SELECT content FROM knowledge_chunks WHERE id='chunk-a'").fetchone()[0] == "private body"
    assert snapshot.execute("SELECT version FROM app_schema_migrations WHERE component='state' ORDER BY version DESC LIMIT 1").fetchone()[0] == 2
    snapshot.close()
