"""Serve a no-Elasticsearch browser fixture for the document/chunk panel.

Run with `./.venv/bin/python tests/run_chunk_input_fixture.py`. The fixture
uses a dynamic loopback port and synthetic in-memory documents only.
"""

from __future__ import annotations

import json
import socket
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from es_rag_tuner import server as workbench_server
from es_rag_tuner.es_client import ElasticsearchError


DOCUMENTS = {
    "rag-unsafe": {
        "issue_key": "SYNTH-1",
        "summary": "Synthetic passage source",
        "rag_chunk_text": "<script>alert('synthetic')</script> " + ("longunbroken" * 90),
        "description": "A separate source field",
        "comments": [{"author": "Synthetic author", "body": "Synthetic comment"}],
    },
}
REQUEST_LOG: list[dict[str, str]] = []


def synthetic_es_request(connection, method: str, path: str, body=None):
    REQUEST_LOG.append({"method": method, "path": path})
    if method != "GET":
        raise AssertionError(f"fixture must not write: {method} {path}")
    document_id = unquote(path.rsplit("/", 1)[-1])
    if document_id not in DOCUMENTS:
        raise ElasticsearchError("Synthetic document unavailable", 404)
    return {
        "_index": "synthetic-index",
        "_id": document_id,
        "found": True,
        "_source": json.loads(json.dumps(DOCUMENTS[document_id])),
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FixtureHandler(workbench_server.WorkbenchHandler):
    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/__fixture/log":
            self._json(200, {"calls": REQUEST_LOG})
            return
        super().do_GET()


def main() -> None:
    workbench_server.request = synthetic_es_request
    port = free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), FixtureHandler)
    print(f"FIXTURE_URL=http://127.0.0.1:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
