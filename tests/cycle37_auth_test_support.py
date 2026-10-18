"""Shared authenticated HTTP fixtures for offline workbench API tests."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import ExitStack
from http.cookiejar import CookieJar
from pathlib import Path
from unittest import mock
from http.server import ThreadingHTTPServer
import threading

from es_rag_tuner import auth, concepts


_CLIENTS: dict[str, "AuthenticatedClient"] = {}
_PASSWORD = "Cycle37-offline-test-admin-password-001!"


class AuthenticatedClient:
    def __init__(self, base: str, user: dict, password: str = _PASSWORD):
        self.base = base.rstrip("/")
        self.user = user
        self.password = password
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        status, session = self.request("/api/auth/session")
        if status != 200 or not session.get("csrf_token"):
            raise AssertionError(f"auth fixture did not receive login CSRF token: {status} {session}")
        status, result = self.request("/api/auth/login", {
            "username": user["username"], "password": password,
        }, csrf=session["csrf_token"])
        if status != 200 or not result.get("authenticated"):
            raise AssertionError(f"auth fixture login failed: {status} {result}")
        self.csrf_token = result["csrf_token"]

    def request(self, path: str, payload: dict | None = None, *, csrf: str | None = None):
        headers = {}
        data = None
        method = "GET" if payload is None else "POST"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Origin"] = self.base
            headers["X-CSRF-Token"] = self.csrf_token if csrf is None and hasattr(self, "csrf_token") else (csrf or "")
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"raw": raw.decode("utf-8", errors="replace")}
            return exc.code, body

    def post(self, path: str, payload: dict):
        return self.request(path, payload)


def install_auth_fixture(testcase, base: str, *, es_url: str = "http://127.0.0.1:1") -> AuthenticatedClient:
    """Give one test a fresh DB, bootstrapped admin, owner context, and session."""
    import tempfile

    temp = tempfile.TemporaryDirectory(prefix="cycle37-offline-api-")
    testcase.addCleanup(temp.cleanup)
    db_path = Path(temp.name) / "synthetic.sqlite3"
    env_patch = mock.patch.dict(os.environ, {
        "ES_RAG_CONCEPT_DB": str(db_path),
        "ES_RAG_ACCEPTANCE_ES_URL": es_url,
    })
    env_patch.start()
    testcase.addCleanup(env_patch.stop)
    suffix = uuid.uuid4().hex[:10]
    username = "offline-admin-" + suffix
    user = auth.bootstrap_admin(username, "Offline Test Admin", _PASSWORD)
    owner_cm = concepts.owner_scope(user["id"])
    owner_cm.__enter__()
    testcase.addCleanup(owner_cm.__exit__, None, None, None)
    client = AuthenticatedClient(base, user)
    _CLIENTS[base.rstrip("/")] = client
    testcase.addCleanup(_CLIENTS.pop, base.rstrip("/"), None)
    testcase.db_path = db_path
    testcase.test_admin = user
    testcase.test_api = client
    return client


def post_url(url: str, payload: dict):
    parsed = urllib.parse.urlsplit(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    client = _CLIENTS.get(base)
    if client is None:
        raise AssertionError(f"no authenticated API fixture is registered for {base}")
    return client.post(parsed.path + (("?" + parsed.query) if parsed.query else ""), payload)


def api_request(base: str, path: str, payload: dict | None = None):
    client = _CLIENTS.get(base.rstrip("/"))
    if client is None:
        raise AssertionError(f"no authenticated API fixture is registered for {base}")
    return client.request(path, payload)


def bootstrap_existing_db_client(base: str, db_path: str | Path) -> AuthenticatedClient:
    """Bootstrap and log into a caller-owned temporary DB for subprocess fixtures."""
    with mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(db_path)}):
        suffix = uuid.uuid4().hex[:10]
        user = auth.bootstrap_admin("offline-admin-" + suffix, "Offline Test Admin", _PASSWORD)
    client = AuthenticatedClient(base, user)
    _CLIENTS[base.rstrip("/")] = client
    return client


def start_test_http_server(handler):
    """Start an in-process loopback workbench HTTP server for a fixture class."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread
