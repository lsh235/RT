"""Serve a disposable browser fixture for the tune-readiness panel.

Run with `./.venv/bin/python tests/run_tune_readiness_fixture.py`. It prints a
dynamic loopback URL and fixture concept id, then runs until interrupted.
"""

from __future__ import annotations

import os
import socket
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="es-rag-tune-readiness-browser-") as temp:
        os.environ["ES_RAG_CONCEPT_DB"] = str(Path(temp) / "concepts.sqlite3")
        from es_rag_tuner import concepts
        from es_rag_tuner.server import WorkbenchHandler

        concept = concepts.save_concept({
            "id": "tune-readiness-browser-fixture",
            "name": "Tune readiness browser fixture",
            "description": "Synthetic browser acceptance data",
            "corpus": {"index": "synthetic-index", "text_fields": ["body"]},
            "queries": [
                {"id": "train-current", "query": "current train query", "split": "train"},
                {"id": "train-other", "query": "other train query", "split": "train"},
                {"id": "validation", "query": "validation query", "split": "validation"},
            ],
        })["concept"]
        concepts.save_judgment({
            "concept_id": concept["id"], "query_id": "train-other",
            "document_index": "synthetic-index", "document_id": "synthetic-doc-train",
            "rating": 2, "pinned": False, "reason": "private reason browser sentinel",
        })
        concepts.save_judgment({
            "concept_id": concept["id"], "query_id": "validation",
            "document_index": "synthetic-index", "document_id": "synthetic-doc-validation",
            "rating": 3, "pinned": False, "reason": "private reason browser sentinel",
        })
        port = free_port()
        server = ThreadingHTTPServer(("127.0.0.1", port), WorkbenchHandler)
        print(f"FIXTURE_URL=http://127.0.0.1:{port}", flush=True)
        print(f"FIXTURE_CONCEPT_ID={concept['id']}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
