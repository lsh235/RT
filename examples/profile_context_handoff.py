#!/usr/bin/env python3
"""Run an exported es-rag-profile-v1 and print a bounded local context bundle."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from es_rag_tuner.context_bundle import build_context_bundle
from es_rag_tuner.es_client import Connection
from es_rag_tuner.profile_runtime import search_profile


def whitespace_token_counter(text: str) -> int:
    """Small deterministic counter; it is not a model tokenizer."""
    return len(text.split())


def _connection_from_environment() -> Connection:
    url = os.environ.get("ES_URL", "http://127.0.0.1:9200")
    api_key = os.environ.get("ES_API_KEY", "")
    username = os.environ.get("ES_USERNAME", "")
    password = os.environ.get("ES_PASSWORD", "")
    if api_key and (username or password):
        raise ValueError("Set either ES_API_KEY or ES_USERNAME/ES_PASSWORD, not both.")
    if api_key:
        auth: dict[str, Any] = {"type": "api_key", "api_key": api_key}
    elif username or password:
        if not username or not password:
            raise ValueError("Both ES_USERNAME and ES_PASSWORD are required for basic authentication.")
        auth = {"type": "basic", "username": username, "password": password}
    else:
        auth = {"type": "none"}
    return Connection.from_payload({"url": url, "auth": auth})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile_file", type=Path, help="JSON file exported by the workbench")
    parser.add_argument("query", help="search query")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--max-entries", type=int, default=10)
    args = parser.parse_args()
    try:
        export = json.loads(args.profile_file.read_text(encoding="utf-8"))
        if not isinstance(export, dict) or export.get("format") != "es-rag-profile-v1" or not isinstance(export.get("profile"), dict):
            raise ValueError("Input is not an es-rag-profile-v1 export.")
        result = search_profile(_connection_from_environment(), export["profile"], args.query)
        bundle = build_context_bundle(
            result,
            token_counter=whitespace_token_counter,
            counter_name="whitespace-word-count-v1",
            max_tokens=args.max_tokens,
            max_entries=args.max_entries,
        )
        # Emit only the sanitized, whole-entry, token-budgeted artifact. Raw
        # search hits may include entries omitted or redacted by the bundler.
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        # Avoid printing transport exceptions, which can echo a URL or request
        # details. The user can inspect configuration locally without exposing it.
        print("Profile search or context-bundle creation failed. Review the profile and runtime settings locally.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
