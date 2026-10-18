from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import threading
import uuid

import pytest

from es_rag_tuner import auth, concepts, knowledge, storage


PASSWORD = "R04-temporary-fixture-password-001!"


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("ES_RAG_CONCEPT_DB", str(tmp_path / "control.sqlite3"))
    primary = auth.bootstrap_admin("r04-admin-" + uuid.uuid4().hex[:8], "R04 Admin", PASSWORD)
    secondary = auth.create_account("r04-user-" + uuid.uuid4().hex[:8], "R04 User", PASSWORD)
    return primary, secondary


def _payload(filename: str, content: bytes, fields: dict | None = None, **extra):
    return {"filename": filename, "content_base64": base64.b64encode(content).decode("ascii"), "fields": fields or {}, **extra}


def _docs(owner):
    with concepts.owner_scope(owner):
        return knowledge.list_documents()["documents"]


def test_csv_field_discovery_partial_rows_provenance_and_private_stale_state(accounts):
    primary, _secondary = accounts
    content = b"Title,Body,Ref\nFirst,alpha body,manual\nMissing,,manual\nThird,gamma body,guide\n"
    unmapped = _payload("notes.csv", content)
    with concepts.owner_scope(primary["id"]):
        mapping_preview = knowledge.import_preview(unmapped)
        assert mapping_preview["fields_available"] == ["Title", "Body", "Ref"]
        assert mapping_preview["needs_field_mapping"] is True
        assert mapping_preview["valid_records"] == []
        assert mapping_preview["errors"] == []
        with pytest.raises(knowledge.KnowledgeError, match="field mappings"):
            knowledge.import_commit(unmapped)

        mapped = _payload("notes.csv", content, {"title": "Title", "content": "Body", "source": "Ref"})
        preview = knowledge.import_preview(mapped)
        assert preview["needs_field_mapping"] is False
        assert [row["row_number"] for row in preview["valid_records"]] == [2, 4]
        assert [error["row_number"] for error in preview["errors"]] == [3]
        assert preview["valid_records"][0]["content_sha256"] == hashlib.sha256(b"alpha body").hexdigest()
        result = knowledge.import_commit(mapped)
        assert [row["outcome"] for row in result["outcomes"]] == ["created", "created"]
        assert result["partial"] is True
        assert result["usage"]["documents"] == 2
        assert result["private_es_state"]["state"] == "stale"
        db_path = auth.state_database_path(primary["id"])
        db = sqlite3.connect(db_path)
        rows = db.execute("SELECT id,source_name,source_record,source_sha256,content_sha256,revision FROM knowledge_documents ORDER BY source_record").fetchall()
        db.close()
        assert [row[1:] for row in rows] == [
            ("notes.csv", "2", hashlib.sha256(content).hexdigest(), hashlib.sha256(b"alpha body").hexdigest(), 1),
            ("notes.csv", "4", hashlib.sha256(content).hexdigest(), hashlib.sha256(b"gamma body").hexdigest(), 1),
        ]


def test_strict_utf8_and_file_size_rejection_preserve_prior_data(accounts):
    primary, _secondary = accounts
    with concepts.owner_scope(primary["id"]):
        knowledge.save_document({"title": "Keep", "content": "existing content"})
        before = _docs(primary["id"])
        for bad in (b"\xff\xfe", b"x" * (knowledge.MAX_DOCUMENT_BYTES + 1)):
            with pytest.raises(knowledge.KnowledgeError):
                knowledge.import_preview(_payload("bad.txt", bad))
        assert _docs(primary["id"]) == before


