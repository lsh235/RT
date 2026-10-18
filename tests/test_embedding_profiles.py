from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from es_rag_tuner import embeddings
from es_rag_tuner.es_client import ElasticsearchError


class EmbeddingProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._models = embeddings._MODELS.copy()
        self._errors = embeddings._LOAD_ERRORS.copy()
        embeddings._MODELS.clear()
        embeddings._LOAD_ERRORS.clear()

    def tearDown(self) -> None:
        embeddings._MODELS.clear()
        embeddings._MODELS.update(self._models)
        embeddings._LOAD_ERRORS.clear()
        embeddings._LOAD_ERRORS.update(self._errors)

    def test_fixed_profiles_and_default_compatibility(self) -> None:
        self.assertEqual(embeddings.MODEL_NAME, "intfloat/multilingual-e5-large")
        self.assertEqual(embeddings.MODEL_DIMENSIONS, 1024)
        specs = {profile["profile_id"]: profile for profile in embeddings.list_profiles()}
        e5 = specs["e5-multilingual-large"]
        mini = specs["paraphrase-multilingual-minilm-l12"]
        self.assertEqual((e5["model_name"], e5["dimensions"], e5["context_tokens"]), (embeddings.MODEL_NAME, 1024, 512))
        self.assertEqual((mini["model_name"], mini["dimensions"], mini["context_tokens"]),
                         ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384, 128))
        self.assertEqual(embeddings.format_embedding_input(" hello ", "query"), "query: hello")
        self.assertEqual(embeddings.format_embedding_input(" hello ", "passage"), "passage: hello")
        self.assertEqual(embeddings.format_embedding_input(" hello ", "query", mini["profile_id"]), "hello")
        with self.assertRaisesRegex(ValueError, "Unknown embedding profile"):
            embeddings.profile_spec("e5")
        with self.assertRaisesRegex(ValueError, "Unknown embedding profile"):
            embeddings.embed_texts([], "query", profile_id="")

    def test_recipe_binds_fastembed_recipe_and_cached_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"ES_RAG_MODEL_CACHE": tmp}):
                profile = embeddings.profile_spec()
                repo_dir = Path(tmp) / "models--Qdrant--multilingual-e5-large-onnx" / "onnx_snapshots" / "0123abcd"
                repo_dir.mkdir(parents=True)
                (repo_dir / "model.onnx").write_bytes(b"fixture")
                standard = repo_dir.parent.parent / "snapshots" / "0123abcd"
                standard.mkdir(parents=True)
                (standard / "tokenizer.json").write_text("{}", encoding="utf-8")
                (standard / "config.json").write_text("{}", encoding="utf-8")
                recipe = embeddings.profile_recipe()
                self.assertEqual(recipe["profile_id"], "e5-multilingual-large")
                self.assertEqual(recipe["source_revision"], "0123abcd")
                self.assertEqual(recipe["fastembed_version"], profile["fastembed_version"])
                self.assertEqual(recipe["similarity"], "cosine")
                self.assertTrue(recipe["normalized"])
                self.assertEqual(recipe["dimensions"], 1024)
                self.assertEqual(recipe["query_prefix"], "query: ")
                self.assertRegex(recipe["recipe_fingerprint"], r"^[0-9a-f]{64}$")

    def test_minilm_huggingface_snapshot_cache_resolves_revision(self) -> None:
        profile_id = "paraphrase-multilingual-minilm-l12"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"ES_RAG_MODEL_CACHE": tmp}):
                repo_dir = Path(tmp) / "models--Qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q" / "snapshots" / "faf4aa42"
                repo_dir.mkdir(parents=True)
                (repo_dir / "model_optimized.onnx").write_bytes(b"fixture")
                (repo_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
                (repo_dir / "config.json").write_text("{}", encoding="utf-8")
                recipe = embeddings.profile_recipe(profile_id)
                self.assertEqual(recipe["source_revision"], "faf4aa42")
                self.assertEqual(recipe["dimensions"], 384)
                self.assertEqual(embeddings.cached_file_path(profile_id, "tokenizer.json"), repo_dir / "tokenizer.json")

    def test_profile_tokenizer_disables_model_truncation(self) -> None:
        class FakeTokenizer:
            def __init__(self):
                self.truncation_disabled = False

            def no_truncation(self):
                self.truncation_disabled = True

        fake = FakeTokenizer()
        mini_id = "paraphrase-multilingual-minilm-l12"
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"ES_RAG_MODEL_CACHE": tmp}):
                repo_dir = Path(tmp) / "models--Qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q" / "snapshots" / "rev-42"
                repo_dir.mkdir(parents=True)
                for name in ("model_optimized.onnx", "tokenizer.json", "config.json"):
                    (repo_dir / name).write_bytes(b"fixture")
                fake_module = types.SimpleNamespace(Tokenizer=types.SimpleNamespace(from_file=mock.Mock(return_value=fake)))
                with mock.patch.dict(sys.modules, {"tokenizers": fake_module}):
                    tokenizer = __import__("es_rag_tuner.knowledge", fromlist=["_profile_tokenizer"])._profile_tokenizer(mini_id)
        self.assertIs(tokenizer, fake)
        self.assertTrue(fake.truncation_disabled)

    def test_recipe_fingerprint_changes_for_model_prefix_revision_and_runtime(self) -> None:
        profile_id = embeddings.DEFAULT_PROFILE_ID
        original = embeddings._PROFILES[profile_id].copy()
        with mock.patch.object(embeddings, "_cached_artifact", return_value=(False, None)), \
             mock.patch.object(embeddings, "_fastembed_version", return_value="0.9.0"):
            base = embeddings.profile_recipe(profile_id)
            self.assertIsNone(base["source_revision"])
            self.assertEqual(base["recipe_fingerprint"], embeddings.profile_recipe(profile_id)["recipe_fingerprint"])

            with mock.patch.dict(embeddings._PROFILES, {profile_id: {**original, "model_name": "different/model"}}):
                model_changed = embeddings.profile_recipe(profile_id)
            with mock.patch.dict(embeddings._PROFILES, {profile_id: {**original, "query_prefix": "search: "}}):
                prefix_changed = embeddings.profile_recipe(profile_id)
            with mock.patch.object(embeddings, "_cached_artifact", return_value=(True, "revision-2")):
                revision_changed = embeddings.profile_recipe(profile_id)

        with mock.patch.object(embeddings, "_fastembed_version", return_value="0.9.1"):
            runtime_changed = embeddings.profile_recipe(profile_id)
        fingerprints = {
            base["recipe_fingerprint"],
            model_changed["recipe_fingerprint"],
            prefix_changed["recipe_fingerprint"],
            revision_changed["recipe_fingerprint"],
            runtime_changed["recipe_fingerprint"],
        }
        self.assertEqual(len(fingerprints), 5)
        self.assertEqual(revision_changed["source_revision"], "revision-2")

    def test_fake_runtime_uses_profile_dimensions_and_prefixes(self) -> None:
        class FakeModel:
            def __init__(self, dimensions: int) -> None:
                self.dimensions = dimensions
                self.inputs: list[str] = []

            def embed(self, inputs: list[str], batch_size: int):
                self.inputs.extend(inputs)
                return [[3.0] + [0.0] * (self.dimensions - 1) for _ in inputs]

        mini_id = "paraphrase-multilingual-minilm-l12"
        fake = FakeModel(384)
        with mock.patch.object(embeddings, "_model", return_value=fake):
            vectors = embeddings.embed_texts(["  hello "], "query", profile_id=mini_id)
        self.assertEqual(fake.inputs, ["hello"])
        self.assertEqual(len(vectors[0]), 384)
        self.assertEqual(vectors[0][0], 1.0)

    def test_runtime_status_distinguishes_missing_dependency_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"ES_RAG_MODEL_CACHE": tmp}):
                with mock.patch.object(embeddings.importlib.util, "find_spec", return_value=None):
                    status = embeddings.runtime_status()
                self.assertEqual(status["status"], "dependency_missing")
                with mock.patch.object(embeddings.importlib.util, "find_spec", return_value=object()):
                    status = embeddings.runtime_status()
                self.assertEqual(status["status"], "model_not_cached")
                self.assertNotIn("cache_path", status)
                repo_dir = Path(tmp) / "models--Qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q" / "snapshots" / "rev-42"
                repo_dir.mkdir(parents=True)
                (repo_dir / "model_optimized.onnx").write_bytes(b"fixture")
                (repo_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
                (repo_dir / "config.json").write_text("{}", encoding="utf-8")
                with mock.patch.object(embeddings.importlib.util, "find_spec", return_value=object()):
                    status = embeddings.runtime_status("paraphrase-multilingual-minilm-l12")
                self.assertEqual(status["status"], "cached")
                self.assertEqual(status["source_revision"], "rev-42")
                (repo_dir / "tokenizer.json").unlink()
                with mock.patch.object(embeddings.importlib.util, "find_spec", return_value=object()):
                    status = embeddings.runtime_status("paraphrase-multilingual-minilm-l12")
                self.assertEqual(status["status"], "model_not_cached")

    def test_loading_failure_status_is_sanitized(self) -> None:
        embeddings._LOAD_ERRORS[embeddings.DEFAULT_PROFILE_ID] = True
        with mock.patch.object(embeddings.importlib.util, "find_spec", return_value=object()):
            status = embeddings.runtime_status()
        self.assertEqual(status["status"], "loading_failure")
        self.assertNotIn("detail", status)
        self.assertNotIn("cache_path", status)

    def test_local_load_failure_does_not_expose_exception_details(self) -> None:
        class FailingEmbedding:
            def __init__(self, **kwargs: object) -> None:
                raise RuntimeError("/secret/cache token=private")

        fake_module = types.SimpleNamespace(TextEmbedding=FailingEmbedding)
        with mock.patch.object(embeddings.importlib.util, "find_spec", return_value=object()), \
             mock.patch.dict("sys.modules", {"fastembed": fake_module}), \
             mock.patch.object(embeddings, "_model_cache_root", return_value=Path(tempfile.gettempdir())):
            with self.assertRaises(ElasticsearchError) as caught:
                embeddings._model(embeddings.DEFAULT_PROFILE_ID, local_files_only=True)
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(embeddings.runtime_status()["status"], "loading_failure")


if __name__ == "__main__":
    unittest.main()
