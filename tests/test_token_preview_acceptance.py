"""Acceptance tests for the exact E5 passage-token preview helper.

These tests inject a deterministic tokenizer with the same interface as the
production adapter. They do not download assets, load FastEmbed/ONNX, contact
Elasticsearch, or open SQLite. HTTP/browser and pinned-asset compatibility
checks are recorded separately in docs/token-preview-acceptance.md.
"""

from __future__ import annotations

import re
import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import urllib.request

from es_rag_tuner import server as workbench_server
try:
    from tests.cycle37_auth_test_support import install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import install_auth_fixture
from es_rag_tuner import token_preview


@dataclass
class FakeEncoding:
    ids: list[int]
    offsets: list[tuple[int, int]]


class FakeTokenizer:
    """Whitespace tokenizer fixture with CLS/SEP and source character offsets."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, int | None]] = []

    def encode(
        self,
        text: str,
        *,
        truncation: bool = False,
        max_length: int | None = None,
    ) -> FakeEncoding:
        self.calls.append((text, truncation, max_length))
        matches = list(re.finditer(r"\S+", text))
        ids = [1, *(index + 10 for index, _ in enumerate(matches)), 2]
        offsets = [(0, 0), *((match.start(), match.end()) for match in matches), (0, 0)]
        if truncation and max_length is not None:
            ids = ids[:max_length]
            offsets = offsets[:max_length]
        return FakeEncoding(ids=ids, offsets=offsets)


class TokenPreviewAcceptance(unittest.TestCase):
    def test_counts_attended_tokens_including_special_tokens_at_boundaries(self):
        # Fake tokenization produces one `passage:` token, N payload tokens,
        # and two attended special tokens.
        cases = (
            (508, 511, 511, False),
            (509, 512, 512, False),
            (510, 513, 512, True),
        )
        for payload_tokens, full_count, retained_count, truncated in cases:
            with self.subTest(payload_tokens=payload_tokens):
                tokenizer = FakeTokenizer()
                input_text = "passage: " + " ".join(f"word{i}" for i in range(payload_tokens))

                result = token_preview.preview_input(input_text, tokenizer=tokenizer)

                self.assertTrue(result["available"])
                self.assertEqual(result["input_text"], input_text)
                self.assertEqual(result["full_token_count"], full_count)
                self.assertEqual(result["retained_token_count"], retained_count)
                self.assertEqual(result["max_tokens"], 512)
                self.assertEqual(result["truncated"], truncated)
                expected_calls = [(input_text, False, None)]
                if truncated:
                    expected_calls.append((input_text, True, 512))
                self.assertEqual(tokenizer.calls, expected_calls)

                if truncated:
                    # Two special tokens plus `passage:` and 509 payload
                    # tokens fit. The cut is the original offset end of the
                    # final retained source token; remaining whitespace/text
                    # is preserved verbatim in removed_text.
                    cut = input_text.index("word509")
                    cut += len("word508")
                    self.assertEqual(result["cut_char_offset"], cut)
                    self.assertEqual(result["retained_text"], input_text[:cut])
                    self.assertEqual(result["removed_text"], input_text[cut:])
                else:
                    self.assertEqual(result["cut_char_offset"], len(input_text))
                    self.assertEqual(result["retained_text"], input_text)
                    self.assertEqual(result["removed_text"], "")

    def test_empty_or_whitespace_only_input_is_unavailable_not_special_only(self):
        for input_text in ("", " \t\r\n  ", "\u00a0\u3000"):
            with self.subTest(input_text=repr(input_text)):
                result = token_preview.preview_input(input_text, tokenizer=FakeTokenizer())

                self.assertFalse(result["available"])
                self.assertEqual(result["full_token_count"], 0)
                self.assertEqual(result["retained_token_count"], 0)
                self.assertFalse(result["truncated"])
                self.assertEqual(result["input_text"], input_text)
                self.assertEqual(result["retained_text"], "")
                self.assertEqual(result["removed_text"], "")
                self.assertEqual(result["cut_char_offset"], 0)
                self.assertTrue(result["reason"])

    def test_prefix_is_consumed_as_supplied_and_never_added_by_preview_helper(self):
        input_text = "passage:   already formatted  input\n"
        tokenizer = FakeTokenizer()

        result = token_preview.preview_input(input_text, tokenizer=tokenizer)

        self.assertEqual(tokenizer.calls, [(input_text, False, None)])
        self.assertEqual(result["input_text"], input_text)
        self.assertEqual(result["retained_text"], input_text)
        self.assertFalse(result["truncated"])

    def test_unicode_multilingual_and_whitespace_offsets_slice_original_text(self):
        # Include combining marks, emoji, CJK, CR/LF, tabs, and repeated
        # whitespace around a forced right-truncation boundary.
        words = ["한국어", "🙂", "e\u0301", "中\t文", "line\r\nbreak"]
        payload = "  " + " \t ".join(words * 103) + "  \n"
        input_text = "passage: " + payload
        result = token_preview.preview_input(input_text, tokenizer=FakeTokenizer())

        self.assertTrue(result["truncated"])
        self.assertEqual(result["full_token_count"], len(re.findall(r"\S+", input_text)) + 2)
        self.assertEqual(result["retained_token_count"], 512)
        self.assertEqual(result["retained_text"] + result["removed_text"], input_text)
        self.assertEqual(result["retained_text"], input_text[:result["cut_char_offset"]])
        self.assertEqual(result["removed_text"], input_text[result["cut_char_offset"]:])
        self.assertTrue(result["retained_text"].startswith("passage: "))
        self.assertGreater(result["cut_char_offset"], len("passage: "))
        self.assertLess(result["cut_char_offset"], len(input_text))

    def test_tokenizer_failure_returns_stable_unavailable_shape(self):
        class BrokenTokenizer:
            def encode(self, text, *, truncation=False, max_length=None):
                raise OSError("synthetic offline tokenizer failure")

        result = token_preview.preview_input("passage: synthetic", tokenizer=BrokenTokenizer())

        self.assertFalse(result["available"])
        for field in (
            "model", "revision", "max_tokens", "full_token_count",
            "retained_token_count", "truncated", "input_text",
            "retained_text", "removed_text", "cut_char_offset", "reason",
        ):
            self.assertIn(field, result)
        self.assertEqual(result["input_text"], "passage: synthetic")
        self.assertEqual(result["retained_text"], "")
        self.assertEqual(result["removed_text"], "")
        self.assertTrue(result["reason"])

    def test_pinned_asset_constants_match_approved_repo_revision_and_hashes(self):
        self.assertEqual(token_preview.REPOSITORY, "Qdrant/multilingual-e5-large-onnx")
        self.assertEqual(token_preview.REVISION, "ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b")
        self.assertEqual(token_preview.ASSETS, {
            "tokenizer.json": "f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af",
            "tokenizer_config.json": "f90024142df07163e5e6c5b9a6ad7c8c68b22a9112af11e3db4559a9ff90f737",
            "config.json": "1de8c3be1f344c0eefa4962480a006f8639f416dfafaa95a770e3cf4bceae6a4",
            "special_tokens_map.json": "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
        })

    def test_cached_asset_resolution_is_local_only_and_uses_fixed_allowlist(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {name: Path(tmpdir) / name for name in token_preview.ASSETS}
            for path in paths.values():
                path.write_bytes(b"synthetic")

            def fake_download(*, repo_id, filename, revision, cache_dir, local_files_only):
                calls.append((repo_id, filename, revision, cache_dir, local_files_only))
                return str(paths[filename])

            fake_hub = SimpleNamespace(hf_hub_download=fake_download)
            with patch.dict("sys.modules", {"huggingface_hub": fake_hub}), \
                    patch.object(token_preview, "cache_path", return_value=Path(tmpdir)):
                resolved = token_preview._cached_assets()

        self.assertEqual(set(resolved), set(token_preview.ASSETS))
        self.assertEqual({call[0] for call in calls}, {token_preview.REPOSITORY})
        self.assertEqual({call[2] for call in calls}, {token_preview.REVISION})
        self.assertEqual({call[4] for call in calls}, {True})
        self.assertEqual({call[1] for call in calls}, set(token_preview.ASSETS))

    def test_asset_hash_verification_rejects_mismatched_bytes(self):
        payload = b"synthetic tokenizer bytes"
        good_hash = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tokenizer.json"
            path.write_bytes(payload)
            with patch.object(token_preview, "ASSETS", {"tokenizer.json": good_hash}):
                token_preview._verify_assets({"tokenizer.json": path})
            with patch.object(token_preview, "ASSETS", {"tokenizer.json": "0" * 64}):
                with self.assertRaisesRegex(ValueError, "tokenizer.json"):
                    token_preview._verify_assets({"tokenizer.json": path})

    def test_asset_size_limit_rejects_oversized_file_before_hashing(self):
        # Isolate the configured size guard from the content-hash guard. A
        # sparse file makes this fixture cheap on disk and it is rejected from
        # stat() before hashing or reading the payload.
        filename = "tokenizer.json"
        maximum = 18 * 1024 * 1024
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / filename
            with path.open("wb") as stream:
                stream.truncate(maximum + 1)
            with patch.object(token_preview, "ASSETS", {filename: "0" * 64}), \
                    patch.object(token_preview, "ASSET_MAX_BYTES", {filename: maximum}):
                with self.assertRaisesRegex(ValueError, "size|large|oversiz|크기|용량"):
                    token_preview._verify_assets({filename: path})

    def test_explicit_prepare_hash_checks_only_pinned_files_and_fails_closed(self):
        names = tuple(token_preview.ASSETS)
        payloads = {name: f"synthetic bytes for {name}".encode() for name in names}
        synthetic_hashes = {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in payloads.items()
        }
        limits = {name: 1024 for name in names}

        def run_prepare(*, corrupt_one: bool):
            calls = []
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)

                def fake_download(*, repo_id, filename, revision, cache_dir, local_files_only):
                    calls.append((repo_id, filename, revision, local_files_only))
                    path = root / filename
                    content = payloads[filename]
                    if corrupt_one and filename == names[0]:
                        content += b"corrupt"
                    path.write_bytes(content)
                    return str(path)

                fake_hub = SimpleNamespace(hf_hub_download=fake_download)
                with patch.dict("sys.modules", {"huggingface_hub": fake_hub}), \
                        patch.object(token_preview, "ASSETS", synthetic_hashes), \
                        patch.object(token_preview, "ASSET_MAX_BYTES", limits), \
                        patch.object(token_preview, "_dependencies", return_value=(True, True)), \
                        patch.object(token_preview, "cache_path", return_value=root), \
                        patch.object(token_preview, "_load_tokenizer", return_value=object()) as load, \
                        patch.object(token_preview, "status", return_value={"available": True}):
                    result = token_preview.prepare()
                    return result, calls, load

        failed, failed_calls, failed_load = run_prepare(corrupt_one=True)
        self.assertFalse(failed["available"])
        self.assertTrue(failed["reason"])
        failed_load.assert_not_called()
        self.assertEqual(len(failed_calls), 4)

        succeeded, successful_calls, successful_load = run_prepare(corrupt_one=False)
        self.assertEqual(succeeded, {"available": True})
        successful_load.assert_called_once_with()
        for calls in (failed_calls, successful_calls):
            self.assertTrue(all(call[0] == token_preview.REPOSITORY for call in calls))
            self.assertTrue(all(call[2] == token_preview.REVISION for call in calls))
            self.assertTrue(all(call[3] is False for call in calls))
            self.assertEqual({call[1] for call in calls}, set(names))

    def test_missing_dependency_and_corrupt_cache_degrade_without_downloading(self):
        with patch.object(token_preview, "_dependencies", return_value=(False, False)), \
                patch.object(token_preview, "_cached_assets", side_effect=AssertionError("must not download")):
            missing = token_preview.status()
        self.assertFalse(missing["available"])
        self.assertTrue(missing["reason"])

        with patch.object(token_preview, "_dependencies", return_value=(True, True)), \
                patch.object(token_preview, "_cached_assets", side_effect=ValueError("synthetic corrupt cache")):
            corrupt = token_preview.status()
        self.assertFalse(corrupt["available"])
        self.assertTrue(corrupt["reason"])

    def test_prepare_route_rejects_caller_controlled_asset_and_document_fields(self):
        # Route-level guard: preparation takes no body, document text, URL,
        # repository, revision, or filename from the caller.
        for payload in (
            {"input_text": "synthetic passage"},
            {"text": "synthetic passage"},
            {"repo_id": "attacker/repository"},
            {"revision": "main"},
            {"url": "https://example.invalid/tokenizer.json"},
            {"filename": "model.onnx"},
        ):
            with self.subTest(payload=payload), \
                    patch.object(token_preview, "prepare", side_effect=AssertionError("must reject before prepare")):
                with self.assertRaises((ValueError, TypeError, workbench_server.ElasticsearchError)):
                    workbench_server.WorkbenchHandler._token_preview_prepare(payload)

    def test_status_is_cache_only_and_preview_never_retries_prepare(self):
        with patch.object(token_preview, "_dependencies", return_value=(True, True)), \
                patch.object(token_preview, "_cached_assets", side_effect=OSError("offline cache miss")) as cached, \
                patch.object(token_preview, "prepare", side_effect=AssertionError("status must not prepare")):
            result = token_preview.status()
        cached.assert_called_once_with()
        self.assertFalse(result["available"])
        self.assertTrue(result["reason"])

        with patch.object(token_preview, "_load_tokenizer", side_effect=OSError("offline")), \
                patch.object(token_preview, "prepare", side_effect=AssertionError("preview must not prepare")):
            result = token_preview.preview_input("passage: synthetic")
        self.assertFalse(result["available"])
        self.assertTrue(result["reason"])

    def test_shared_tokenizer_adapter_does_not_race_between_full_and_truncated_encodes(self):
        """Two threads must not overwrite tokenizer truncation while encoding."""
        from es_rag_tuner.token_preview import _TokenizerAdapter

        start = threading.Barrier(3)

        class MutableTokenizer:
            def __init__(self):
                self.max_length = None
                self.active_encodes = 0
                self.max_active_encodes = 0
                self.state_lock = threading.Lock()

            def enable_truncation(self, *, max_length, direction):
                self.max_length = max_length

            def no_truncation(self):
                self.max_length = None

            def encode(self, text, *, add_special_tokens=True):
                with self.state_lock:
                    self.active_encodes += 1
                    self.max_active_encodes = max(self.max_active_encodes, self.active_encodes)
                    max_length = self.max_length
                try:
                    time.sleep(0.05)
                    count = 600 if max_length is None else max_length
                    return FakeEncoding(list(range(count)), [(0, 1)] * count)
                finally:
                    with self.state_lock:
                        self.active_encodes -= 1

        mutable = MutableTokenizer()
        adapter = _TokenizerAdapter(mutable)
        outputs = {}

        def call(text, truncation):
            start.wait(timeout=5)
            outputs[text] = adapter.encode(
                text, truncation=truncation,
                max_length=512 if truncation else None,
            )

        full_thread = threading.Thread(target=call, args=("full", False))
        truncated_thread = threading.Thread(target=call, args=("long", True))
        full_thread.start()
        truncated_thread.start()
        start.wait(timeout=5)
        full_thread.join(timeout=5)
        truncated_thread.join(timeout=5)

        self.assertFalse(full_thread.is_alive())
        self.assertFalse(truncated_thread.is_alive())
        self.assertEqual(len(outputs["full"].ids), 600)
        self.assertEqual(len(outputs["long"].ids), 512)
        self.assertEqual(mutable.max_active_encodes, 1)

    def test_http_status_and_preview_routes_are_read_only_and_preserve_input(self):
        port = _free_port()
        httpd = ThreadingHTTPServer(("127.0.0.1", port), workbench_server.WorkbenchHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        client = install_auth_fixture(self, f"http://127.0.0.1:{port}")
        input_text = "passage: <script>안녕 🙂</script>  exact\ntext"
        fake_preview = {
            "available": True, "model": token_preview.MODEL,
            "revision": token_preview.REVISION, "max_tokens": 512,
            "full_token_count": 8, "retained_token_count": 8,
            "truncated": False, "input_text": input_text,
            "retained_text": input_text, "removed_text": "",
            "cut_char_offset": len(input_text), "reason": None,
        }

        def post(path: str, payload: dict[str, object]) -> dict[str, object]:
            status, result = client.post(path, payload)
            self.assertEqual(status, 200, result)
            return result

        try:
            with patch.object(token_preview, "preview_input", return_value=fake_preview) as preview, \
                    patch.object(token_preview, "status", return_value={"available": False, "reason": "offline"}) as status, \
                    patch.object(token_preview, "prepare", side_effect=AssertionError("implicit prepare")), \
                    patch("es_rag_tuner.embeddings._model", side_effect=AssertionError("model must not load")):
                result = post("/api/token-preview", {"input_text": input_text})
                status_code, status_result = client.request("/api/token-preview/status")
                self.assertEqual(status_code, 200, status_result)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        preview.assert_called_once_with(input_text)
        status.assert_called_once_with()
        self.assertEqual(result, fake_preview)
        self.assertEqual(status_result, {"available": False, "reason": "offline"})

    def test_document_and_preview_http_flow_performs_only_one_document_read(self):
        source = {"rag_chunk_text": " <b>synthetic</b>  passage "}
        original_source = dict(source)
        seen_es = []
        input_text = "passage: <b>synthetic</b>  passage"
        preview_result = {
            "available": True, "model": token_preview.MODEL,
            "revision": token_preview.REVISION, "max_tokens": 512,
            "full_token_count": 6, "retained_token_count": 6,
            "truncated": False, "input_text": input_text,
            "retained_text": input_text, "removed_text": "",
            "cut_char_offset": len(input_text), "reason": None,
        }
        port = _free_port()
        httpd = ThreadingHTTPServer(("127.0.0.1", port), workbench_server.WorkbenchHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        client = install_auth_fixture(self, f"http://127.0.0.1:{port}")

        def post(path, payload):
            status, result = client.post(path, payload)
            self.assertEqual(status, 200, result)
            return result

        def fake_es(connection, method, path, body=None):
            seen_es.append((method, path, body))
            return {"_index": "synthetic", "_id": "doc-1", "found": True,
                    "_source": dict(source)}

        try:
            with patch("es_rag_tuner.server.request", side_effect=fake_es), \
                    patch("es_rag_tuner.embeddings._model", side_effect=AssertionError("model must not load")), \
                    patch.object(token_preview, "status", return_value={"available": True}), \
                    patch.object(token_preview, "preview_input", return_value=preview_result) as preview:
                document = post("/api/document", {
                    "connection": {"url": "http://127.0.0.1:9200"},
                    "index": "synthetic", "id": "doc-1",
                })
                result = post("/api/token-preview", {"input_text": document["embedding_input"]["text"]})
                status, token_status = client.request("/api/token-preview/status")
                self.assertEqual(status, 200, token_status)
                self.assertTrue(token_status["available"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.assertEqual(seen_es, [("GET", "synthetic/_doc/doc-1", None)])
        self.assertEqual(document["embedding_input"]["text"], input_text)
        self.assertEqual(source, original_source)
        preview.assert_called_once_with(input_text)
        self.assertEqual(result, preview_result)

    def test_ui_uses_text_rendering_and_has_narrow_layout_rules(self):
        root = Path(workbench_server.__file__).parent / "web"
        app_js = (root / "app.js").read_text(encoding="utf-8")
        index_html = (root / "index.html").read_text(encoding="utf-8")
        style_css = (root / "style.css").read_text(encoding="utf-8")

        self.assertIn('$("#token-retained-text").textContent = preview.retained_text', app_js)
        self.assertIn('$("#token-removed-text").textContent = preview.removed_text', app_js)
        self.assertIn('id="token-retained-text"', index_html)
        self.assertIn('id="token-removed-text"', index_html)
        self.assertRegex(style_css, r"@media\s*\(max-width\s*:\s*560px\)[^{]*\{[^}]*\.token-preview-parts\s*\{[^}]*grid-template-columns:\s*1fr")
        # Existing document content rendering and preview requests use the
        # server-provided string; this path must not rewrite the source input.
        self.assertIn('refreshTokenPreview(state.currentEmbeddingInput?.text ?? null)', app_js)

    @unittest.skipUnless(
        os.environ.get("ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE"),
        "requires an isolated fixture containing only the four pinned tokenizer/config assets",
    )
    def test_real_tokenizer_matches_fastembed_090_loader_without_model_construction(self):
        """Opt-in parity check; never downloads or constructs TextEmbedding."""
        fixture_root = Path(os.environ["ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE"]).resolve()
        expected_files = set(token_preview.ASSETS)
        self.assertEqual({path.name for path in fixture_root.iterdir()}, expected_files)
        fixture_paths = {name: fixture_root / name for name in expected_files}
        token_preview._verify_assets(fixture_paths)

        from fastembed import __version__ as fastembed_version
        from fastembed.common.preprocessor_utils import load_tokenizer

        self.assertEqual(fastembed_version, "0.9.0")
        fastembed_tokenizer, _special_token_to_id = load_tokenizer(fixture_root)

        # Force the production tokenizer seam to read the same temporary
        # fixture. No Hugging Face cache, model constructor, or ONNX path is
        # involved. Restore the module singleton after the assertion.
        previous = token_preview._TOKENIZER
        try:
            with patch.object(token_preview, "_TOKENIZER", None), \
                    patch.object(token_preview, "_cached_assets", return_value=fixture_paths):
                preview_tokenizer = token_preview._load_tokenizer()
                preview_tokenizer.enable_truncation(max_length=512, direction="right")
                fastembed_retained = fastembed_tokenizer.encode(
                    "passage: " + "token " * 520, add_special_tokens=True
                )
                preview_retained = preview_tokenizer.encode(
                    "passage: " + "token " * 520, add_special_tokens=True
                )
                self.assertEqual(preview_retained.ids, fastembed_retained.ids)
                self.assertEqual(len(preview_retained.ids), 512)

                preview_tokenizer.no_truncation()
                fastembed_tokenizer.no_truncation()
                full_text = "passage: " + "token " * 520
                self.assertEqual(
                    len(preview_tokenizer.encode(full_text, add_special_tokens=True).ids),
                    len(fastembed_tokenizer.encode(full_text, add_special_tokens=True).ids),
                )
        finally:
            token_preview._TOKENIZER = previous


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