def test_duplicate_actions_skip_replace_revision_and_deterministic_retry(accounts):
    primary, _secondary = accounts
    initial = _payload("records.jsonl", b'{"name":"One","body":"first text"}\n', {"title": "name", "content": "body"})
    with concepts.owner_scope(primary["id"]):
        created = knowledge.import_commit(initial)
        document_id = created["outcomes"][0]["document_id"]
        same_preview = knowledge.import_preview(initial)
        assert same_preview["valid_records"][0]["duplicate"] == {"document_id": document_id, "revision": 1}
        with pytest.raises(knowledge.KnowledgeError, match="explicit"):
            knowledge.import_commit(initial)
        skipped = knowledge.import_commit({**initial, "duplicate_actions": [{"row_number": 1, "action": "skip"}]})
        assert skipped["outcomes"][0]["outcome"] == "skipped"

        changed = _payload("records.jsonl", b'{"name":"One","body":"revised text"}\n', {"title": "name", "content": "body"})
        duplicate = knowledge.import_preview(changed)["valid_records"][0]["duplicate"]
        assert duplicate["document_id"] == document_id
        replaced = knowledge.import_commit({**changed, "duplicate_actions": [{"row_number": 1, "action": "replace"}]})
        assert replaced["outcomes"][0]["outcome"] == "replaced"
        assert replaced["outcomes"][0]["revision"] == 2
        retried = knowledge.import_commit({**changed, "duplicate_actions": [{"row_number": 1, "action": "replace"}]})
        assert retried["outcomes"][0]["outcome"] == "unchanged"
        assert retried["outcomes"][0]["revision"] == 2
        assert _docs(primary["id"])[0]["document_id"] == document_id


def test_metadata_only_import_replacement_advances_revision_and_full_retry_is_unchanged(accounts):
    primary, _secondary = accounts
    first = _payload("first.csv", b"Name,Body,Ref\nOriginal,same body,manual-a\n", {"title": "Name", "content": "Body", "source": "Ref"})
    changed = _payload("second.csv", b"Name,Body,Ref\nRenamed,same body,manual-b\n", {"title": "Name", "content": "Body", "source": "Ref"})
    with concepts.owner_scope(primary["id"]):
        created = knowledge.import_commit(first)
        document_id = created["outcomes"][0]["document_id"]
        preview = knowledge.import_preview(changed)
        assert preview["valid_records"][0]["duplicate"]["document_id"] == document_id
        replaced = knowledge.import_commit({**changed, "duplicate_actions": [{"row_number": 2, "action": "replace"}]})
        assert replaced["outcomes"][0]["revision"] == 2
        assert replaced["outcomes"][0]["outcome"] == "replaced"
        repeated = knowledge.import_commit({**changed, "duplicate_actions": [{"row_number": 2, "action": "replace"}]})
        assert repeated["outcomes"][0]["revision"] == 2
        assert repeated["outcomes"][0]["outcome"] == "unchanged"
        doc = knowledge.get_document({"document_id": document_id})
        assert (doc["title"], doc["source_label"], doc["revision"]) == ("Renamed", "manual-b", 2)


def test_save_title_and_source_only_edits_advance_revision(accounts):
    primary, _secondary = accounts
    with concepts.owner_scope(primary["id"]):
        created = knowledge.save_document({"title": "Title one", "source_label": "Source one", "content": "same body"})
        document_id = created["document"]["document_id"]
        title_edit = knowledge.save_document({"document_id": document_id, "title": "Title two", "source_label": "Source one", "content": "same body"})
        source_edit = knowledge.save_document({"document_id": document_id, "title": "Title two", "source_label": "Source two", "content": "same body"})
        identical = knowledge.save_document({"document_id": document_id, "title": "Title two", "source_label": "Source two", "content": "same body"})
        assert (title_edit["document"]["revision"], source_edit["document"]["revision"], identical["document"]["revision"]) == (2, 3, 3)


def test_parallel_first_open_serializes_missing_database_creation(tmp_path, monkeypatch):
    path = tmp_path / "first-open.sqlite3"
    monkeypatch.setattr(concepts, "_db_path", lambda: path)
    assert not path.exists()

    barrier = threading.Barrier(8)
    errors: list[str] = []
    def open_and_migrate():
        try:
            barrier.wait(timeout=10)
            with concepts._connect_db() as db:
                assert db.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()[0] == 0
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=open_and_migrate) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.execute("SELECT version FROM app_schema_migrations WHERE component='state' ORDER BY version").fetchall() == [(1,), (2,), (3,), (4,), (5,)]


