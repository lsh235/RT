"""Serve disposable stored preview runs for manual browser acceptance.

Run from the repository root with:
    ./.venv/bin/python tests/run_preview_comparison_fixture.py

The script creates a temporary SQLite database, starts the local workbench on
a free loopback port, prints the URL, and removes its database on Ctrl-C. It
does not connect to Elasticsearch or inspect configured user data.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONCEPT_ID = "synthetic-run-comparison"
OTHER_CONCEPT_ID = "synthetic-other-concept"
QUERY = "compare saved preview <img src=x onerror=alert(1)>"
SOURCE_SENTINEL = "SOURCE_BODY_MUST_NOT_RENDER"
REASON_SENTINEL = "PRIVATE_REASON_MUST_NOT_RENDER"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _rows(index: str, entries: list[tuple[str, int | None, str, bool]]) -> list[dict[str, object]]:
    return [
        {"index": index, "id": doc_id, "organic_rank": rank, "pinned": pinned,
         "source_sha256": source_hash}
        for doc_id, rank, source_hash, pinned in entries
    ]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def run_body(
    run_id: str,
    *,
    candidate: list[dict[str, object]] | None = None,
    baseline: list[dict[str, object]] | None = None,
    query_fingerprint: str = "query-fingerprint-1",
    index_uuid: str = "uuid-1",
    index_identity_available: bool = True,
    concept_snapshot: object | None = None,
    include_concept_snapshot: bool = True,
    effective_filters: list[dict[str, object]] | None = None,
    filters_fingerprint: str = "filters-fingerprint-1",
) -> dict[str, object]:
    baseline_rows = baseline or [
        {"index": "idx-a", "id": "base-a", "rank": 1, "source_sha256": _hash("base-hash-a")},
        {"index": "idx-b", "id": "base-b", "rank": 2, "source_sha256": _hash("base-hash-b")},
    ]
    candidate_rows = candidate or [
        *_rows("idx-a", [("shared", 1, _hash("shared-hash"), False)]),
        *_rows("idx-b", [("shared", 2, _hash("shared-hash-b"), False)]),
        *_rows("idx-a", [("pin-only", None, _hash("pin-hash"), True)]),
    ]
    saved_concept = concept_snapshot if concept_snapshot is not None else _concept_snapshot()
    default_filters = saved_concept.get("filters") if isinstance(saved_concept, dict) else None
    actual_filters = effective_filters if effective_filters is not None else (
        default_filters if isinstance(default_filters, list) else []
    )
    input_snapshot = {
        "query": {"id": "synthetic-query", "query": QUERY},
        "filters": actual_filters,
        "judgments": [{"rating": 3, "reason": REASON_SENTINEL}],
        "source": {"body": SOURCE_SENTINEL},
    }
    if include_concept_snapshot:
        input_snapshot["concept"] = saved_concept
    saved_settings = saved_concept.get("settings") if isinstance(saved_concept, dict) else None
    if not isinstance(saved_settings, dict):
        saved_settings = {"mode": "bm25", "size": 3, "candidate_size": 10}
    return {
        "query": QUERY,
        "query_id": "synthetic-query",
        "settings": saved_settings,
        "effective_filters": actual_filters,
        "input_snapshot": input_snapshot,
        "output_snapshot": {"baseline": baseline_rows, "candidate": candidate_rows},
        "reproducibility": {
            "index": "idx-a",
            "index_identity": {
                "available": index_identity_available,
                "requested_index": "idx-a",
                "uuids": ([{"index": "idx-a", "uuid": index_uuid}]
                          if index_identity_available else []),
            },
            "query_fingerprint": query_fingerprint,
            "mapping_fingerprint": "mapping-fingerprint-1",
            "filters_fingerprint": filters_fingerprint,
            "settings_fingerprint": "settings-fingerprint-1",
        },
    }


def _concept_snapshot(changed: bool = False, long: bool = False, all_settings: bool = False) -> dict[str, object]:
    """Synthetic saved input only; deliberately contains no live connection data."""
    concept: dict[str, object] = {
        "id": CONCEPT_ID,
        "name": "Deadline recovery <fixture>",
        "description": "Retry after a request deadline.",
        "aliases": ["timeout retry", "request recovery"],
        "related": [{"term": "jittered backoff", "relation": "mechanism", "weight": 10}],
        "excluded_terms": ["connect timeout"],
        "corpus": {
            "index": "synthetic-index",
            "title_field": "title",
            "text_fields": ["title", "body"],
            "filter_fields": ["project"],
        },
        "filters": [{"field": "project", "value": "alpha"}],
        "settings": {
            "size": 3,
            "candidate_size": 10,
            "mode": "bm25",
            "concept_weight": 1.0,
            "related_weight": 1.0,
            "field_boosts": {"title": 2, "body": 1},
        },
    }
    if changed:
        concept.update({
            "name": "Deadline recovery updated <img src=x onerror=alert(1)>",
            "description": "Recover a request after deadline expiry.",
            "aliases": ["timeout retries", "resumed request"],
            "related": [{"term": "exponential backoff", "relation": "strategy", "weight": 25}],
            "excluded_terms": ["connection timeout", "terminal failure"],
            "corpus": {
                "index": "synthetic-index",
                "title_field": "headline",
                "text_fields": ["headline", "body", "comments.text"],
                "filter_fields": ["project", "team"],
            },
            "filters": [{"field": "project", "value": "beta"}],
            "settings": {
                "size": 5,
                "candidate_size": 12,
                "mode": "hybrid",
                "concept_weight": 1.5,
                "related_weight": 0.75,
                "field_boosts": {"headline": 3, "body": 1, "comments.text": 0.5},
            },
        })
        if not all_settings:
            settings = concept["settings"]
            assert isinstance(settings, dict)
            settings.update({"mode": "bm25", "size": 3, "candidate_size": 10})
    if long:
        concept["name"] = "Synthetic long name " + "N" * 2048
        concept["description"] = "Synthetic long description " + "D" * 4096
        concept["aliases"] = [f"synthetic-alias-{i}-" + "A" * 256 for i in range(80)]
        concept["related"] = [
            {"term": f"synthetic-related-{i}-" + "R" * 256, "relation": "synthetic-relation-" + "Q" * 128, "weight": i}
            for i in range(80)
        ]
        concept["excluded_terms"] = [f"synthetic-exclusion-{i}-" + "E" * 256 for i in range(80)]
        corpus = concept["corpus"]
        assert isinstance(corpus, dict)
        corpus["title_field"] = "synthetic-title-" + "T" * 2048
        corpus["text_fields"] = [f"synthetic.text.{i}-" + "F" * 256 for i in range(80)]
        corpus["filter_fields"] = [f"synthetic-filter-{i}-" + "G" * 256 for i in range(80)]
        concept["filters"] = [{"field": f"synthetic-filter-{i}", "value": "V" * 256} for i in range(80)]
        settings = concept["settings"]
        assert isinstance(settings, dict)
        settings["field_boosts"] = {f"synthetic-field-{i}-" + "B" * 128: i for i in range(80)}
    return concept


def _concept_snapshot_without_aliases() -> dict[str, object]:
    concept = _concept_snapshot()
    del concept["aliases"]
    return concept


def _concept_snapshot_with_empty_aliases() -> dict[str, object]:
    concept = _concept_snapshot()
    concept["aliases"] = []
    return concept


def seed_database(path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    concept = {"id": CONCEPT_ID, "name": "Synthetic comparison fixture"}
    other_concept = {"id": OTHER_CONCEPT_ID, "name": "Other synthetic concept"}
    base_candidate = [
        *_rows("idx-a", [("shared", 1, _hash("shared-hash"), False)]),
        *_rows("idx-b", [("shared", 2, _hash("shared-hash-b"), False)]),
        *_rows("idx-a", [("pin-only", None, _hash("pin-hash"), True)]),
    ]
    swapped_candidate = [
        *_rows("idx-a", [("shared", 2, _hash("shared-hash"), False)]),
        *_rows("idx-b", [("shared", 1, _hash("shared-hash-b"), False)]),
        *_rows("idx-a", [("new", 3, _hash("new-hash"), False)]),
    ]
    mismatch_baseline = [
        {"index": "idx-a", "id": "different-base", "rank": 1, "source_sha256": _hash("changed-base-hash")},
        {"index": "idx-b", "id": "base-b", "rank": 2, "source_sha256": _hash("base-hash-b")},
    ]
    no_index_candidate = [
        {"id": "shared", "organic_rank": 1, "pinned": False, "source_sha256": _hash("shared-hash")},
    ]
    cases = [
        ("match-a", run_body("match-a", candidate=base_candidate), "2026-10-18T00:00:01+00:00"),
        ("match-b", run_body("match-b", candidate=swapped_candidate, concept_snapshot=_concept_snapshot(changed=True), effective_filters=[{"field": "project", "value": "alpha"}]), "2026-10-18T00:00:02+00:00"),
        ("context-mismatch", run_body("context-mismatch", candidate=base_candidate, index_uuid="uuid-other", concept_snapshot=_concept_snapshot(changed=True, all_settings=True), effective_filters=[{"field": "project", "value": "beta"}], filters_fingerprint="filters-fingerprint-2"), "2026-10-18T00:00:03+00:00"),
        ("filter-mismatch", run_body("filter-mismatch", candidate=swapped_candidate, effective_filters=[{"field": "project", "value": "beta"}], filters_fingerprint="filters-fingerprint-2"), "2026-10-18T00:00:18+00:00"),
        ("baseline-mismatch", run_body("baseline-mismatch", candidate=base_candidate, baseline=mismatch_baseline), "2026-10-18T00:00:04+00:00"),
        ("hash-mismatch", run_body("hash-mismatch", candidate=[
            *_rows("idx-a", [("shared", 1, _hash("changed-shared-hash"), False)]),
            *_rows("idx-b", [("shared", 2, _hash("shared-hash-b"), False)]),
        ]), "2026-10-18T00:00:05+00:00"),
        ("missing-index", run_body("missing-index", candidate=no_index_candidate), "2026-10-18T00:00:06+00:00"),
        ("identity-unavailable", run_body("identity-unavailable", index_identity_available=False), "2026-10-18T00:00:07+00:00"),
        ("settings-unchanged-a", run_body("settings-unchanged-a"), "2026-10-18T00:00:10+00:00"),
        ("settings-unchanged-b", run_body("settings-unchanged-b"), "2026-10-18T00:00:11+00:00"),
        ("settings-snapshot-missing", run_body("settings-snapshot-missing", include_concept_snapshot=False), "2026-10-18T00:00:12+00:00"),
        ("settings-snapshot-empty", run_body("settings-snapshot-empty", concept_snapshot={}), "2026-10-18T00:00:13+00:00"),
        ("settings-snapshot-malformed", run_body("settings-snapshot-malformed", concept_snapshot=["not", "an", "object"]), "2026-10-18T00:00:14+00:00"),
        ("settings-long", run_body("settings-long", concept_snapshot=_concept_snapshot(long=True)), "2026-10-18T00:00:15+00:00"),
        ("settings-aliases-missing", run_body("settings-aliases-missing", concept_snapshot=_concept_snapshot_without_aliases()), "2026-10-18T00:00:16+00:00"),
        ("settings-aliases-empty", run_body("settings-aliases-empty", concept_snapshot=_concept_snapshot_with_empty_aliases()), "2026-10-18T00:00:17+00:00"),
    ]
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE concepts (id TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE runs (
                id TEXT PRIMARY KEY, concept_id TEXT NOT NULL, created_at TEXT NOT NULL,
                kind TEXT NOT NULL, body TEXT NOT NULL
            );
        """)
        db.execute("INSERT INTO concepts(id, body, updated_at) VALUES (?, ?, ?)",
                   (CONCEPT_ID, json.dumps(concept), now))
        db.execute("INSERT INTO concepts(id, body, updated_at) VALUES (?, ?, ?)",
                   (OTHER_CONCEPT_ID, json.dumps(other_concept), now))
        for run_id, body, created_at in cases:
            db.execute("INSERT INTO runs(id, concept_id, created_at, kind, body) VALUES (?, ?, ?, ?, ?)",
                       (run_id, CONCEPT_ID, created_at, "preview", json.dumps(body)))
        db.execute("INSERT INTO runs(id, concept_id, created_at, kind, body) VALUES (?, ?, ?, ?, ?)",
                   ("synthetic-tune", CONCEPT_ID, "2026-10-18T00:00:08+00:00", "tune",
                    json.dumps(run_body("synthetic-tune"))))
        db.execute("INSERT INTO runs(id, concept_id, created_at, kind, body) VALUES (?, ?, ?, ?, ?)",
                   ("foreign-preview", OTHER_CONCEPT_ID, "2026-10-18T00:00:09+00:00", "preview",
                    json.dumps(run_body("foreign-preview"))))


def wait_for_server(url: str, process: subprocess.Popen[bytes]) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"workbench server exited with status {process.returncode}")
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise TimeoutError("workbench server did not become healthy within 10 seconds")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="es-rag-preview-compare-qa-") as tmp:
        db_path = Path(tmp) / "synthetic.sqlite3"
        seed_database(db_path)
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env["ES_RAG_CONCEPT_DB"] = str(db_path)
        process = subprocess.Popen(
            [sys.executable, "-m", "es_rag_tuner.server", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_server(url, process)
            print(f"Synthetic saved preview fixture ready at {url}", flush=True)
            print("Database and records are temporary and contain no Elasticsearch connection data.", flush=True)
            process.wait()
        except KeyboardInterrupt:
            pass
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
