from __future__ import annotations

import math
import uuid
from unittest import mock

import pytest

from es_rag_tuner import auth, concepts, evaluation_datasets as datasets
from es_rag_tuner.es_client import ElasticsearchError


def _provenance():
    return {
        "source_uri": "",
        "source_name": "synthetic acceptance fixture",
        "source_license": "synthetic; no external material",
        "permission_status": "synthetic",
        "collection_date": "2026-10-19",
        "extraction_rules": "constructed by the test",
        "omitted_known_relevant_items": "none",
        "judgment_source": "synthetic",
        "assessor": "acceptance test",
    }


def _content():
    return {
        "name": "synthetic retrieval fixture",
        "provenance": _provenance(),
        "queries": [
            {"query_id": "q1", "query": "alpha records", "split": "validation", "information_need": "need-a"},
            {"query_id": "q2", "query": "beta records", "split": "test", "information_need": "need-b"},
        ],
        "qrels": [
            {"query_id": "q1", "document_index": "docs", "document_id": "1", "grade": 3, "document_family_id": "family-a"},
            {"query_id": "q1", "document_index": "docs", "document_id": "2", "grade": 1},
            {"query_id": "q1", "document_index": "docs", "document_id": "3", "grade": None},
            {"query_id": "q2", "document_index": "docs", "document_id": "4", "grade": 2, "document_family_id": "family-b"},
        ],
    }


@pytest.fixture
def account_db(tmp_path, monkeypatch):
    monkeypatch.setattr(concepts, "_db_path", lambda: tmp_path / "evaluation.sqlite3")
    return "synthetic-owner-" + uuid.uuid4().hex


def test_versioned_import_export_round_trip_and_immutability(account_db):
    with concepts.owner_scope(account_db):
        created = datasets.create_dataset(**_content())
        dataset_id = created["dataset_id"]
        version_id = created["version"]["version_id"]
        original = datasets.get_dataset_version(dataset_id, version_id)
        assert original["version"]["fingerprint"] == created["version"]["fingerprint"]
        assert original["qrels"][2]["grade"] is None

        for fmt in ("csv", "jsonl"):
            exported = datasets.export_dataset(dataset_id, version_id, fmt)
            imported = datasets.import_dataset(fmt, exported["content"])
            assert imported["idempotent"] is True
            assert imported["dataset"]["dataset_id"] == dataset_id
            assert imported["version"]["version_id"] == version_id
            assert imported["fingerprint"] == original["fingerprint"]
        csv_export = datasets.export_dataset(dataset_id, version_id, "csv")
        assert csv_export["content"].splitlines()[0].split(",") == list(datasets.CSV_FIELDS)

        changed = _content()
        changed["queries"][0]["query"] = "alpha records updated"
        version2 = datasets.create_version(dataset_id, version_id, **changed)
        assert version2["version"]["version_number"] == 2
        assert datasets.get_dataset_version(dataset_id, version_id)["queries"][0]["query"] == "alpha records"
        with pytest.raises(ElasticsearchError, match="latest version"):
            datasets.create_version(dataset_id, version_id, **changed)


def test_dataset_versions_are_isolated_by_authenticated_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "state_database_path", lambda owner_id: tmp_path / f"{owner_id}.sqlite3")
    with concepts.owner_scope("owner-a"):
        created = datasets.create_dataset(**_content())
        dataset_id = created["dataset_id"]
        version_id = created["version"]["version_id"]
        assert datasets.get_dataset_version(dataset_id, version_id)["dataset"]["dataset_id"] == dataset_id

    with concepts.owner_scope("owner-b"):
        assert datasets.list_datasets()["datasets"] == []
        with pytest.raises(ElasticsearchError, match="not found"):
            datasets.get_dataset_version(dataset_id, version_id)


def test_import_validation_is_atomic_and_split_leakage_is_rejected(account_db):
    payload = _content()
    payload["queries"][1]["information_need"] = payload["queries"][0]["information_need"]
    with concepts.owner_scope(account_db):
        with pytest.raises(ElasticsearchError, match="split leakage"):
            datasets.create_dataset(**payload)
        assert datasets.list_datasets()["datasets"] == []

        good = _content()
        created = datasets.create_dataset(**good)
        bad = datasets.export_dataset(created["dataset_id"], created["version"]["version_id"], "jsonl")["content"]
        bad = bad.replace('"grade":null', '"grade":4')
        with pytest.raises(ElasticsearchError, match="grade"):
            datasets.import_dataset("jsonl", bad)
        assert len(datasets.list_datasets()["datasets"]) == 1
        assert len(datasets.list_datasets()["datasets"][0]["versions"]) == 1


@pytest.mark.parametrize("mutation,expected", [
    (lambda rows: rows[1].update(query="  ALPHA   records "), "normalized character-trigram"),
    (lambda rows: rows[1].update(query="unrelated beta", information_need="need-a"), "information_need"),
])
def test_normalized_query_and_explicit_group_leakage(mutation, expected):
    content = _content()
    mutation(content["queries"])
    with pytest.raises(ElasticsearchError, match=expected):
        datasets._validate_content(**content)


def test_document_family_leakage_is_checked_across_query_splits():
    content = _content()
    content["qrels"][3]["document_family_id"] = "family-a"
    with pytest.raises(ElasticsearchError, match="document_family_id"):
        datasets._validate_content(**content)


def test_exact_concrete_document_reuse_across_splits_is_rejected_but_same_split_is_allowed():
    cross_split = _content()
    cross_split["qrels"][3]["document_index"] = "docs"
    cross_split["qrels"][3]["document_id"] = "1"
    with pytest.raises(ElasticsearchError, match="concrete document identity"):
        datasets._validate_content(**cross_split)

    same_split = _content()
    same_split["queries"][1]["split"] = "validation"
    same_split["qrels"][3]["document_index"] = "docs"
    same_split["qrels"][3]["document_id"] = "1"
    datasets._validate_content(**same_split)


def _reference_metrics(hits, qrels, cutoff, policy):
    """Small acceptance oracle derived directly from the documented formulas."""
    qrel_by_key = {(row["document_index"], row["document_id"]): row for row in qrels}
    returned = hits[:cutoff]
    numeric_returned = []
    explicit_null_count = absent_count = relevant_returned = 0
    judged_entries = []
    inclusive_entries = []
    ranked_states = []
    for rank, hit in enumerate(returned, start=1):
        key = (hit["_index"], hit["_id"])
        judgment = qrel_by_key.get(key)
        if judgment is None:
            absent_count += 1
            state, grade = "absent", None
        elif judgment["grade"] is None:
            explicit_null_count += 1
            state, grade = "explicit_null", None
        else:
            state, grade = "numeric", judgment["grade"]
            numeric_returned.append(hit)
            judged_entries.append(grade)
        inclusive_entries.append(grade if grade is not None else 0)
        ranked_states.append(state)

    numeric_qrels = [row["grade"] for row in qrels if row["grade"] is not None]
    relevant_qrel_count = sum(grade >= 2 for grade in numeric_qrels)
    ranking_grades = judged_entries if policy == "judged_only" else inclusive_entries
    denominator = min(cutoff, len(numeric_returned)) if policy == "judged_only" else cutoff
    relevant_returned = sum(grade >= 2 for grade in ranking_grades)
    relevant_ranks = [rank for rank, grade in enumerate(ranking_grades, start=1) if grade >= 2]
    precision = relevant_returned / denominator if denominator else None
    recall = relevant_returned / relevant_qrel_count if relevant_qrel_count else None
    mrr = (1 / relevant_ranks[0]) if relevant_ranks else (0.0 if relevant_qrel_count else None)

    def dcg(grades):
        return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))

    ideal = sorted(numeric_qrels, reverse=True)[:cutoff]
    idcg = dcg(ideal)
    ndcg = dcg(ranking_grades) / idcg if idcg else None
    if not relevant_qrel_count:
        recall = mrr = ndcg = None
    coverage = len(numeric_returned) / len(returned) if returned else 0.0
    return {
        "metrics": {"precision_at_k": precision, "recall_at_k": recall, "mrr_at_k": mrr,
                    "ndcg_at_k": ndcg, "judged_coverage_at_k": coverage},
        "counts": {"returned_at_k": len(returned), "numeric_judged_retrieved": len(numeric_returned),
                   "explicit_null_retrieved": explicit_null_count, "absent_qrel_retrieved": absent_count,
                   "numeric_qrels_total": len(numeric_qrels),
                   "explicit_null_qrels_total": sum(row["grade"] is None for row in qrels),
                   "known_relevant": relevant_qrel_count, "relevant_retrieved_at_k": relevant_returned},
        "ranked_states": ranked_states,
        "precision_denominator": denominator,
    }


def test_metric_implementation_matches_independent_reference_matrix():
    qrels = [
        {"document_index": "docs", "document_id": "1", "grade": 3},
        {"document_index": "docs", "document_id": "2", "grade": 1},
        {"document_index": "docs", "document_id": "3", "grade": None},
        {"document_index": "docs", "document_id": "5", "grade": 2},
    ]
    cases = [
        # Graded relevance, grade>=2 binary threshold, partial qrels, explicit null vs absent.
        {"name": "graded_partial", "hits": ("3", "1", "2", "99"), "qrels": qrels,
         "cutoff": 4, "policy": "judged_only"},
        # A short response list must use only numeric judgments for judged-only P@k.
        {"name": "short_list", "hits": ("1", "99"), "qrels": qrels,
         "cutoff": 4, "policy": "judged_only"},
        # Equal raw scores retain backend order, so the relevant result is at rank two.
        {"name": "tied_rank", "hits": ("2", "5"), "qrels": qrels,
         "cutoff": 2, "policy": "judged_only", "tied": True},
        # No grade reaches the binary threshold; R/MRR/nDCG must be unavailable.
        {"name": "zero_positive", "hits": ("a", "b"), "qrels": [
            {"document_index": "docs", "document_id": "a", "grade": 0},
            {"document_index": "docs", "document_id": "b", "grade": 1}],
         "cutoff": 2, "policy": "judged_only"},
        # A known-positive query with no relevant returned hit has zero MRR, not an unavailable value.
        {"name": "missed_relevant", "hits": ("99",), "qrels": [
            {"document_index": "docs", "document_id": "5", "grade": 3}],
         "cutoff": 5, "policy": "judged_only"},
        # Explicitly selected alternative policy counts missing/null results as nonrelevant.
        {"name": "unjudged_as_nonrelevant", "hits": ("3", "1", "2", "99"), "qrels": qrels,
         "cutoff": 3, "policy": "unjudged_as_nonrelevant"},
    ]

    for case in cases:
        hits = [{"_index": "docs", "_id": doc_id,
                 "_score": 1.0 if case.get("tied") else 10.0 - rank}
                for rank, doc_id in enumerate(case["hits"], start=1)]
        expected = _reference_metrics(hits, case["qrels"], case["cutoff"], case["policy"])
        actual = datasets._metrics_for_query(hits, case["qrels"], case["cutoff"], case["policy"])
        for metric, expected_value in expected["metrics"].items():
            actual_value = actual["metrics"][metric]
            if expected_value is None:
                assert actual_value is None, case["name"]
            else:
                assert actual_value == pytest.approx(expected_value), (case["name"], metric)
        for count, expected_value in expected["counts"].items():
            assert actual["counts"][count] == expected_value, (case["name"], count)
        assert [row["qrel_state"] for row in actual["ranked_hits"]] == expected["ranked_states"]
        assert actual["denominators"]["precision_at_k"] == expected["precision_denominator"]
        if case["name"] == "zero_positive":
            assert set(actual["unavailable_reasons"]) >= {"recall_at_k", "mrr_at_k", "ndcg_at_k"}
        if case["name"] == "missed_relevant":
            assert actual["metrics"]["recall_at_k"] == 0.0
            assert actual["metrics"]["mrr_at_k"] == 0.0
            assert actual["metrics"]["ndcg_at_k"] == 0.0
            assert "mrr_at_k" not in actual["unavailable_reasons"]
        if case["name"] == "tied_rank":
            assert actual["metrics"]["mrr_at_k"] == pytest.approx(0.5)
            assert actual["ranked_hits"][0]["document_id"] == "2"
            assert actual["ranked_hits"][1]["document_id"] == "5"
        if case["policy"] == "unjudged_as_nonrelevant":
            assert actual["unjudged_policy_consequence"] == "counted_as_nonrelevant_by_explicit_policy"

    with pytest.raises(ElasticsearchError, match="qrels_complete=true"):
        datasets._validate_content(name="x", provenance=_provenance(), queries=_content()["queries"], qrels=[],
                                   unjudged_policy="unjudged_as_nonrelevant", qrels_complete=False)