def test_jsonl_invalid_row_is_reported_without_echo_and_valid_rows_commit(accounts):
    primary, _secondary = accounts
    raw = b'{"title":"ok","content":"safe text"}\nSECRET_MARKER bad json\n'
    payload = _payload("rows.jsonl", raw, {"title": "title", "content": "content"})
    with concepts.owner_scope(primary["id"]):
        preview = knowledge.import_preview(payload)
        assert preview["fields_available"] == ["content", "title"]
        assert preview["errors"] == [{"code": "INVALID_JSONL_ROW", "message": "Row is not valid JSON.", "row_number": 2}]
        assert "SECRET_MARKER" not in json.dumps(preview)
        result = knowledge.import_commit(payload)
        assert result["partial"] is True
        assert result["outcomes"][0]["outcome"] == "created"
        assert "SECRET_MARKER" not in json.dumps(result)


def test_import_quota_failure_keeps_rows_and_never_calls_elasticsearch(accounts, monkeypatch):
    primary, _secondary = accounts
    with concepts.owner_scope(primary["id"]):
        knowledge.save_document({"title": "Existing", "content": "12345"})
        before = _docs(primary["id"])
        monkeypatch.setattr(knowledge, "MAX_ACCOUNT_BYTES", 5)
        monkeypatch.setattr(knowledge, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("import must not call Elasticsearch")))
        result = knowledge.import_commit(_payload("quota.txt", b"new"))
        assert result["partial"] is True
        assert result["outcomes"][0]["outcome"] == "failed"
        assert result["errors"][0]["code"] == "ACCOUNT_QUOTA_EXCEEDED"
        assert _docs(primary["id"]) == before


def test_export_restore_round_trip_conflicts_and_account_isolation(accounts, monkeypatch):
    primary, secondary = accounts
    import_data = _payload("roundtrip.md", "private archive text".encode())
    with concepts.owner_scope(primary["id"]):
        concept = concepts.save_concept({"name": "R04 test", "corpus": {"index": "fixture", "text_fields": ["body"]}, "queries": [{"id": "q1", "query": "archive"}]})["concept"]
        saved = knowledge.import_commit(import_data)
        document_id = saved["outcomes"][0]["document_id"]
        knowledge.judge({"concept_id": concept["id"], "query_id": "q1", "document_id": document_id, "rating": 3})
        archive = knowledge.export_archive()
        assert archive["format"] == knowledge.ARCHIVE_FORMAT
        assert "owner_id" not in json.dumps(archive)
        assert "control.sqlite3" not in json.dumps(archive)
        db_path = auth.state_database_path(primary["id"])
        db = sqlite3.connect(db_path)
        db.execute("DELETE FROM knowledge_fts WHERE document_id=?", (document_id,))
        db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,))
        db.execute("DELETE FROM knowledge_documents WHERE id=?", (document_id,))
        db.execute("DELETE FROM knowledge_judgments")
        db.commit()
        db.close()
        preview = knowledge.restore_preview({"archive": archive})
        assert preview["errors"] == []
        restored = knowledge.restore_commit({"archive": archive, "expected_sha256": preview["archive_sha256"], "actions": []})
        assert restored["documents"] == [{"document_id": document_id, "outcome": "created", "revision": 1}]
        assert restored["judgments"][0]["outcome"] == "restored"
        assert _docs(primary["id"])[0]["document_id"] == document_id

        # A forged payload owner is ignored; each owner sees their own DB only.
        assert knowledge.import_preview({**import_data, "owner_id": secondary["id"]})["usage"]["documents"] == 1
    with concepts.owner_scope(secondary["id"]):
        assert knowledge.export_archive()["documents"] == []
        assert knowledge.list_documents()["documents"] == []


def test_restore_rejects_changed_archive_and_conflict_without_choice(accounts):
    primary, _secondary = accounts
    data = _payload("one.txt", b"one private record")
    with concepts.owner_scope(primary["id"]):
        knowledge.import_commit(data)
        archive = knowledge.export_archive()
        preview = knowledge.restore_preview({"archive": archive})
        with pytest.raises(knowledge.KnowledgeError, match="changed after preview"):
            knowledge.restore_commit({"archive": {**archive, "created_at": "changed"}, "expected_sha256": preview["archive_sha256"], "actions": []})
        with pytest.raises(knowledge.KnowledgeError, match="conflict"):
            knowledge.restore_commit({"archive": archive, "expected_sha256": preview["archive_sha256"], "actions": []})
        assert len(_docs(primary["id"])) == 1


def test_restore_conflict_skip_and_replace_report_document_judgment_outcomes(accounts):
    primary, _secondary = accounts
    with concepts.owner_scope(primary["id"]):
        concept = concepts.save_concept({"name": "Restore conflict", "corpus": {"index": "fixture", "text_fields": ["body"]}, "queries": [{"id": "q1", "query": "old text"}]})["concept"]
        first = knowledge.import_commit(_payload("restore.txt", b"old text"))
        document_id = first["outcomes"][0]["document_id"]
        knowledge.judge({"concept_id": concept["id"], "query_id": "q1", "document_id": document_id, "rating": 2})
        archive = knowledge.export_archive()
        knowledge.save_document({"document_id": document_id, "title": "restore", "content": "new current text"})
        preview = knowledge.restore_preview({"archive": archive})
        assert preview["conflicts"][0]["document_id"] == document_id
        skipped = knowledge.restore_commit({"archive": archive, "expected_sha256": preview["archive_sha256"], "actions": [{"document_id": document_id, "action": "skip"}]})
        assert skipped["document_outcomes"][0]["outcome"] == "skipped"
        assert skipped["judgment_outcomes"][0]["outcome"] == "skipped"

        restored = knowledge.restore_commit({"archive": archive, "expected_sha256": preview["archive_sha256"], "actions": [{"document_id": document_id, "action": "replace"}]})
        assert restored["document_outcomes"][0]["outcome"] == "replaced"
        assert restored["document_outcomes"][0]["revision"] == 3
        assert restored["judgment_outcomes"][0]["outcome"] == "restored"
        assert knowledge.get_document({"document_id": document_id})["content"] == "old text"


def test_state_v2_migration_is_repeatable_and_failure_preserves_v1_source(tmp_path, monkeypatch):
    path = tmp_path / "state-v1.sqlite3"
    db = sqlite3.connect(path)
    storage._state_v1(db)
    storage._ensure_ledger(db)
    db.execute("INSERT INTO knowledge_documents(id,title,source_label,content,content_bytes,created_at,updated_at) VALUES('legacy','old','src','legacy text',11,'now','now')")
    db.execute("INSERT INTO app_schema_migrations(component,version) VALUES('state',1)")
    db.commit()
    before_columns = [tuple(row) for row in db.execute("PRAGMA table_info(knowledge_documents)")]
    before_rows = [tuple(row) for row in db.execute("SELECT * FROM knowledge_documents")]
    original_v2 = storage._MIGRATIONS["state"][2]
    monkeypatch.setitem(storage._MIGRATIONS["state"], 2, lambda _db: (_ for _ in ()).throw(sqlite3.OperationalError("injected")))
    with pytest.raises(sqlite3.OperationalError):
        storage.migrate(db, "state")
    assert [tuple(row) for row in db.execute("PRAGMA table_info(knowledge_documents)")] == before_columns
    assert [tuple(row) for row in db.execute("SELECT * FROM knowledge_documents")] == before_rows
    assert [row[0] for row in db.execute("SELECT version FROM app_schema_migrations WHERE component='state'")] == [1]
    db.close()

    db = sqlite3.connect(path)
    monkeypatch.setitem(storage._MIGRATIONS["state"], 2, original_v2)
    storage.migrate(db, "state")
    storage.migrate(db, "state")
    migrated = db.execute("SELECT content_sha256,revision,source_name FROM knowledge_documents WHERE id='legacy'").fetchone()
    assert tuple(migrated) == (hashlib.sha256(b"legacy text").hexdigest(), 1, "")
    assert [row[0] for row in db.execute("SELECT version FROM app_schema_migrations WHERE component='state' ORDER BY version")] == [1, 2, 3, 4, 5]
    db.close()
