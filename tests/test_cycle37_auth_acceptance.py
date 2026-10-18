"""Cycle 37 test-first account boundary acceptance coverage."""
from __future__ import annotations

import json
import hashlib
import io
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import redirect_stderr
from http.cookiejar import CookieJar
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from es_rag_tuner import server
from es_rag_tuner import auth, concepts


def _request(base, path, *, method="GET", payload=None, opener=None, csrf=None, origin=None):
    headers = {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if method == "POST":
        headers["Origin"] = origin if origin is not None else base
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    client = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    try:
        with client.open(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return response.status, response.headers, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"raw": raw}
        return exc.code, exc.headers, body


def _new_client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def _login(base, username, password):
    client = _new_client()
    status, _, session = _request(base, "/api/auth/session", opener=client)
    if status != 200 or not session.get("csrf_token"):
        raise AssertionError(f"login bootstrap session missing CSRF token: {status} {session}")
    status, headers, result = _request(
        base, "/api/auth/login", method="POST", payload={"username": username, "password": password},
        opener=client, csrf=session["csrf_token"],
    )
    return client, status, headers, result


class Cycle37AuthBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cycle37-auth-baseline-")
        cls.db_path = Path(cls.temp.name) / "synthetic.sqlite3"
        cls.env = mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(cls.db_path), "ES_RAG_ACCEPTANCE_ES_URL": "http://127.0.0.1:1"})
        cls.env.start()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", port), server.WorkbenchHandler)
        cls.base = f"http://127.0.0.1:{port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls.env.stop()
        cls.temp.cleanup()

    def test_session_endpoint_reports_unconfigured_before_bootstrap(self):
        with urllib.request.urlopen(self.base + "/api/auth/session", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {"configured": False, "authenticated": False})

    def test_first_admin_has_no_public_http_bootstrap_route(self):
        status, _, body = _request(self.base, "/api/auth/bootstrap", method="POST", payload={
            "username": "http-attacker", "display_name": "No Route", "password": "Cycle37-http-bootstrap-password!",
        })
        self.assertIn(status, (401, 404))
        self.assertNotIn("authenticated", body)

    def test_business_api_route_inventory_fails_closed_without_session(self):
        """Private route inventory must reject anonymous calls before handlers run."""
        post_paths = (
            "/api/connect", "/api/sample-info", "/api/sample-import", "/api/vectorize",
            "/api/mapping", "/api/search", "/api/code-rag", "/api/explain", "/api/document",
            "/api/token-preview", "/api/token-preview/prepare", "/api/evaluate", "/api/tune",
            "/api/corpus/schema", "/api/concepts/list", "/api/concepts/save",
            "/api/concepts/quickstart", "/api/concepts/ensure-query", "/api/concepts/diagnose",
            "/api/concepts/versions", "/api/concepts/restore", "/api/concepts/export",
            "/api/concepts/preview", "/api/concepts/information-need-preview",
            "/api/concepts/vector-candidates", "/api/concepts/mode-comparison",
            "/api/concepts/mode-comparison-group", "/api/concepts/locate-document",
            "/api/concepts/document", "/api/concepts/judge", "/api/concepts/tune/readiness",
            "/api/concepts/tune", "/api/concepts/runs", "/api/concepts/runs/export",
            "/api/ai/status", "/api/ai/sessions/create", "/api/ai/sessions/message",
            "/api/ai/sessions/history", "/api/ai/sessions/reset", "/api/ai/jobs/get",
            "/api/ai/jobs/cancel", "/api/admin/accounts/list", "/api/admin/accounts/create",
            "/api/admin/accounts/update", "/api/admin/accounts/disable", "/api/admin/accounts/password/reset",
            "/api/auth/logout", "/api/auth/password/change", "/api/auth/bootstrap",
        )
        handler_names = (
            "_connect", "_sample_info", "_sample_import", "_vectorize", "_mapping", "_search",
            "_code_rag", "_explain", "_document", "_token_preview", "_token_preview_prepare",
            "_evaluate", "_tune", "_concept_schema", "_concept_list", "_concept_save",
            "_concept_quickstart", "_concept_ensure_query", "_concept_diagnose", "_concept_versions",
            "_concept_restore", "_concept_export", "_concept_preview", "_concept_information_need_preview",
            "_concept_vector_candidates", "_concept_mode_comparison", "_concept_mode_comparison_group",
            "_concept_locate_document", "_concept_document", "_concept_judge", "_concept_tune_readiness",
            "_concept_tune", "_concept_runs", "_concept_run_export", "_ai_status", "_ai_create_session",
            "_ai_message", "_ai_history", "_ai_reset", "_ai_job", "_ai_cancel",
        )
        failures = []
        with ExitStack() as stack:
            for name in handler_names:
                stack.enter_context(mock.patch.object(server.WorkbenchHandler, name, return_value={"handler_called": name}))
            for path in post_paths:
                request = urllib.request.Request(
                    self.base + path, data=b"{}", headers={"Content-Type": "application/json", "Origin": self.base}, method="POST"
                )
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        status = response.status
                        body = response.read().decode("utf-8")
                except urllib.error.HTTPError as exc:
                    status, body = exc.code, exc.read().decode("utf-8")
                if status not in (401, 403):
                    failures.append(f"POST {path}: status={status}, body={body}")

        for path in ("/api/token-preview/status", "/api/codebase-status"):
            with mock.patch.object(server.token_preview, "status", return_value={"private": True}), \
                    mock.patch.object(server.codebase, "status", return_value={"private": True}):
                try:
                    with urllib.request.urlopen(self.base + path, timeout=5) as response:
                        status, body = response.status, response.read().decode("utf-8")
                except urllib.error.HTTPError as exc:
                    status, body = exc.code, exc.read().decode("utf-8")
            if status not in (401, 403):
                failures.append(f"GET {path}: status={status}, body={body}")

        with urllib.request.urlopen(self.base + "/api/health", timeout=5) as response:
            self.assertEqual(response.status, 200, "minimal health endpoint remains public")
            self.assertEqual(set(json.loads(response.read())), {"ok", "version"})
        self.assertEqual(failures, [], "anonymous private route access was not denied:\n" + "\n".join(failures))


