"""R05 policy and persisted reindex-job contract tests (no live Elasticsearch)."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest import mock

import pytest

from es_rag_tuner import auth, chunking, concepts, knowledge

PASSWORD = "R05-offline-acceptance-password-123!"


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setenv("ES_RAG_CONCEPT_DB", str(tmp_path / "control.sqlite3"))
    admin = auth.bootstrap_admin("r05-admin-" + uuid.uuid4().hex[:8], "R05 Admin", PASSWORD)
    owner = admin["id"]
    with concepts.owner_scope(owner):
        knowledge.list_documents()
    yield owner
    with concepts.owner_scope(owner):
        path = auth.state_database_path(owner)
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def test_chunk_preview_offsets_policy_and_tokenizer_fail_closed(account):
    source = "alpha\n\nbeta\n\ngamma"
    with concepts.owner_scope(account):
        result = knowledge.preview_chunks({"content": source, "strategy": "paragraph", "size": 9, "overlap": 0})
        assert [chunk["content"] for chunk in result["chunks"]] == ["alpha\n\n", "beta\n\n", "gamma"]
        assert result["chunks"][0]["start_offset"] == 0
        assert result["chunks"][-1]["end_offset"] == len(source)
        with mock.patch.object(chunking, "tokenizer_info", return_value={"available": False, "reason": "fixture tokenizer missing"}):
            with pytest.raises(knowledge.KnowledgeError, match="tokenizer|토크나이저"):
                knowledge.preview_chunks({"content": "alpha beta", "strategy": "token", "size": 16, "overlap": 2})
        with pytest.raises(knowledge.KnowledgeError):
            knowledge.preview_chunks({"content": "x", "strategy": "character", "size": 0, "overlap": 0})


def test_policy_chunks_bind_revision_and_fingerprint(account):
    with concepts.owner_scope(account):
        saved = knowledge.save_document({"title": "one", "content": "first source text"})
        doc_id = saved["document"]["document_id"]
        policy = {"strategy": "character", "size": 6, "overlap": 1}
        knowledge.set_chunk_policy({"policy": policy})
        edited = knowledge.save_document({"document_id": doc_id, "title": "one", "content": "edited source text"})
        expected = chunking.policy_fingerprint(policy)
        assert all(chunk["policy_sha256"] == expected for chunk in edited["chunks"])
        assert all(chunk["source_revision"] == edited["document"]["revision"] for chunk in edited["chunks"])
        ids = [chunk["id"] for chunk in edited["chunks"]]
        assert len(ids) == len(set(ids))
        assert edited["document"]["revision"] == 2


def test_direct_reindex_policy_change_marks_existing_index_stale(account):
    class NoopThread:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
        def start(self):
            return None

    with concepts.owner_scope(account):
        knowledge.save_document({"title": "source", "content": "old policy chunks"})
        fingerprint = knowledge._local_fingerprint()
        with concepts._connect_db() as db:
            db.execute("UPDATE knowledge_es_state SET state='in_sync',generation=1,indexed_chunks=(SELECT COUNT(*) FROM knowledge_chunks),local_fingerprint=?,synced_fingerprint=?,error='' WHERE id=1", (fingerprint, fingerprint))
        assert knowledge.es_status()["state"] == "in_sync"
        with mock.patch.object(knowledge.threading, "Thread", NoopThread):
            started = knowledge.reindex_start({"policy": {"strategy": "character", "size": 9, "overlap": 1}}, object())
        try:
            assert started["state"] == "queued"
            assert knowledge.es_status()["state"] == "stale"
        finally:
            with knowledge._ACTIVE_JOB_IDS_GUARD:
                knowledge._ACTIVE_JOB_IDS.discard(started["job_id"])


def test_job_owner_scope_and_mock_completion_from_local_sources(account):
    fake_connection = object()
    with concepts.owner_scope(account):
        doc = knowledge.save_document({"title": "source", "content": "source of truth"})["document"]
        def publish(_connection, **kwargs):
            kwargs["on_published"]()
            return {"state": "in_sync"}
        with mock.patch.object(knowledge, "_sync_es", side_effect=publish):
            started = knowledge.reindex_start({"policy": {"strategy": "character", "size": 8, "overlap": 1}}, fake_connection)
            deadline = time.time() + 5
            while time.time() < deadline:
                status = knowledge.reindex_status({"job_id": started["job_id"]})
                if status["state"] in {"complete", "failed"}:
                    break
                time.sleep(0.02)
            assert status["state"] == "complete", status
            assert status["completed"] == status["total"] == 1
            foreign_fields = knowledge.reindex_status({"job_id": started["job_id"], "owner_id": "forged", "alias": "shared-index"})
            assert foreign_fields["state"] == "complete"
    other = str(uuid.uuid4())
    with concepts.owner_scope(other):
        with pytest.raises((knowledge.KnowledgeError, auth.AuthError)):
            knowledge.reindex_status({"job_id": started["job_id"]})


def test_failed_job_details_persist_and_retry_completes(account):
    calls = 0
    def failing_then_publishing(_connection, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            failure = knowledge.KnowledgeError("injected staged bulk failure", 503)
            failure.failed_documents = [{"document_id": "fixture-document", "chunk_id": "fixture-chunk", "status": 400, "message": "Elasticsearch rejected this staged chunk."}]
            raise failure
        kwargs["on_published"]()
        return {"state": "in_sync"}

    def wait_terminal(job_id):
        deadline = time.time() + 5
        while time.time() < deadline:
            status = knowledge.reindex_status({"job_id": job_id})
            if status["state"] in {"complete", "failed"}:
                return status
            time.sleep(0.02)
        raise AssertionError(f"job did not finish: {job_id}")

    with concepts.owner_scope(account), mock.patch.object(knowledge, "_sync_es", side_effect=failing_then_publishing):
        knowledge.save_document({"title": "source", "content": "retryable source content"})
        started = knowledge.reindex_start({"policy": {"strategy": "character", "size": 8, "overlap": 1}}, object())
        failed = wait_terminal(started["job_id"])
        assert failed["state"] == "failed", failed
        assert failed["failed_documents"] == [{"document_id": "fixture-document", "chunk_id": "fixture-chunk", "status": 400, "message": "Elasticsearch rejected this staged chunk."}]
        retried = knowledge.reindex_retry({"job_id": started["job_id"]}, object())
        assert retried["job_id"] != started["job_id"]
        completed = wait_terminal(retried["job_id"])
        assert completed["state"] == "complete", completed


def test_cancel_check_prevents_publish_and_retry_creates_fresh_job(account):
    entered = threading.Event()
    release = threading.Event()
    with concepts.owner_scope(account):
        knowledge.save_document({"title": "cancel me", "content": "body"})
        def blocked_sync(_connection, **kwargs):
            entered.set()
            release.wait(3)
            if kwargs["cancel_check"]():
                raise knowledge._ReindexCancelled()
            return {"state": "in_sync"}
        with mock.patch.object(knowledge, "_sync_es", side_effect=blocked_sync):
            started = knowledge.reindex_start({"policy": {"strategy": "character", "size": 10, "overlap": 1}}, object())
            assert entered.wait(3)
            knowledge.reindex_cancel({"job_id": started["job_id"]})
            release.set()
            deadline = time.time() + 5
            while time.time() < deadline:
                status = knowledge.reindex_status({"job_id": started["job_id"]})
                if status["state"] in {"cancelled", "failed"}:
                    break
                time.sleep(0.02)
            assert status["state"] == "cancelled", status
            with mock.patch.object(knowledge, "reindex_start", return_value={"job_id": "retry-fixture", "state": "queued"}) as restart:
                retry = knowledge.reindex_retry({"job_id": started["job_id"]}, object())
            assert retry["job_id"] != started["job_id"]
            assert retry["state"] == "queued"
            assert restart.call_args.args[0]["policy"]["strategy"] == "character"


def test_persisted_running_job_recovers_as_interrupted(account):
    with concepts.owner_scope(account):
        with concepts._connect_db() as db:
            knowledge._schema(db)
            now = knowledge._now()
            db.execute("INSERT INTO knowledge_reindex_jobs(id,state,policy_json,policy_sha256,created_at,updated_at,total_documents,completed_documents,failed_documents_json,source_fingerprint,target_generation,safe_error,cancel_requested) VALUES(?,?,?,?,?,?,0,0,'[]','','','',0)", ("restart-fixture", "running", json.dumps({"strategy": "character", "size": 10, "overlap": 0}), "fixture-policy", now, now))
        result = knowledge.reindex_status({"job_id": "restart-fixture"})
        assert result["state"] == "interrupted"
        assert "Retry" in result["safe_error"]
