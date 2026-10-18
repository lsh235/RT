"""Write a stable fingerprint for the configured small source corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from test_concept_live_acceptance import SOURCE_INDEX, es_request, source_fingerprint


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/record_source_fingerprint.py OUTPUT.json")
    corpus = source_fingerprint(SOURCE_INDEX)
    canonical = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    version = es_request("/").get("version", {}).get("number", "unknown")
    result = {
        "elasticsearch_endpoint_class": "local loopback test service",
        "elasticsearch_version": version,
        "index": SOURCE_INDEX,
        "document_count": corpus["count"],
        "all_documents_sha256": hashlib.sha256(canonical).hexdigest(),
        "document_source_hashes": corpus["sample_ids_and_source_sha256"],
    }
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "document_source_hashes"}, indent=2))


if __name__ == "__main__":
    main()