class Cycle37AuthAPI(unittest.TestCase):
    ADMIN_PASSWORD = "Cycle37-admin-password-001!"
    USER_PASSWORD = "Cycle37-user-password-001!"

    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), server.WorkbenchHandler)
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cycle37-auth-api-")
        self.db_path = Path(self.temp.name) / "synthetic.sqlite3"
        self.env = mock.patch.dict(os.environ, {
            "ES_RAG_CONCEPT_DB": str(self.db_path),
            "ES_RAG_ACCEPTANCE_ES_URL": "http://127.0.0.1:1",
        })
        self.env.start()
        self.admin_user = auth.bootstrap_admin("cycle-admin", "Cycle Admin", self.ADMIN_PASSWORD)
        self.admin, status, self.admin_headers, self.admin_session = _login(
            self.base, "cycle-admin", self.ADMIN_PASSWORD
        )
        self.assertEqual(status, 200, self.admin_session)
        self.admin_csrf = self.admin_session["csrf_token"]

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def post(self, path, payload, *, client=None, csrf=None, origin=None):
        return _request(self.base, path, method="POST", payload=payload, opener=client or self.admin,
                        csrf=self.admin_csrf if csrf is None else csrf, origin=origin)

    def create_user(self, username="cycle-user", display="Cycle User", password=None):
        status, _, body = self.post("/api/admin/accounts/create", {
            "username": username, "display_name": display,
            "password": password or self.USER_PASSWORD,
        })
        self.assertEqual(status, 201, body)
        return body["account"]

    @staticmethod
    def clean_concept(concept_id, name):
        return {
            "id": concept_id, "name": name, "description": "synthetic private account fixture",
            "aliases": [], "related": [], "excluded_terms": [],
            "corpus": {"index": "synthetic-alias", "title_field": "", "text_fields": ["body"], "filter_fields": []},
            "filters": [], "settings": {"mode": "bm25", "size": 2, "candidate_size": 10},
            "queries": [{"id": "q1", "query": "synthetic account query", "split": "train"}],
        }

    def test_session_cookie_admin_controls_password_change_and_revocation(self):
        session_cookie = next(
            value for value in self.admin_headers.get_all("Set-Cookie", [])
            if value.startswith(auth.COOKIE_NAME + "=")
        )
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=Strict", session_cookie)
        cookie_value = session_cookie.split("=", 1)[1].split(";", 1)[0]
        self.assertNotIn("cycle-admin", cookie_value)
        self.assertNotIn(self.ADMIN_PASSWORD, cookie_value)
        self.assertNotEqual(cookie_value, self.admin_csrf)
        self.assertEqual(set(self.admin_session["user"]), {"id", "username", "display_name", "role"})

        status, _, session = _request(self.base, "/api/auth/session", opener=self.admin)
        self.assertEqual(status, 200)
        self.assertEqual(session["user"], self.admin_user)
        self.assertTrue(session["authenticated"])
        self.assertTrue(session["csrf_token"])

        user = self.create_user()
        self.assertNotIn("password", json.dumps(user).lower())
        self.assertNotIn("hash", json.dumps(user).lower())
        status, _, listed = self.post("/api/admin/accounts/list", {}, client=self.admin, csrf=self.admin_csrf)
        self.assertEqual(status, 200, listed)
        self.assertEqual({item["username"] for item in listed["accounts"]}, {"cycle-admin", "cycle-user"})
        self.assertNotIn("password_hash", json.dumps(listed).lower())
        self.assertNotIn(self.USER_PASSWORD, json.dumps(listed))
        status, _, renamed = self.post("/api/admin/accounts/update", {
            "user_id": user["id"], "display_name": "Renamed User",
        })
        self.assertEqual(status, 200, renamed)
        self.assertEqual(renamed["account"]["display_name"], "Renamed User")
        self.assertNotIn("hash", json.dumps(renamed).lower())

        # A password change invalidates all old sessions and requires a fresh login.
        status, _, changed = self.post("/api/auth/password/change", {
            "current_password": self.ADMIN_PASSWORD, "new_password": "Cycle37-admin-password-002!",
        })
        self.assertEqual(status, 200, changed)
        status, _, old_session = _request(self.base, "/api/auth/session", opener=self.admin)
        self.assertEqual(status, 200)
        self.assertFalse(old_session["authenticated"])
        new_client, status, headers, result = _login(
            self.base, "cycle-admin", "Cycle37-admin-password-002!"
        )
        self.assertEqual(status, 200, result)
        new_cookie = next(value for value in headers.get_all("Set-Cookie", []) if value.startswith(auth.COOKIE_NAME + "="))
        self.assertNotEqual(cookie_value, new_cookie.split("=", 1)[1].split(";", 1)[0])
        status, _, logged_out = _request(self.base, "/api/auth/logout", method="POST", payload={},
                                         opener=new_client, csrf=result["csrf_token"])
        self.assertEqual(status, 200, logged_out)
        status, _, revoked = _request(self.base, "/api/auth/session", opener=new_client)
        self.assertFalse(revoked["authenticated"])

    def test_configured_but_unauthenticated_session_is_non_sensitive(self):
        guest = _new_client()
        status, _, session = _request(self.base, "/api/auth/session", opener=guest)
        self.assertEqual(status, 200)
        self.assertEqual(session["configured"], True)
        self.assertEqual(session["authenticated"], False)
        self.assertTrue(session["csrf_token"])
        self.assertNotIn("user", session)
        self.assertNotIn("password", json.dumps(session).lower())
        self.assertNotIn("hash", json.dumps(session).lower())
        status, _, denied = _request(self.base, "/api/concepts/list", method="POST", payload={}, opener=guest,
                                     csrf=session["csrf_token"])
        self.assertEqual(status, 401, denied)

    def test_csrf_origin_expiry_disable_and_last_admin_guards(self):
        status, _, missing = self.post("/api/concepts/save", {"concept": self.clean_concept("csrf-a", "CSRF")}, csrf="")
        self.assertEqual(status, 403, missing)
        user = self.create_user()
        other_client, status, _, other_session = _login(self.base, user["username"], self.USER_PASSWORD)
        self.assertEqual(status, 200, other_session)
        status, _, foreign = self.post("/api/concepts/save", {"concept": self.clean_concept("csrf-b", "Foreign token")},
                                       client=other_client, csrf=self.admin_csrf)
        self.assertEqual(status, 403, foreign)
        status, _, wrong_origin = self.post("/api/concepts/save", {"concept": self.clean_concept("csrf-c", "Wrong origin")},
                                            client=self.admin, csrf=self.admin_csrf, origin="http://localhost:65530")
        self.assertEqual(status, 403, wrong_origin)

        # Expiration revokes the opaque session record even while its cookie remains present.
        with auth._db() as db:
            db.execute("UPDATE auth_sessions SET expires_at=?", (int(time.time()) - 1,))
        status, _, expired = self.post("/api/concepts/list", {}, client=self.admin, csrf=self.admin_csrf)
        self.assertEqual(status, 401, expired)

        # Use a fresh admin login to exercise disable and the final-admin invariant.
        self.admin, status, _, self.admin_session = _login(self.base, "cycle-admin", self.ADMIN_PASSWORD)
        self.assertEqual(status, 200)
        self.admin_csrf = self.admin_session["csrf_token"]
        status, _, last_admin = self.post("/api/admin/accounts/disable", {
            "user_id": self.admin_user["id"], "disabled": True,
        })
        self.assertEqual(status, 409, last_admin)
        user2 = self.create_user("cycle-disabled", "Cycle Disabled")
        disabled_client, status, _, disabled_session = _login(self.base, user2["username"], self.USER_PASSWORD)
        self.assertEqual(status, 200, disabled_session)
        status, _, disabled = self.post("/api/admin/accounts/disable", {
            "user_id": user2["id"], "disabled": True,
        })
        self.assertEqual(status, 200, disabled)
        status, _, revoked = _request(self.base, "/api/concepts/list", method="POST", payload={},
                                      opener=disabled_client, csrf=disabled_session["csrf_token"])
        self.assertEqual(status, 401, revoked)

    def test_admin_password_reset_revokes_target_sessions_and_rejects_self_reset(self):
        user = self.create_user("password-reset", "Password Reset")
        target, status, _, target_session = _login(self.base, user["username"], self.USER_PASSWORD)
        self.assertEqual(status, 200, target_session)
        new_password = "Cycle37-password-reset-new-001!"
        status, _, reset = self.post("/api/admin/accounts/password/reset", {
            "user_id": user["id"], "new_password": new_password,
        })
        self.assertEqual(status, 200, reset)
        self.assertEqual(reset, {"reset": True})
        with auth._db() as db:
            count = db.execute("SELECT COUNT(*) FROM auth_sessions WHERE user_id=?", (user["id"],)).fetchone()[0]
        self.assertEqual(count, 0, "password reset must revoke target sessions immediately")
        status, _, stale = self.post("/api/concepts/list", {}, client=target, csrf=target_session["csrf_token"])
        self.assertEqual(status, 401, stale)
        fresh, status, _, fresh_session = _login(self.base, user["username"], new_password)
        self.assertEqual(status, 200, fresh_session)
        status, _, self_reset = self.post("/api/admin/accounts/password/reset", {
            "user_id": self.admin_user["id"], "new_password": "Cycle37-admin-reset-001!",
        })
        self.assertEqual(status, 400, self_reset)
        status, _, still_admin = self.post("/api/concepts/list", {}, client=self.admin, csrf=self.admin_csrf)
        self.assertEqual(status, 200, still_admin)
        self.assertNotIn(new_password, json.dumps(reset) + json.dumps(self_reset))

    def test_password_policy_preserves_unicode_and_spaces_and_cli_recovery_rotates_sessions(self):
        exact_password = "Cycle37 password 🔐 with trailing space "
        user = self.create_user("unicode-password", "Unicode Password", exact_password)
        client, status, _, session = _login(self.base, user["username"], exact_password)
        self.assertEqual(status, 200, session)
        recovery_password = "Cycle37-admin-recovered-password-001!"
        command = [sys.executable, "-m", "es_rag_tuner", "auth", "reset-admin-password"]
        result = subprocess.run(command, input="cycle-admin\n" + recovery_password + "\n" + recovery_password + "\n",
                                text=True, capture_output=True, env=dict(os.environ), timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(recovery_password, result.stdout + result.stderr)
        status, _, revoked = _request(self.base, "/api/concepts/list", method="POST", payload={},
                                      opener=self.admin, csrf=self.admin_csrf)
        self.assertEqual(status, 401, revoked)
        fresh, status, _, recovered = _login(self.base, "cycle-admin", recovery_password)
        self.assertEqual(status, 200, recovered)
        self.assertNotIn(exact_password, json.dumps(session) + json.dumps(recovered))

    def test_json_type_errors_are_rejected_without_echoing_values(self):
        bad_values = [None, 17, True, {"username": "forged"}, ["forged"]]
        for index, bad in enumerate(bad_values):
            status, _, body = self.post("/api/admin/accounts/create", {
                "username": "bad-type-" + str(index), "display_name": "Bad Type", "password": bad,
            })
            self.assertIn(status, (400, 422), body)
            self.assertNotIn(json.dumps(bad), json.dumps(body))
        for path, payload in (
            ("/api/admin/accounts/update", {"user_id": {"id": self.admin_user["id"]}, "display_name": "bad"}),
            ("/api/admin/accounts/disable", {"user_id": True, "disabled": True}),
            ("/api/admin/accounts/password/reset", {"user_id": self.admin_user["id"], "new_password": None}),
            ("/api/auth/password/change", {"current_password": self.ADMIN_PASSWORD, "new_password": 12345}),
        ):
            status, _, body = self.post(path, payload)
            self.assertIn(status, (400, 422), (path, body))
            self.assertNotIn(json.dumps(payload.get("new_password")), json.dumps(body))

    def test_concurrent_secondary_database_initialization_is_owner_marked(self):
        user = auth.create_account("secondary-race", "Secondary Race", self.USER_PASSWORD)
        barrier = threading.Barrier(2)
        errors = []
        def open_state():
            try:
                barrier.wait(timeout=5)
                with concepts.owner_scope(user["id"]):
                    with concepts._connect_db() as db:
                        db.execute("SELECT 1").fetchone()
            except Exception as exc:
                errors.append(repr(exc))
        threads = [threading.Thread(target=open_state) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(errors, [])
        state_path = auth.state_database_path(user["id"])
        with sqlite3.connect(state_path) as db:
            markers = db.execute("SELECT singleton,owner_id FROM state_owner").fetchall()
        self.assertEqual(markers, [(1, user["id"])])
        # A corrupt/foreign owner marker fails closed instead of returning state.
        with sqlite3.connect(state_path) as db:
            db.execute("UPDATE state_owner SET owner_id=? WHERE singleton=1", (self.admin_user["id"],))
        client, status, _, session = _login(self.base, user["username"], self.USER_PASSWORD)
        self.assertEqual(status, 200, session)
        status, _, denied = self.post("/api/concepts/list", {}, client=client, csrf=session["csrf_token"])
        self.assertEqual(status, 503, denied)

    def test_generic_login_errors_and_throttle(self):
        client = _new_client()
        _, _, challenge = _request(self.base, "/api/auth/session", opener=client)
        hasher = mock.Mock(wraps=auth._hasher)
        hasher.hash.side_effect = AssertionError("unknown-user login must reuse the process dummy hash")
        with mock.patch.object(auth, "_hasher", hasher):
            bad_user_status, _, bad_user = _request(
                self.base, "/api/auth/login", method="POST", payload={"username": "missing-user", "password": "whatever"},
                opener=client, csrf=challenge["csrf_token"],
            )
        hasher.hash.assert_not_called()
        self.assertEqual(bad_user_status, 401)
        client2 = _new_client()
        _, _, challenge2 = _request(self.base, "/api/auth/session", opener=client2)
        bad_password_status, _, bad_password = _request(
            self.base, "/api/auth/login", method="POST", payload={"username": "cycle-admin", "password": "wrong-password"},
            opener=client2, csrf=challenge2["csrf_token"],
        )
        self.assertEqual(bad_password_status, 401)
        self.assertEqual(bad_user, bad_password, "invalid username/password errors must be indistinguishable")
        self.assertNotIn("cycle-admin", json.dumps(bad_user))
        self.assertNotIn(self.ADMIN_PASSWORD, json.dumps(bad_password))

        throttle_client = _new_client()
        _, _, challenge = _request(self.base, "/api/auth/session", opener=throttle_client)
        failures = []
        for _ in range(6):
            status, _, body = _request(
                self.base, "/api/auth/login", method="POST",
                payload={"username": "cycle-admin", "password": "incorrect-password"},
                opener=throttle_client, csrf=challenge["csrf_token"],
            )
            failures.append((status, body))
        self.assertTrue(all(status == 401 for status, _ in failures))
        self.assertTrue(all(body == bad_password for _, body in failures))
        with auth._db() as db:
            attempts = db.execute("SELECT failures,blocked_until FROM auth_login_attempts WHERE username_key=?",
                                  (auth._username_key("cycle-admin"),)).fetchone()
        self.assertIsNotNone(attempts)
        self.assertGreaterEqual(attempts["failures"], 5)
        self.assertGreater(attempts["blocked_until"], 0)

    def test_two_account_concepts_versions_judgments_runs_and_exports_are_isolated(self):
        user = self.create_user()
        bob, status, _, bob_session = _login(self.base, user["username"], self.USER_PASSWORD)
        self.assertEqual(status, 200, bob_session)
        concept_id = "shared-guessed-id"
        concept_a = self.clean_concept(concept_id, "Alice private concept")
        status, _, saved_a = self.post("/api/concepts/save", {"concept": concept_a, "owner_id": user["id"]})
        self.assertEqual(status, 200, saved_a)
        concept_a["name"] = "Alice private concept v2"
        status, _, saved_a2 = self.post("/api/concepts/save", {"concept": concept_a})
        self.assertEqual(status, 200, saved_a2)
        version_a = saved_a["version_id"]
        status, _, judgment_a = self.post("/api/concepts/judge", {
            "concept_id": concept_id, "query_id": "q1", "document_index": "synthetic-index",
            "document_id": "alice-private-doc", "rating": 3, "reason": "alice-only", "owner_id": user["id"],
        })
        self.assertEqual(status, 200, judgment_a)
        run_body = {"query": "synthetic", "baseline": {}, "candidate": {}}
        with concepts.owner_scope(self.admin_user["id"]):
            run_id = concepts._store_run(concept_id, "test", run_body, run_id="alice-private-run")

        bob_concept = self.clean_concept(concept_id, "Bob private concept")
        status, _, saved_b = self.post("/api/concepts/save", {
            "concept": bob_concept, "owner_id": self.admin_user["id"], "user_id": self.admin_user["id"],
        }, client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 200, saved_b)
        self.assertEqual(saved_b["concept"]["name"], "Bob private concept")
        bob_concept["name"] = "Bob private concept updated"
        status, _, saved_b_update = self.post("/api/concepts/save", {"concept": bob_concept},
                                             client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 200, saved_b_update)
        status, _, list_b = self.post("/api/concepts/list", {"owner_id": self.admin_user["id"]},
                                      client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in list_b["concepts"]], ["Bob private concept updated"])
        status, _, versions_b = self.post("/api/concepts/versions", {"concept_id": concept_id},
                                          client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 200)
        self.assertTrue(versions_b["versions"])
        self.assertNotIn(version_a, {item["version_id"] for item in versions_b["versions"]})
        status, _, restore_b = self.post("/api/concepts/restore", {"concept_id": concept_id, "version_id": version_a},
                                         client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 404, restore_b)
        with mock.patch.object(concepts, "_validate_search_fields", return_value={"fields": []}):
            status, _, export_b = self.post("/api/concepts/export", {
                "concept_id": concept_id, "version_id": version_a,
            }, client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 404, export_b)
        status, _, judgment_b = self.post("/api/concepts/judge", {
            "concept_id": concept_id, "query_id": "q1", "document_index": "synthetic-index",
            "document_id": "alice-private-doc", "rating": 0, "reason": "forged update",
            "owner_id": self.admin_user["id"],
        }, client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 200, judgment_b)
        status, _, runs_b = self.post("/api/concepts/runs", {"concept_id": concept_id},
                                      client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 200)
        self.assertEqual(runs_b["runs"], [])
        status, _, run_export_b = self.post("/api/concepts/runs/export", {
            "concept_id": concept_id, "run_id": run_id,
        }, client=bob, csrf=bob_session["csrf_token"])
        self.assertEqual(status, 404, run_export_b)
        with mock.patch.object(concepts, "_validate_search_fields", return_value={"fields": []}):
            status, _, own_profile_export = self.post("/api/concepts/export", {"concept_id": concept_id})
        self.assertEqual(status, 200, own_profile_export)
        status, _, own_run_export = self.post("/api/concepts/runs/export", {
            "concept_id": concept_id, "run_id": run_id,
        })
        self.assertEqual(status, 200, own_run_export)

        with concepts.owner_scope(self.admin_user["id"]):
            own = concepts.get_saved_concept(concept_id)
            own_judgments = concepts._judgments(concept_id)
            own_runs = concepts.list_runs(concept_id)["runs"]
        self.assertEqual(own["name"], "Alice private concept v2")
        self.assertEqual(own_judgments[0]["rating"], 3)
        self.assertEqual(own_judgments[0]["reason"], "alice-only")
        self.assertEqual([item["run_id"] for item in own_runs], [run_id])
        self.assertEqual(judgment_a["judgment"]["rating"], 3)
        with concepts.owner_scope(user["id"]):
            bob_own = concepts.get_saved_concept(concept_id)
            bob_judgments = concepts._judgments(concept_id)
        self.assertEqual(bob_own["name"], "Bob private concept updated")
        self.assertEqual(bob_judgments[0]["rating"], 0)

    def test_ai_sessions_and_jobs_are_account_bound_with_provider_and_worker_mocked(self):
        from es_rag_tuner import ai_coach
        user = self.create_user()
        bob, status, _, bob_session = _login(self.base, user["username"], self.USER_PASSWORD)
        self.assertEqual(status, 200, bob_session)
        corpus = {"index": "synthetic-alias", "text_fields": ["body"], "filter_fields": []}
        connection = {"url": "http://127.0.0.1:1", "auth": {"type": "none"}}
        provider_info = {"available": True, "models": ["synthetic-model"], "default_model": "synthetic-model"}
        with mock.patch.object(ai_coach, "_provider_probe", return_value=provider_info), \
                mock.patch.object(concepts, "_validate_search_fields", return_value={"fields": []}), \
                mock.patch.object(ai_coach, "request", return_value={"cluster_uuid": "synthetic-cluster"}):
            status, _, created = self.post("/api/ai/sessions/create", {
                "provider": "codex", "model": "synthetic-model", "connection": connection, "corpus": corpus,
            })
            self.assertEqual(status, 200, created)
            session_id = created["session_id"]
            with mock.patch.object(ai_coach._POOL, "submit", return_value=None):
                status, _, queued = self.post("/api/ai/sessions/message", {
                    "session_id": session_id, "connection": connection, "message": "synthetic question",
                    "context": {"concept": self.clean_concept("ai-c", "AI fixture")},
                })
            self.assertEqual(status, 200, queued)
            job_id = queued["job_id"]
            for path, payload in (
                ("/api/ai/sessions/history", {"session_id": session_id}),
                ("/api/ai/sessions/reset", {"session_id": session_id}),
                ("/api/ai/jobs/get", {"job_id": job_id}),
                ("/api/ai/jobs/cancel", {"job_id": job_id}),
            ):
                status, _, body = self.post(path, payload, client=bob, csrf=bob_session["csrf_token"])
                self.assertEqual(status, 404, (path, body))
            status, _, own_job = self.post("/api/ai/jobs/get", {"job_id": job_id})
            self.assertEqual(status, 200, own_job)
            status, _, reset = self.post("/api/ai/sessions/reset", {"session_id": session_id})
            self.assertEqual(status, 200, reset)
            status, _, gone = self.post("/api/ai/sessions/history", {"session_id": session_id})
            self.assertEqual(status, 404, gone)

            # Disabled accounts lose the server session immediately, so even
            # a previously issued AI session/job cannot be operated afterward.
            disabled_user = self.create_user("ai-disabled", "AI Disabled")
            disabled_client, login_status, _, disabled_login = _login(self.base, disabled_user["username"], self.USER_PASSWORD)
            self.assertEqual(login_status, 200, disabled_login)
            status, _, disabled_ai = self.post("/api/ai/sessions/create", {
                "provider": "codex", "model": "synthetic-model", "connection": connection, "corpus": corpus,
            }, client=disabled_client, csrf=disabled_login["csrf_token"])
            self.assertEqual(status, 200, disabled_ai)
            with mock.patch.object(ai_coach._POOL, "submit", return_value=None):
                status, _, disabled_job = self.post("/api/ai/sessions/message", {
                    "session_id": disabled_ai["session_id"], "connection": connection,
                    "message": "synthetic in-flight task", "context": {"concept": self.clean_concept("ai-d", "AI disabled fixture")},
                }, client=disabled_client, csrf=disabled_login["csrf_token"])
            self.assertEqual(status, 200, disabled_job)
            status, _, disable_response = self.post("/api/admin/accounts/disable", {
                "user_id": disabled_user["id"], "disabled": True,
            })
            self.assertEqual(status, 200, disable_response)
            with auth._db() as db:
                remaining_sessions = db.execute("SELECT COUNT(*) FROM auth_sessions WHERE user_id=?", (disabled_user["id"],)).fetchone()[0]
            self.assertEqual(remaining_sessions, 0, "disable must revoke account sessions immediately")
            for path, payload in (
                ("/api/ai/sessions/history", {"session_id": disabled_ai["session_id"]}),
                ("/api/ai/sessions/reset", {"session_id": disabled_ai["session_id"]}),
                ("/api/ai/jobs/get", {"job_id": disabled_job["job_id"]}),
                ("/api/ai/jobs/cancel", {"job_id": disabled_job["job_id"]}),
            ):
                status, _, denied = self.post(path, payload, client=disabled_client, csrf=disabled_login["csrf_token"])
                self.assertEqual(status, 401, (path, denied))

    def test_responses_errors_and_http_logs_do_not_disclose_credentials_or_targets(self):
        user_password = "Cycle37-secret-test-password!"
        log_output = io.StringIO()
        with redirect_stderr(log_output):
            account = self.create_user("secret-check", "Secret Check", user_password)
            status, _, body = self.post("/api/admin/accounts/list", {})
            bad_status, _, bad = self.post("/api/auth/password/change", {
                "current_password": "submitted-wrong-secret-001!", "new_password": "submitted-new-secret-001!",
            })
        self.assertEqual(status, 200, body)
        self.assertEqual(bad_status, 401, bad)
        self.assertNotIn(user_password, json.dumps(account) + json.dumps(body))
        self.assertNotIn("password_hash", json.dumps(account) + json.dumps(body).lower())
        self.assertNotIn("submitted-wrong-secret-001!", json.dumps(bad))
        self.assertNotIn("submitted-new-secret-001!", json.dumps(bad))
        self.assertEqual(log_output.getvalue(), "", "HTTP access log must omit request targets and bodies")


class Cycle37BootstrapMigration(unittest.TestCase):
    LEGACY_CONCEPT = {
        "id": "legacy-cycle37", "name": "Legacy synthetic", "description": "keep me",
        "aliases": [], "related": [], "excluded_terms": [],
        "corpus": {"index": "synthetic-alias", "title_field": "", "text_fields": ["body"], "filter_fields": []},
        "filters": [], "settings": {"mode": "bm25", "size": 2, "candidate_size": 10},
        "queries": [{"id": "legacy-q", "query": "legacy query", "split": "train"}],
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cycle37-bootstrap-")
        self.db_path = Path(self.temp.name) / "legacy.sqlite3"
        self.env = mock.patch.dict(os.environ, {"ES_RAG_CONCEPT_DB": str(self.db_path)})
        self.env.start()
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE concepts(id TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE concept_versions(version_id TEXT PRIMARY KEY, concept_id TEXT NOT NULL, version_number INTEGER NOT NULL, body TEXT NOT NULL, fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 1, UNIQUE(concept_id,version_number));
                CREATE TABLE judgments(concept_id TEXT NOT NULL,query_id TEXT NOT NULL,document_index TEXT NOT NULL,document_id TEXT NOT NULL,rating INTEGER,pinned INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,PRIMARY KEY(concept_id,query_id,document_index,document_id));
                CREATE TABLE runs(id TEXT PRIMARY KEY,concept_id TEXT NOT NULL,created_at TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL);
            """)
            body = json.dumps(self.LEGACY_CONCEPT)
            db.execute("INSERT INTO concepts VALUES(?,?,?)", (self.LEGACY_CONCEPT["id"], body, "legacy-time"))
            db.execute("INSERT INTO concept_versions VALUES(?,?,?,?,?,?,1)", ("legacy-version", self.LEGACY_CONCEPT["id"], 1, body, "legacy-fingerprint", "legacy-time"))
            db.execute("INSERT INTO judgments VALUES(?,?,?,?,?,?,?,?)", (self.LEGACY_CONCEPT["id"], "legacy-q", "legacy-index", "legacy-doc", 3, 0, "legacy judgment", "legacy-time"))
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", ("legacy-run", self.LEGACY_CONCEPT["id"], "legacy-time", "synthetic", json.dumps({"query": "legacy"})))
        self.before = self.snapshot()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def snapshot(self):
        with sqlite3.connect(self.db_path) as db:
            return {
                "concepts": db.execute("SELECT id,body,updated_at FROM concepts ORDER BY id").fetchall(),
                "concept_versions": db.execute("SELECT version_id,concept_id,version_number,body,fingerprint,created_at,is_current FROM concept_versions ORDER BY version_id").fetchall(),
                "judgments": db.execute("SELECT concept_id,query_id,document_index,document_id,rating,pinned,reason,updated_at FROM judgments ORDER BY concept_id,query_id,document_id").fetchall(),
                "runs": db.execute("SELECT id,concept_id,created_at,kind,body FROM runs ORDER BY id").fetchall(),
            }

    def test_first_admin_claims_legacy_state_and_claim_migration_is_idempotent(self):
        admin = auth.bootstrap_admin("legacy-admin", "Legacy Admin", "Cycle37-legacy-password-001!")
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(auth.state_database_path(admin["id"]), self.db_path)
        with auth._db() as db:
            marker = db.execute("SELECT owner_id FROM auth_migrations WHERE name='legacy_state_claim'").fetchone()
        self.assertEqual(marker["owner_id"], admin["id"])
        # Reapplying the legacy schema check is safe after the schema upgrade.
        with auth._db() as db:
            auth._prepare_legacy_state_claim(db)
        with auth._db() as db:
            auth._prepare_legacy_state_claim(db)
            self.assertEqual(db.execute("SELECT owner_id FROM auth_migrations WHERE name='legacy_state_claim'").fetchone()["owner_id"], admin["id"])
        self.assertEqual(self.snapshot(), self.before)
        with self.assertRaises(auth.AuthError) as duplicate:
            auth.bootstrap_admin("second-admin", "Second Admin", "Cycle37-legacy-password-002!")
        self.assertEqual(duplicate.exception.status, 409)
        self.assertEqual(self.snapshot(), self.before)

    def test_first_admin_bootstrap_race_has_one_winner_and_no_http_bootstrap(self):
        barrier = threading.Barrier(2)
        outcomes = []
        def contender(username):
            barrier.wait(timeout=5)
            try:
                outcomes.append(("ok", auth.bootstrap_admin(username, username, "Cycle37-race-password-001!")))
            except auth.AuthError as exc:
                outcomes.append(("error", exc.status))
        threads = [threading.Thread(target=contender, args=(f"racer-{n}",)) for n in (1, 2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(sum(item[0] == "ok" for item in outcomes), 1, outcomes)
        self.assertEqual(sum(item == ("error", 409) for item in outcomes), 1, outcomes)
        self.assertEqual(self.snapshot(), self.before)

    def test_bootstrap_cli_is_single_use_and_not_a_public_route(self):
        command = [sys.executable, "-m", "es_rag_tuner", "auth", "bootstrap-admin"]
        env = dict(os.environ)
        env["ES_RAG_CONCEPT_DB"] = str(self.db_path)
        first = subprocess.run(command, input="cli-admin\nCLI Admin\nCycle37-cli-password-001!\nCycle37-cli-password-001!\n",
                               text=True, capture_output=True, env=env, timeout=20)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("Initial administrator configured for cli-admin.", first.stdout)
        self.assertNotIn("Cycle37-cli-password-001!", first.stdout + first.stderr)
        second = subprocess.run(command, input="again-admin\nAgain Admin\nCycle37-cli-password-002!\nCycle37-cli-password-002!\n",
                                text=True, capture_output=True, env=env, timeout=20)
        self.assertNotEqual(second.returncode, 0)
        self.assertNotIn("Cycle37-cli-password-002!", second.stdout + second.stderr)
        self.assertEqual(self.snapshot(), self.before)


if __name__ == "__main__":
    unittest.main()
