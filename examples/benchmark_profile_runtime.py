"""Bounded, read-only concurrency sample for an exported es-rag-profile-v1.

The command reads ES_URL, ES_BENCHMARK_QUERY, and optional ES_USERNAME /
ES_PASSWORD or ES_API_KEY from the environment. It prints aggregate timings
only; it never prints the query, endpoint, credentials, or search hits.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from es_rag_tuner.es_client import Connection
from es_rag_tuner.profile_runtime import search_profile

MAX_ITERATIONS = 100
CONCURRENCY_CHOICES = (1, 2, 4)


def _percentile(values: list[float], percent: float) -> float:
    if not values:
        raise ValueError("at least one sample is required")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def run_benchmark(
    profile: dict[str, Any],
    connection: Connection,
    query: str,
    *,
    iterations: int = 20,
    concurrency: int = 1,
    search: Callable[..., dict[str, Any]] = search_profile,
) -> dict[str, int | float]:
    """Run exactly a bounded number of read-only profile searches."""
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= MAX_ITERATIONS:
        raise ValueError(f"iterations must be an integer from 1 to {MAX_ITERATIONS}")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency not in CONCURRENCY_CHOICES:
        raise ValueError("concurrency must be one of 1, 2, or 4")
    if not query or not query.strip():
        raise ValueError("query is required")

    latencies: list[float] = []
    lock = threading.Lock()

    def one_search(_: int) -> float:
        started = time.perf_counter()
        search(connection, profile, query)
        duration_ms = (time.perf_counter() - started) * 1000.0
        with lock:
            latencies.append(duration_ms)
        return duration_ms

    effective_workers = min(concurrency, iterations)
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as pool:
        # The input range itself is capped; no producer can add more work.
        list(pool.map(one_search, range(iterations)))
    elapsed_seconds = max(time.perf_counter() - started, 1e-9)
    return {
        "concurrency": concurrency,
        "effective_workers": effective_workers,
        "iterations": iterations,
        "searches_completed": len(latencies),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "p50_ms": round(_percentile(latencies, 0.50), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "throughput_per_second": round(len(latencies) / elapsed_seconds, 3),
    }


def _connection_from_environment() -> Connection:
    url = os.environ.get("ES_URL", "").strip()
    if not url:
        raise ValueError("ES_URL is required")
    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("ES_URL must not contain userinfo, query, or fragment")
    api_key = os.environ.get("ES_API_KEY")
    username = os.environ.get("ES_USERNAME")
    password = os.environ.get("ES_PASSWORD")
    if api_key:
        auth = {"type": "api_key", "api_key": api_key}
    elif username is not None or password is not None:
        if not username or password is None:
            raise ValueError("set both ES_USERNAME and ES_PASSWORD")
        auth = {"type": "basic", "username": username, "password": password}
    else:
        auth = {"type": "none"}
    return Connection.from_payload({"url": url, "auth": auth})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded read-only profile runtime measurement")
    parser.add_argument("profile", help="path to an exported profile JSON file")
    parser.add_argument("--iterations", type=int, default=20, help=f"search count (1–{MAX_ITERATIONS})")
    parser.add_argument("--concurrency", type=int, choices=CONCURRENCY_CHOICES, default=1)
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.iterations <= MAX_ITERATIONS:
            raise ValueError(f"iterations must be between 1 and {MAX_ITERATIONS}")
        envelope = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        profile = envelope.get("profile") if isinstance(envelope, dict) else None
        if not isinstance(profile, dict):
            raise ValueError("profile envelope is invalid")
        query = os.environ.get("ES_BENCHMARK_QUERY", "")
        connection = _connection_from_environment()
        result = run_benchmark(profile, connection, query, iterations=args.iterations, concurrency=args.concurrency)
    except Exception:
        # Never forward exception messages: HTTP clients may include sensitive transport details.
        print("Benchmark failed; details were suppressed to protect query and connection data.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
