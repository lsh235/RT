"""Synthetic acceptance tests for bounded concept tuning.

All Elasticsearch calls, clock values, and persistence boundaries are local fakes.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from es_rag_tuner import concepts, server
from es_rag_tuner.es_client import Connection, ElasticsearchError


class FakeClock:
    def __init__(self, step: float = 0.0):
        self.value = 0.0
        self.step = step

    def __call__(self):
        value = self.value
        self.value += self.step
        return value


def fixture_concept(validation: bool = True):
    queries = [{"id": "train-q", "query": "train query", "split": "train"}]
    if validation:
        queries.append({"id": "validation-q", "query": "validation query", "split": "validation"})
    return {
        "id": "bounded-tune-fixture", "name": "Synthetic bounded tune",
        "corpus": {"index": "synthetic-index", "text_fields": ["body"]},
        "queries": queries,
        "settings": {"size": 2, "candidate_size": 5, "concept_weight": 1.0, "related_weight": 1.0},
        "filters": [],
    }


def fixture_judgments(validation=True, stale_test=False):
    rows = [
        {"concept_id": "bounded-tune-fixture", "query_id": "train-q", "document_index": "synthetic-index", "document_id": "train-rel", "rating": 3, "pinned": False, "reason": "synthetic", "stale": False, "query_fingerprint": "train-fp"},
        {"concept_id": "bounded-tune-fixture", "query_id": "train-q", "document_index": "synthetic-index", "document_id": "train-unjudged", "rating": None, "pinned": False, "reason": "", "stale": False, "query_fingerprint": "train-fp"},
    ]
    if validation:
        rows += [
            {"concept_id": "bounded-tune-fixture", "query_id": "validation-q", "document_index": "synthetic-index", "document_id": "validation-rel", "rating": 2, "pinned": False, "reason": "synthetic", "stale": False, "query_fingerprint": "val-fp"},
            {"concept_id": "bounded-tune-fixture", "query_id": "validation-q", "document_index": "synthetic-index", "document_id": "known-unjudged", "rating": None, "pinned": False, "reason": "", "stale": False, "query_fingerprint": "val-fp"},
            {"concept_id": "bounded-tune-fixture", "query_id": "validation-q", "document_index": "synthetic-index", "document_id": "stale-target", "rating": 3, "pinned": False, "reason": "stale", "stale": True, "query_fingerprint": "old"},
        ]
    if stale_test:
        rows.append({"concept_id": "bounded-tune-fixture", "query_id": "test-q", "document_index": "synthetic-index", "document_id": "test-only-relevant", "rating": 3, "pinned": False, "reason": "must not leak", "stale": True, "query_fingerprint": "old"})
    return rows


class BoundedTuneAcceptance(unittest.TestCase):
    def setup_mocks(self, validation=True, stale_test=False, *, failing_validation=False, flat=False, baseline_best=False):
        judgments = fixture_judgments(validation, stale_test)
        calls = []

        def fake_hits(connection, index, query, size, concept, *, expanded=True, filters=None, timeout=None):
            settings = concept["settings"]
            qid = "train-q" if query == "train query" else "validation-q"
            calls.append((qid, settings["concept_weight"], settings["related_weight"], timeout))
            if failing_validation and qid == "validation-q":
                raise ElasticsearchError("synthetic validation unavailable")
            if baseline_best:
                doc = ("train-rel" if qid == "train-q" else "validation-rel") if settings["concept_weight"] == 1.0 else "other-doc"
                return {"hits": [{"_index": index, "_id": doc, "rank": 1, "source_sha256": "synthetic"}], "total": 1}
            if flat:
                return {"hits": [{"_index": index, "_id": "train-rel" if qid == "train-q" else "validation-rel", "rank": 1, "source_sha256": "synthetic"}], "total": 1}
            if settings["concept_weight"] == 0.0:
                doc = "train-rel" if qid == "train-q" else "validation-rel"
                return {"hits": [{"_index": index, "_id": doc, "rank": 1, "source_sha256": "synthetic"}, {"_index": index, "_id": "known-unjudged", "rank": 2, "source_sha256": "synthetic"}], "total": 2}
            return {"hits": [{"_index": index, "_id": "other-doc", "rank": 1, "source_sha256": "synthetic"}, {"_index": index, "_id": "known-unjudged", "rank": 2, "source_sha256": "synthetic"}], "total": 2}

        context = (
            patch.object(concepts, "_validate_search_fields", return_value={"fields": []}),
            patch.object(concepts, "_judgments", return_value=judgments),
            patch.object(concepts, "_hits", side_effect=fake_hits),
            patch.object(concepts, "_index_identity", return_value=({"available": True, "uuids": [{"index": "synthetic-index", "uuid": "uuid-1"}]}, None)),
            patch.object(concepts, "_store_run", return_value="synthetic-run"),
        )
        return context, calls

    def run_tune(self, **kwargs):
        validation = kwargs.pop("validation", True)
        ctx, calls = self.setup_mocks(validation, kwargs.pop("stale_test", False), failing_validation=kwargs.pop("failing_validation", False), flat=kwargs.pop("flat", False), baseline_best=kwargs.pop("baseline_best", False))
        with ctx[0], ctx[1], ctx[2], ctx[3], ctx[4]:
            result = concepts.tune(None, fixture_concept(validation), **kwargs)
        return result, calls

    def test_candidate_and_time_limits_and_explicit_stop_state(self):
        result, calls = self.run_tune(max_candidates=3, time_budget_seconds=600)
        self.assertEqual(len(result["candidate_trace"]), 3)
        self.assertEqual(result["tuning_budget"]["max_candidates"], 3)
        self.assertEqual(result["tuning_budget"]["stop_reason"], "candidate_budget")
        self.assertLessEqual(len(calls), 6)
        for bad in (0, 31, True, 1.5):
            context, _ = self.setup_mocks()
            with context[0], context[1], context[2], context[3], context[4]:
                with self.assertRaisesRegex(ElasticsearchError, "max_candidates"):
                    concepts.tune(None, fixture_concept(), max_candidates=bad)
        context, _ = self.setup_mocks()
        with context[0], context[1], context[2], context[3], context[4]:
            with self.assertRaisesRegex(ElasticsearchError, "time_budget_seconds"):
                concepts.tune(None, fixture_concept(), time_budget_seconds=601)

    def test_service_rejects_invalid_budget_before_connection_and_defaults_are_bounded(self):
        with patch.object(server.WorkbenchHandler, "_connection") as connection:
            with self.assertRaisesRegex(ElasticsearchError, "max_candidates"):
                server.WorkbenchHandler._concept_tune(object(), {"max_candidates": 31})
            connection.assert_not_called()
        result, _ = self.run_tune()
        self.assertEqual(result["tuning_budget"]["max_candidates"], 30)
        self.assertEqual(result["tuning_budget"]["time_budget_seconds"], 600)
        self.assertLessEqual(len(result["candidate_trace"]), 30)

    def test_mapping_and_uuid_helpers_forward_finite_request_timeouts(self):
        connection = Connection(url="http://127.0.0.1:9200")
        with patch.object(concepts, "request", return_value={"synthetic-index": {"mappings": {"properties": {"body": {"type": "text"}}}}}) as request_mock:
            concepts.corpus_schema(connection, "synthetic-index", timeout=0.75)
            self.assertEqual(request_mock.call_args.kwargs["timeout"], 0.75)
        with patch.object(concepts, "request", return_value={"synthetic-index": {"settings": {"index": {"uuid": "uuid-1"}}}}) as request_mock:
            concepts._index_identity(connection, "synthetic-index", timeout=0.5)
            self.assertEqual(request_mock.call_args.kwargs["timeout"], 0.5)

    def test_preflight_budget_exhaustion_reports_stop_without_search(self):
        context, _ = self.setup_mocks()
        with context[0] as preflight, context[1], context[2] as search, context[3], context[4]:
            with self.assertRaisesRegex(ElasticsearchError, "stop_reason=time_budget"):
                concepts.tune(None, fixture_concept(), time_budget_seconds=1, _clock=FakeClock(step=1.0))
            preflight.assert_not_called()
            search.assert_not_called()

    def test_mapping_and_index_identity_calls_use_remaining_timeout_and_mapping_is_reused(self):
        context, _ = self.setup_mocks()
        with context[0] as preflight, context[1], context[2], context[3] as identity, context[4]:
            result = concepts.tune(None, fixture_concept(), max_candidates=1, time_budget_seconds=3)
        preflight.assert_called_once()
        self.assertGreater(preflight.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(preflight.call_args.kwargs["timeout"], 3)
        identity.assert_called_once()
        self.assertGreater(identity.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(identity.call_args.kwargs["timeout"], 3)
        self.assertIn("mapping_fingerprint", result["reproducibility"])

    def test_exact_validation_tie_retains_baseline(self):
        result, _ = self.run_tune(max_candidates=5, flat=True)
        self.assertEqual(result["selection"], {"selected_candidate_id": "baseline", "reason": "baseline_retained_tie"})

    def test_worse_validation_keeps_baseline_with_exact_reason(self):
        result, _ = self.run_tune(max_candidates=4, baseline_best=True)
        self.assertEqual(result["selection"], {"selected_candidate_id": "baseline", "reason": "no_candidate_improved"})

    def test_diagnostics_mark_new_misses_recovered_targets_and_rating(self):
        qmap = {"validation-q": {"id": "validation-q", "query": "query words", "split": "validation"}}
        grades = [
            {"query_id": "validation-q", "document_index": "index-a", "document_id": "was-found", "rating": 3, "stale": False},
            {"query_id": "validation-q", "document_index": "index-b", "document_id": "was-missed", "rating": 1, "stale": False},
        ]
        before = {"queries": [{"query_id": "validation-q", "ndcg_at_k": 1.0, "judged_coverage_at_k": 1.0, "recall_of_judged_relevant_at_k": 0.5}]}
        after = {"queries": [{"query_id": "validation-q", "ndcg_at_k": 0.0, "judged_coverage_at_k": 1.0, "recall_of_judged_relevant_at_k": 0.5}]}
        diagnostics = concepts._validation_diagnostics(before, after, grades, qmap,
            {"validation-q": [concepts._metric_document_key("index-a", "was-found")]},
            {"validation-q": [concepts._metric_document_key("index-b", "was-missed")]}, 1)
        row = diagnostics[0]
        self.assertEqual(row["missed_relevant_added"], [{"document_index": "index-a", "document_id": "was-found", "rating": 3}])
        self.assertEqual(row["missed_relevant_fixed"], [{"document_index": "index-b", "document_id": "was-missed", "rating": 1}])
        self.assertEqual(row["metric_deltas"]["ndcg_at_k"], -1.0)

    def test_fake_clock_stops_candidate_loop_at_time_budget(self):
        clock = FakeClock(step=0.10)
        result, calls = self.run_tune(max_candidates=30, time_budget_seconds=1, _clock=clock)
        self.assertEqual(result["tuning_budget"]["stop_reason"], "time_budget")
        self.assertLess(result["tuning_budget"]["candidates_evaluated"], 30)
        self.assertLess(len(calls), 30)
        self.assertTrue(all(timeout is not None and 0 < timeout <= 1 for _, _, _, timeout in calls))
        self.assertTrue(any(item["evaluation_status"] == "not_evaluated_time_budget" for item in result["candidate_trace"]))
        self.assertEqual(result["tuning_budget"]["candidates_evaluated"], sum(row["train_metrics"] is not None for row in result["candidate_trace"]))
        partial = next(row for row in result["candidate_trace"] if row["evaluation_status"] == "not_evaluated_time_budget")
        self.assertIsNotNone(partial["train_metrics"])
        self.assertIsNone(partial["validation_metrics"])

    def test_generation_is_deterministic_and_test_only_stale_judgment_cannot_leak(self):
        baseline, calls_a = self.run_tune(max_candidates=5, validation=True)
        adversarial, calls_b = self.run_tune(max_candidates=5, validation=True, stale_test=True)
        sig = lambda result: [(row["candidate_id"], row["settings"], row["train_metrics"], row["validation_metrics"]) for row in result["candidate_trace"]]
        self.assertEqual(sig(baseline), sig(adversarial))
        self.assertEqual(baseline["selection"], adversarial["selection"])
        self.assertEqual([row["candidate_id"] for row in baseline["candidate_trace"]], ["baseline", "candidate-001", "candidate-002", "candidate-003", "candidate-004"])
        self.assertTrue(all("evaluation_status" in row and "status" not in row for row in baseline["candidate_trace"]))
        self.assertEqual(set(baseline["selection"]["reason"] for _ in [0]), {"candidate_selected"})
        self.assertTrue(all(qid in {"train-q", "validation-q"} for qid, _, _, _ in calls_a + calls_b))
        self.assertEqual(calls_a, calls_b)

    def test_validation_selects_candidate_and_diagnostics_are_known_relevant_only(self):
        result, _ = self.run_tune(max_candidates=5)
        self.assertNotEqual(result["selection"]["selected_candidate_id"], "baseline")
        self.assertEqual(result["selection"]["reason"], "candidate_selected")
        self.assertIn(result["selection"]["reason"], {"candidate_selected", "no_candidate_improved", "baseline_retained_tie", "validation_unavailable", "validation_failed"})
        self.assertEqual(result["settings"], next(row["settings"] for row in result["candidate_trace"] if row["candidate_id"] == result["selection"]["selected_candidate_id"]))
        diag = result["validation_diagnostics"]
        self.assertIsInstance(diag, list)
        row = next(item for item in diag if item["query_id"] == "validation-q")
        self.assertEqual(row["query"], "validation query")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["metric_deltas"]["ndcg_at_k"], 1.0)
        target = {"document_index": "synthetic-index", "document_id": "validation-rel", "rating": 2}
        self.assertEqual(row["baseline_missed_known_relevant"], [target])
        self.assertEqual(row["selected_missed_known_relevant"], [])
        self.assertEqual(row["missed_relevant_added"], [])
        self.assertEqual(row["missed_relevant_fixed"], [target])
        self.assertEqual(row["baseline_retrieved_unjudged_count"], 2)
        self.assertEqual(row["selected_retrieved_unjudged_count"], 1)
        self.assertEqual(row["stale_judgment_count"], 1)
        self.assertIn("qrels_incomplete", row["incomplete_categories"])

    def test_baseline_retained_without_validation_positive_or_on_failed_validation(self):
        for kwargs, expected in [({"validation": False}, "validation_unavailable"),
                                 ({"validation": True, "failing_validation": True}, "validation_failed")]:
            result, _ = self.run_tune(max_candidates=4, **kwargs)
            self.assertEqual(result["selection"]["selected_candidate_id"], "baseline")
            self.assertEqual(result["settings"], concepts.validate_concept(fixture_concept())["settings"])
            self.assertEqual(result["selection"]["reason"], expected)

    def test_saved_runs_and_exports_are_owner_scoped(self):
        with tempfile.TemporaryDirectory() as root:
            paths = {"account-a": Path(root) / "a.sqlite", "account-b": Path(root) / "b.sqlite"}
            with patch("es_rag_tuner.auth.state_database_path", side_effect=lambda owner: paths[owner]):
                ctx, _ = self.setup_mocks()
                with ctx[0], ctx[1], ctx[2], ctx[3], concepts.owner_scope("account-a"):
                    saved = concepts.save_concept(fixture_concept())["concept"]
                    result = concepts.tune(None, saved, max_candidates=2)
                    self.assertEqual(concepts.get_saved_concept(saved["id"])["settings"], saved["settings"])
                with concepts.owner_scope("account-a"):
                    run = concepts.export_run("bounded-tune-fixture", result["run_id"])
                    self.assertIn("candidate_trace", run["run"])
                    self.assertIn("validation_diagnostics", run["run"])
                with concepts.owner_scope("account-b"):
                    self.assertEqual(concepts.list_runs("bounded-tune-fixture")["runs"], [])
                    with self.assertRaises(ElasticsearchError):
                        concepts.export_run("bounded-tune-fixture", result["run_id"])


if __name__ == "__main__":
    unittest.main()
