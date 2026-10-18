"""Read-only connection and feature compatibility report for Elasticsearch."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    return tuple(int(part or 0) for part in match.groups()) if match else None


def _feature_estimates(product: str, build_flavor: str, version: str) -> dict[str, str]:
    parsed = _version_tuple(version)
    if parsed is None:
        return {"dense_vector": "unknown", "knn_query": "unknown"}
    normalized = product.lower()
    flavor = build_flavor.lower()
    if "opensearch" in normalized:
        return {
            "dense_vector": "unsupported",
            "knn_query": "unknown",
        }
    if flavor == "oss":
        return {"dense_vector": "unsupported", "knn_query": "unknown"}
    if flavor != "default":
        return {"dense_vector": "unknown", "knn_query": "unknown"}
    return {
        "dense_vector": "likely" if parsed >= (7, 3, 0) else "unlikely",
        "knn_query": "likely" if parsed >= (8, 0, 0) else "unknown",
    }


def _authorization_header() -> str | None:
    api_key = os.environ.get("ES_API_KEY")
    if api_key:
        return "ApiKey " + api_key
    username, password = os.environ.get("ES_USERNAME"), os.environ.get("ES_PASSWORD")
    if username is not None and password is not None:
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        return "Basic " + token
    return None


def inspect_cluster(url: str, timeout: float = 5.0) -> dict[str, object]:
    """Read only GET / and return a credential-free report."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Elasticsearch URL must be an absolute http:// or https:// URL")
    host = f"[{parts.hostname}]" if ":" in (parts.hostname or "") else parts.hostname or ""
    port = parts.port
    authority = host + (f":{port}" if port else "")
    request_url = urlunsplit((parts.scheme, authority, parts.path.rstrip("/"), "", "")) + "/"
    request = urllib.request.Request(request_url, headers={"Accept": "application/json"})
    authorization = _authorization_header()
    if authorization:
        request.add_header("Authorization", authorization)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    version_data = payload.get("version", {}) if isinstance(payload, dict) else {}
    number = str(version_data.get("number", "unknown"))
    flavor = str(version_data.get("build_flavor", "unknown"))
    declared_product = str(version_data.get("distribution", ""))
    tagline = str(payload.get("tagline", "")) if isinstance(payload, dict) else ""
    if "opensearch" in declared_product.lower() or "opensearch" in tagline.lower():
        distribution = "OpenSearch"
    elif declared_product.lower() in {"elasticsearch", "default", "oss"} or flavor.lower() in {"default", "oss"}:
        distribution = "Elasticsearch"
    else:
        distribution = declared_product or "Elasticsearch-compatible"
    estimates = _feature_estimates(distribution, flavor, number)
    note = "Version and build-flavor estimate only; cluster mappings and plugins were not inspected."
    if distribution == "OpenSearch":
        note = "OpenSearch uses knn_vector rather than Elasticsearch dense_vector; kNN support is plugin-dependent and was not inspected."
    elif flavor.lower() == "oss":
        note = "OSS build estimate; dense_vector is treated as unsupported and kNN support remains unknown without plugin inspection."
    return {
        # URL paths can contain tenant or proxy credentials; report only the origin.
        "url": _redact_url(url),
        "name": payload.get("name", "unknown"),
        "cluster_name": payload.get("cluster_name", "unknown"),
        "distribution": distribution,
        "build_flavor": flavor,
        "version": number,
        "feature_support_estimate": estimates,
        "feature_support_note": note,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Read-only Elasticsearch environment report")
    parser.add_argument("--url", default=os.environ.get("ES_URL", "http://127.0.0.1:9200"))
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        result = inspect_cluster(args.url, args.timeout)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": _safe_error(exc), "url": _redact_url(args.url)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from None
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))


def _redact_url(url: str) -> str:
    """Return origin only; userinfo, path, query, and fragment are never reported."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return "<redacted>"
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        port = parts.port
        authority = host + (f":{port}" if port else "")
        return urlunsplit((parts.scheme, authority, "", "", ""))
    except (TypeError, ValueError):
        return "<redacted>"


def _safe_error(exc: Exception) -> str:
    """Summarize failure type without forwarding exception text from transports."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"Elasticsearch root request failed (HTTP {exc.code})"
    if isinstance(exc, json.JSONDecodeError):
        return "Elasticsearch returned invalid JSON"
    if isinstance(exc, ValueError):
        return "Invalid Elasticsearch URL or response"
    if isinstance(exc, (OSError, TimeoutError, urllib.error.URLError)):
        return "Elasticsearch transport request failed"
    return "Elasticsearch doctor request failed"


if __name__ == "__main__":
    main()