def test_evaluation_passes_recorded_settings_and_requires_frozen_test_config(account_db):
    with concepts.owner_scope(account_db):
        created = datasets.create_dataset(**_content())
        dataset_id, version_id = created["dataset_id"], created["version"]["version_id"]
        with pytest.raises(ElasticsearchError, match="configuration_frozen=true"):
            datasets.evaluate(None, "docs", dataset_id, version_id, "test", "bm25", {}, 5, False)

        hits = [{"_index": "docs", "_id": "4", "_score": 0.7}]
        with mock.patch.object(datasets.concepts, "_index_identity", return_value=({"uuids": ["uuid-1"]}, None)), \
             mock.patch.object(datasets, "request", return_value={"docs": {"mappings": {"properties": {"body": {"type": "text"}}}}}), \
             mock.patch.object(datasets, "retrieve", return_value={"hits": hits}) as retrieve:
            result = datasets.evaluate(
                None, "docs", dataset_id, version_id, "test", "bm25",
                {"size": 5, "candidate_pool": 23, "rank_constant": 17,
                 "boosts": {"summary": 2}, "filters": [{"field": "status", "value": "open"}],
                 "profile_id": "profile-a", "rerank": False},
                5, True,
            )
        kwargs = retrieve.call_args.kwargs
        assert kwargs["candidate_pool"] == 23
        assert kwargs["rank_constant"] == 17
        assert result["settings"]["candidate_pool"] == 23
        assert result["settings"]["size"] == 5
        assert result["mapping_fingerprint"]
        assert result["queries"][0]["counts"]["known_relevant"] == 1
        assert result["test_run_consumed"] is True
        with mock.patch.object(datasets.concepts, "_index_identity", return_value=({"uuids": ["uuid-1"]}, None)), \
             mock.patch.object(datasets, "request", return_value={"docs": {"mappings": {}}}), \
             mock.patch.object(datasets, "retrieve", return_value={"hits": hits}):
            with pytest.raises(ElasticsearchError, match="already been consumed"):
                datasets.evaluate(None, "docs", dataset_id, version_id, "test", "bm25",
                                  {"size": 5, "candidate_pool": 23}, 5, True)

        for settings, cutoff in (({"size": 0}, 1), ({"size": 1, "candidate_pool": 201}, 1),
                                 ({"size": 2}, 3), ({"rank_constant": 0}, 1), ({"rerank": "yes"}, 1)):
            with pytest.raises(ElasticsearchError):
                datasets.evaluate(None, "docs", dataset_id, version_id, "validation", "bm25", settings, cutoff)


def test_failed_test_batch_does_not_consume_final_run_and_ai_suggestions_are_not_ground_truth(account_db):
    with concepts.owner_scope(account_db):
        created = datasets.create_dataset(**_content())
        dataset_id, version_id = created["dataset_id"], created["version"]["version_id"]
        with mock.patch.object(datasets.concepts, "_index_identity", return_value=({"uuids": ["uuid-2"]}, None)), \
             mock.patch.object(datasets, "request", return_value={"docs": {"mappings": {}}}), \
             mock.patch.object(datasets, "retrieve", side_effect=ElasticsearchError("synthetic failure", 503)):
            failed = datasets.evaluate(None, "docs", dataset_id, version_id, "test", "bm25", {"size": 1}, 1, True)
        assert failed["run_id"] is None
        assert failed["persisted"] is False
        assert failed["test_run_consumed"] is False
        assert failed["failed_query_count"] == 1
        assert "aggregate" not in failed
        assert "queries" not in failed
        assert "metrics" not in failed
        assert datasets.list_runs(dataset_id, version_id)["runs"] == []

        with mock.patch.object(datasets.concepts, "_index_identity", return_value=({"uuids": ["uuid-2"]}, None)), \
             mock.patch.object(datasets, "request", return_value={"docs": {"mappings": {}}}), \
             mock.patch.object(datasets, "retrieve", return_value={"hits": [{"_index": "docs", "_id": "4", "_score": 1}]}):
            succeeded = datasets.evaluate(None, "docs", dataset_id, version_id, "test", "bm25", {"size": 1}, 1, True)
        assert succeeded["persisted"] is True

        ai_content = _content()
        ai_content["provenance"]["judgment_source"] = "ai_suggestion"
        ai_dataset = datasets.create_dataset(**ai_content)
        with pytest.raises(ElasticsearchError, match="AI-suggested judgments are not ground truth"):
            datasets.evaluate(None, "docs", ai_dataset["dataset_id"], ai_dataset["version"]["version_id"],
                              "validation", "bm25", {"size": 1}, 1)
