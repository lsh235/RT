import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from es_rag_tuner import concepts


class ExperimentExportFingerprint(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "state.sqlite3"
        self.path_patch = patch.object(concepts, "_db_path", return_value=self.database)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.temp.cleanup)
        self.concept_id = "r10-fingerprint-concept"
        concepts.save_concept({
            "id": self.concept_id,
            "name": "Synthetic fingerprint fixture",
            "description": "Fixture concept",
            "corpus": {"index": "synthetic-index", "text_fields": ["body"]},
            "queries": [{"id": "q1", "query": "synthetic query", "split": "train"}],
            "settings": {"size": 3, "candidate_size": 8, "concept_weight": 1.0, "related_weight": 1.0},
            "filters": [],
        })
        self.run_id = "r10-fingerprint-run"
        self.stored_body = {
            "query": "synthetic query",
            "query_id": "q1",
            "settings": {"size": 3, "concept_weight": 1.0},
            "tuned": {"ndcg_at_k": 0.5, "judged_coverage_at_k": 0.75},
            "input_snapshot": {
                "concept": {"id": self.concept_id, "queries": [{"id": "q1", "query": "synthetic query"}], "api_key": "credential-key-marker", "authorization": "Bearer credential-token-marker"},
                "judgments": [{"query_id": "q1", "document_index": "synthetic-index", "document_id": "doc-1", "rating": 2, "reason": "password=credential-password-marker"}],
                "source_body": "source-body-marker",
            },
            "output_snapshot": {
                "train": {"baseline": {"q1": [{"index": "synthetic-index", "id": "doc-1", "rank": 1, "source": {"body": "raw-source-body-marker"}, "source_sha256": "synthetic-hash"}]}}
            },
            "reproducibility": {"settings_fingerprint": "synthetic-settings-fingerprint"},
        }
        concepts._store_run(self.concept_id, "tune", self.stored_body, run_id=self.run_id)

    def _export_at(self, timestamp):
        with patch.object(concepts, "_now", return_value=timestamp):
            return concepts.export_run(self.concept_id, self.run_id)

    def test_same_saved_run_fingerprint_ignores_export_timestamp(self):
        first = self._export_at("2026-10-19T01:00:00+00:00")
        second = self._export_at("2026-10-19T02:00:00+00:00")
        self.assertNotEqual(first["exported_at"], second["exported_at"])
        self.assertEqual(first["content_fingerprint"], second["content_fingerprint"])
        self.assertRegex(first["content_fingerprint"], r"^[0-9a-f]{64}$")
        expected = concepts._json_hash({key: value for key, value in first.items() if key not in {"exported_at", "content_fingerprint"}})
        self.assertEqual(first["content_fingerprint"], expected)

    def test_substantive_exported_run_change_changes_fingerprint(self):
        original = self._export_at("2026-10-19T03:00:00+00:00")
        changed_body = dict(self.stored_body)
        changed_body["tuned"] = {**self.stored_body["tuned"], "ndcg_at_k": 0.625}
        with concepts._connect_db() as db:
            db.execute("UPDATE runs SET body=? WHERE id=? AND concept_id=?", (json.dumps(changed_body), self.run_id, self.concept_id))
        changed = self._export_at("2026-10-19T03:00:00+00:00")
        self.assertNotEqual(original["content_fingerprint"], changed["content_fingerprint"])
        self.assertEqual(changed["run"]["tuned"]["ndcg_at_k"], 0.625)

    def test_fingerprint_covers_only_privacy_filtered_export(self):
        artifact = self._export_at("2026-10-19T04:00:00+00:00")
        serialized = json.dumps(artifact, ensure_ascii=False)
        for marker in (
            "credential-key-marker", "credential-token-marker", "credential-password-marker",
            "source-body-marker", "raw-source-body-marker",
        ):
            self.assertNotIn(marker, serialized)
        self.assertNotIn("api_key", artifact["run"]["input_snapshot"]["concept"])
        self.assertNotIn("source_body", artifact["run"]["input_snapshot"])
        ranked = artifact["run"]["output_snapshot"]["train"]["baseline"]["q1"][0]
        self.assertNotIn("source", ranked)
        self.assertEqual(ranked["source_sha256"], "synthetic-hash")


if __name__ == "__main__":
    unittest.main()
