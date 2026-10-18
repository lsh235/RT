"""Cycle 39 private-knowledge preview and local judgment API acceptance.

Run with: ./.venv/bin/python -m unittest discover -s tests -p 'test_knowledge_evaluation.py' -v
The API uses disposable account-local SQLite state and an unreachable ES URL.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from es_rag_tuner import auth, concepts, knowledge, server
try:
    from tests.cycle37_auth_test_support import AuthenticatedClient, install_auth_fixture
except ModuleNotFoundError:
    from cycle37_auth_test_support import AuthenticatedClient, install_auth_fixture


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class KnowledgeEvaluationAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), server.WorkbenchHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.client = install_auth_fixture(self, self.base)

    def post(self, path: str, body: dict, expected: int = 200):
        status, payload = self.client.post(path, body)
        self.assertEqual(status, expected, f"{path} returned {status}: {payload}")
        return payload

    def concept(self, *, query: str = "amber report", concept_id: str | None = None) -> dict:
        return {
            "id": concept_id or "knowledge-eval-" + uuid.uuid4().hex[:12],
            "name": "Amber incident concept",
            "description": "operational response guide",
            "aliases": ["amber runbook"],
            "related": [{"term": "dispatch protocol", "weight": 1}],
            "excluded_terms": ["obsolete"],
            "corpus": {"index": "unused-local-only", "text_fields": ["body"]},
            "queries": [
                {"id": "q-train", "query": query, "split": "train"},
                {"id": "q-check", "query": "independent check", "split": "validation"},
            ],
        }

    def save_concept(self, concept: dict) -> dict:
        return self.post("/api/concepts/save", {"concept": concept})["concept"]

    def save_doc(self, title: str, content: str, source: str = "manual") -> str:
        result = self.post("/api/knowledge/save", {"title": title, "content": content, "source_label": source})
        return result["document"]["document_id"]

    def preview(self, concept: dict, query_id: str = "q-train", expected: int = 200) -> dict:
        return self.post("/api/knowledge/concept-preview", {"concept_id": concept["id"], "query_id": query_id}, expected)

    def judge(self, concept: dict, document_id: str, rating: int | None, expected: int = 200) -> dict:
        result = self.post("/api/knowledge/judge", {
            "concept_id": concept["id"], "query_id": "q-train", "document_id": document_id, "rating": rating,
        }, expected)
        if expected == 200:
            judgment = result["judgment"]
            self.assertEqual(set(judgment), {"concept_id", "query_id", "document_id", "rating", "stale", "updated_at"})
            self.assertNotIn("content", judgment)
            self.assertNotIn("title", judgment)
        return result

    def test_preview_is_saved_context_only_local_fts_and_never_calls_es(self):
        concept = self.save_concept(self.concept(query='amber OR "report" <script>'))
        exact = self.save_doc("Amber exact", "amber report procedure", "ops")
        self.save_doc("Expansion only", "dispatch protocol response", "guide")
        excluded_id = self.save_doc("Excluded expansion", "obsolete amber runbook", "archive")
        # These provider entry points must remain untouched while the preview succeeds.
        with mock.patch.object(concepts, "request", side_effect=AssertionError("Elasticsearch request attempted")), \
             mock.patch.object(concepts.embeddings, "embed_texts", side_effect=AssertionError("embedding attempted")):
            result = self.preview(concept)
        self.assertEqual(result["query"], 'amber OR "report" <script>')
        self.assertEqual(result["split"], "train")
        self.assertEqual({hit["document_id"] for hit in result["baseline"]["hits"]}, {exact, excluded_id})
        expanded_ids = {hit["document_id"] for hit in result["expanded"]["hits"]}
        self.assertIn(exact, expanded_ids)
        self.assertNotIn(excluded_id, expanded_ids)
        self.assertEqual(result["baseline"]["hits"][0]["rank"], 1)
        self.assertLessEqual(result["baseline"]["hits"][0]["score"], 0)
        self.assertTrue(any("FTS5 only" in item for item in result["limits"]))
        self.assertTrue(any("lower-is-better" in item for item in result["limits"]))
        self.assertTrue(any("automated tuning" in item for item in result["limits"]))
        self.assertNotIn("content", result["baseline"]["hits"][0])
        self.assertNotIn("chunk", result["baseline"]["hits"][0])
        self.assertRegex(result["corpus_fingerprint"], r"^[0-9a-f]{64}$")

    def test_weight_metadata_is_safe_and_positive_magnitudes_do_not_change_local_ranking(self):
        concept = self.concept(query="amber report")
        concept["related"] = [{"term": "dispatch protocol", "weight": 0.25}, {"term": "response guide", "weight": 0.1}]
        concept["settings"] = {"concept_weight": 0.5, "related_weight": 0.25}
        self.save_concept(concept)
        self.save_doc("Baseline", "amber report and dispatch protocol")
        self.save_doc("Expansion", "dispatch protocol response guide")
        first = self.preview(concept)
        concept["settings"] = {"concept_weight": 8, "related_weight": 3}
        concept["related"] = [{"term": "dispatch protocol", "weight": 7}, {"term": "response guide", "weight": 3}]
        self.save_concept(concept)
        second = self.preview(concept)
        for group in ("baseline", "expanded"):
            self.assertEqual(first[group], second[group])
        self.assertEqual(first["metrics"], second["metrics"])
        self.assertEqual(first["weight_behavior"], {
            "concept_weight": 0.5, "concept_expression_count": 3,
            "concept_expressions_included": True, "related_weight": 0.25,
            "related_terms_total": 2, "related_terms_included": 2,
            "numeric_values_affect_ranking": False,
        })
        self.assertEqual(second["weight_behavior"]["concept_weight"], 8)
        self.assertEqual(second["weight_behavior"]["related_weight"], 3)
        safe_keys = {"concept_weight", "concept_expression_count", "concept_expressions_included", "related_weight", "related_terms_total", "related_terms_included", "numeric_values_affect_ranking"}
        self.assertEqual(set(first["weight_behavior"]), safe_keys)
        serialized = json.dumps(first["weight_behavior"], ensure_ascii=False)
        for private_value in ("Amber incident concept", "operational response guide", "amber runbook", "dispatch protocol", "response guide"):
            self.assertNotIn(private_value, serialized)

    def test_zero_weight_gates_only_expansion_groups_not_baseline(self):
        concept = self.concept(query="cobalt query")
        baseline_id = self.save_doc("Baseline", "cobalt query")
        concept_only = self.save_doc("Concept expansion", "amber incident concept operational response guide")
        related_only = self.save_doc("Related expansion", "dispatch protocol")
        self.save_concept(concept)
        positive = self.preview(concept)
        concept["settings"] = {"concept_weight": 0, "related_weight": 1}
        self.save_concept(concept)
        no_concept = self.preview(concept)
        self.assertEqual(positive["baseline"], no_concept["baseline"])
        no_concept_ids = {hit["document_id"] for hit in no_concept["expanded"]["hits"]}
        positive_expanded_ids = {hit["document_id"] for hit in positive["expanded"]["hits"]}
        self.assertNotIn(concept_only, no_concept_ids)
        self.assertIn(related_only, no_concept_ids)
        self.assertIn(concept_only, positive_expanded_ids)
        self.assertEqual(no_concept["weight_behavior"]["concept_expressions_included"], False)
        self.assertEqual(no_concept["weight_behavior"]["related_terms_included"], 1)
        concept["settings"] = {"concept_weight": 1, "related_weight": 0}
        self.save_concept(concept)
        no_related = self.preview(concept)
        self.assertEqual(positive["baseline"], no_related["baseline"])
        no_related_ids = {hit["document_id"] for hit in no_related["expanded"]["hits"]}
        self.assertNotIn(related_only, no_related_ids)
        self.assertIn(concept_only, no_related_ids)
        self.assertIn(baseline_id, {hit["document_id"] for hit in no_related["baseline"]["hits"]})
        self.assertEqual(no_related["weight_behavior"]["concept_expressions_included"], True)
        self.assertEqual(no_related["weight_behavior"]["related_terms_included"], 0)

    def test_legacy_missing_weights_report_backend_defaults(self):
        concept = self.concept()
        concept.pop("settings", None)
        self.save_concept(concept)
        result = self.preview(concept)
        self.assertEqual(result["weight_behavior"]["concept_weight"], 1)
        self.assertEqual(result["weight_behavior"]["related_weight"], 1)

    def test_preview_requires_exact_saved_ids_and_hides_foreign_scope(self):
        own = self.save_concept(self.concept())
        doc_id = self.save_doc("own", "amber report")
        self.assertEqual(self.preview(own)["concept_id"], own["id"])
        self.post("/api/knowledge/concept-preview", {"concept_id": own["id"], "query_id": "missing"}, 404)
        self.post("/api/knowledge/concept-preview", {"concept_id": "missing", "query_id": "q-train"}, 404)
        self.post("/api/knowledge/concept-preview", {"concept_id": own["id"], "query_id": "q-train", "query": "forged"}, 400)
        self.post("/api/knowledge/judge", {"concept_id": own["id"], "query_id": "missing", "document_id": doc_id, "rating": 2}, 404)
        self.post("/api/knowledge/judge", {"concept_id": own["id"], "query_id": "q-train", "document_id": "unknown-document", "rating": 2}, 404)
        self.post("/api/knowledge/judge", {"concept_id": own["id"], "query_id": "q-train", "document_id": doc_id, "rating": 2, "owner_id": "forged"}, 400)

        foreign_password = "Cycle39-foreign-password-001!"
        foreign_user = auth.create_account("cycle39-foreign-" + uuid.uuid4().hex[:8], "Foreign account", foreign_password)
        foreign_db = auth.state_database_path(foreign_user["id"])
        self.addCleanup(lambda: [Path(str(foreign_db) + suffix).unlink(missing_ok=True) for suffix in ("", "-wal", "-shm")])
        foreign = AuthenticatedClient(self.base, foreign_user, password=foreign_password)
        foreign_concept = self.concept(concept_id="foreign-" + uuid.uuid4().hex[:8])
        status, saved = foreign.post("/api/concepts/save", {"concept": foreign_concept})
        self.assertEqual(status, 200, saved)
        status, foreign_doc = foreign.post("/api/knowledge/save", {"title": "foreign", "content": "amber report", "source_label": "foreign"})
        self.assertEqual(status, 200, foreign_doc)
        self.post("/api/knowledge/concept-preview", {"concept_id": foreign_concept["id"], "query_id": "q-train"}, 404)
        self.judge(own, foreign_doc["document"]["document_id"], 2, 404)

    def test_literal_terms_expansion_exclusions_and_document_level_dedup(self):
        concept = self.save_concept(self.concept(query="alpha beta"))
        multi = self.save_doc("Amber runbook", "alpha beta " + "x " * 1900 + "dispatch protocol", "manual")
        expansion_only = self.save_doc("Guide", "dispatch protocol only", "manual")
        excluded_only = self.save_doc("Obsolete", "obsolete amber runbook", "manual")
        result = self.preview(concept)
        self.assertEqual(result["baseline"]["total"], 1)
        self.assertEqual([h["document_id"] for h in result["baseline"]["hits"]], [multi])
        self.assertEqual(len([h for h in result["expanded"]["hits"] if h["document_id"] == multi]), 1)
        self.assertIn(expansion_only, {h["document_id"] for h in result["expanded"]["hits"]})
        self.assertNotIn(excluded_only, {h["document_id"] for h in result["expanded"]["hits"]})
        self.assertEqual(result["baseline"]["hits"][0]["rank"], 1)
        self.assertEqual(result["expanded"]["hits"], sorted(result["expanded"]["hits"], key=lambda h: (h["score"], h["document_id"], h["chunk_id"])))

    def test_matched_groups_are_fixed_lexical_labels_for_returned_representative_chunks(self):
        concept = self.concept(query="basecue")
        concept.update(name="conceptcue", description="conceptdetail blockedcue", aliases=["conceptalias"],
                       related=[{"term": "relatedcue", "weight": 1}],
                       excluded_terms=["blockedcue"], settings={"concept_weight": 1, "related_weight": 1})
        self.save_concept(concept)
        query_only = self.save_doc("query", "basecue")
        concept_only = self.save_doc("concept", "conceptcue")
        related_only = self.save_doc("related", "relatedcue")
        overlap = self.save_doc("overlap", "basecue conceptalias relatedcue")
        blocked = self.save_doc("blocked", "basecue blockedcue")
        title_match = self.save_doc("basecue", "titleonlybody")
        source_match = self.save_doc("source", "sourceonlybody", "conceptdetail")
        nonmatch = self.save_doc("control", "ordinary unrelated prose")
        # The later chunk has a related-only cue. The returned representative
        # must not inherit that document-level match if another row wins ranking.
        split_chunk = self.save_doc("basecue", "basecue conceptcue " + "x " * 1050 + "relatedcue " + "y " * 1000)

        with mock.patch.object(knowledge, "_attach_matched_groups", return_value=None):
            without_labels = self.preview(concept)
        result = self.preview(concept)

        def without_matched_groups(payload):
            projected = json.loads(json.dumps(payload))
            for lane_name in ("baseline", "expanded"):
                for hit in projected[lane_name]["hits"]:
                    hit.pop("matched_groups", None)
            return projected

        self.assertEqual(without_matched_groups(result), without_matched_groups(without_labels))
        baseline = {hit["document_id"]: hit for hit in result["baseline"]["hits"]}
        expanded = {hit["document_id"]: hit for hit in result["expanded"]["hits"]}
        self.assertEqual(set(baseline), {query_only, overlap, blocked, title_match, split_chunk})
        self.assertNotIn(nonmatch, baseline)
        self.assertNotIn(nonmatch, expanded)
        self.assertNotIn(blocked, expanded)  # whole-document exclusion precedes result labeling
        self.assertIn(concept_only, expanded)
        self.assertIn(related_only, expanded)
        self.assertIn(source_match, expanded)

        allowed = {"saved_query", "concept_expressions", "related_terms"}
        for lane_name, lane, want_baseline in (("baseline", baseline, True), ("expanded", expanded, False)):
            for document_id, hit in lane.items():
                groups = hit["matched_groups"]
                self.assertIsInstance(groups, list)
                self.assertEqual(len(groups), len(set(groups)))
                self.assertTrue(set(groups) <= allowed)
                if want_baseline:
                    self.assertEqual(groups, ["saved_query"])
                else:
                    # Independently ask FTS5 about this exact representative chunk
                    # and the same literal expression used by the ranker.
                    candidate_groups = {
                        "saved_query": knowledge._query_terms("basecue"),
                        "concept_expressions": ["conceptcue", "conceptdetail", "conceptalias"],
                        "related_terms": ["relatedcue"],
                    }
                    exact = []
                    with concepts._connect_db() as db:
                        for group, terms in candidate_groups.items():
                            expr = knowledge._literal_match(terms)
                            if expr and db.execute("SELECT 1 FROM knowledge_fts WHERE knowledge_fts MATCH ? AND chunk_id=?", (expr, hit["chunk_id"])).fetchone():
                                exact.append(group)
                    self.assertEqual(groups, exact, f"{lane_name} groups for {document_id} must match the representative FTS row")
        self.assertEqual(expanded[query_only]["matched_groups"], ["saved_query"])
        self.assertEqual(expanded[concept_only]["matched_groups"], ["concept_expressions"])
        self.assertEqual(expanded[related_only]["matched_groups"], ["related_terms"])
        self.assertEqual(expanded[overlap]["matched_groups"], ["saved_query", "concept_expressions", "related_terms"])
        self.assertNotIn("blockedcue", json.dumps([hit["matched_groups"] for hit in expanded.values()]))
        self.assertNotIn("related_terms", expanded[split_chunk]["matched_groups"])

        # Labels add no term, chunk content, scoring, rank, totals, or metric data.
        self.assertEqual(result["baseline"]["total"], len(baseline))
        self.assertEqual(result["expanded"]["total"], len(expanded))
        self.assertEqual(result["metrics"]["baseline"]["judged_count"], 0)
        for lane in (baseline, expanded):
            for hit in lane.values():
                self.assertNotIn("conceptcue", json.dumps(hit["matched_groups"]))
                self.assertNotIn("relatedcue", json.dumps(hit["matched_groups"]))
                self.assertNotIn("basecue", json.dumps(hit["matched_groups"]))

        # Disabled concept/related groups and excluded terms do not produce labels.
        concept["settings"] = {"concept_weight": 0, "related_weight": 0}
        self.save_concept(concept)
        disabled = self.preview(concept)
        for hit in disabled["expanded"]["hits"]:
            self.assertEqual(hit["matched_groups"], ["saved_query"])
        concept["settings"] = {"concept_weight": 1, "related_weight": 1}
        concept["related"] = []
        self.save_concept(concept)
        empty_related = self.preview(concept)
        self.assertTrue(all("related_terms" not in hit["matched_groups"] for hit in empty_related["expanded"]["hits"]))


    def test_preview_rejects_more_than_200_unique_query_terms_without_partial_results(self):
        query = " ".join(f"w{i}" for i in range(201))
        self.assertLessEqual(len(query), knowledge.MAX_SEARCH_QUERY_CODEPOINTS)
        concept = self.save_concept(self.concept(query=query))
        partial_match = self.save_doc("Must not return partial results", "w0", "manual")

        result = self.preview(concept, expected=400)

        self.assertEqual(
            result.get("error"),
            "A local concept search is limited to 200 unique literal terms; shorten the saved query or concept text.",
        )
        self.assertNotIn("baseline", result)
        self.assertNotIn("expanded", result)
        self.assertNotIn("hits", result)
        self.assertNotIn(partial_match, json.dumps(result, ensure_ascii=False))

    def test_equal_score_document_ties_are_stable(self):
        concept = self.save_concept(self.concept(query="tie marker"))
        one = self.save_doc("Identical title", "tie marker identical body", "same-source")
        two = self.save_doc("Identical title", "tie marker identical body", "same-source")
        first = self.preview(concept)["baseline"]["hits"]
        second = self.preview(concept)["baseline"]["hits"]
        tied = [hit["document_id"] for hit in first if hit["document_id"] in {one, two}]
        self.assertEqual(tied, sorted([one, two]))
        self.assertEqual([hit["document_id"] for hit in first], [hit["document_id"] for hit in second])

    def test_judgments_distinguish_zero_null_and_current_metrics(self):
        concept = self.save_concept(self.concept())
        irrelevant = self.save_doc("Unrelated", "amber report unrelated")
        positive = self.save_doc("Good", "amber report runbook")
        null_id = self.save_doc("Explicit unjudged", "amber report notes")
        self.judge(concept, irrelevant, 0)
        self.judge(concept, positive, 3)
        self.judge(concept, null_id, None)
        result = self.preview(concept)
        by_id = {hit["document_id"]: hit for hit in result["baseline"]["hits"]}
        self.assertEqual(by_id[irrelevant]["judgment"], {"rating": 0, "stale": False})
        self.assertEqual(by_id[positive]["judgment"], {"rating": 3, "stale": False})
        self.assertEqual(by_id[null_id]["judgment"], {"rating": None, "stale": False})
        metric = result["metrics"]["baseline"]
        self.assertEqual(metric["judged_count"], 2)
        self.assertEqual(metric["positive_count"], 1)
        self.assertEqual(metric["unjudged_count"], 1)
        self.assertEqual(metric["known_positive_recall"], 1.0)
        self.assertEqual(metric["source_counts"]["manual"], {"judged": 2, "positive": 1, "unjudged": 1, "stale": 0})
        self.assertEqual(self.judge(concept, irrelevant, None)["judgment"]["rating"], None)
        self.assertEqual(self.judge(concept, irrelevant, 0)["judgment"]["rating"], 0)

    def test_ndcg_uses_condensed_judged_only_ranking(self):
        # Match concepts._graded_metrics: unknown results are omitted before
        # judged positions are enumerated for DCG.
        hits = [
            {"document_id": "unknown", "rank": 1},
            {"document_id": "positive", "rank": 2},
            {"document_id": "zero", "rank": 3},
        ]
        active = {"zero": {"rating": 0}, "positive": {"rating": 3}}
        metric = knowledge._metrics(hits, active, [], [
            {"document_id": "zero", "rating": 0, "stale": False, "source_label": "s"},
            {"document_id": "positive", "rating": 3, "stale": False, "source_label": "s"},
        ])
        self.assertEqual(metric["ndcg_at_k"], 1.0)

    def test_query_and_document_edits_make_saved_ratings_stale_and_rejudge_refreshes(self):
        concept = self.save_concept(self.concept())
        doc_id = self.save_doc("Amber procedure", "amber report procedure")
        self.judge(concept, doc_id, 3)
        edited_concept = {**concept, "queries": [{**concept["queries"][0], "query": "amber incident report"}, concept["queries"][1]]}
        concept = self.save_concept(edited_concept)
        stale = self.preview(concept)
        hit = next(h for h in stale["baseline"]["hits"] if h["document_id"] == doc_id)
        self.assertEqual(hit["judgment"], {"rating": 3, "stale": True})
        self.assertEqual(stale["metrics"]["baseline"]["stale_count"], 1)
        self.assertEqual(stale["metrics"]["baseline"]["judged_count"], 0)
        self.judge(concept, doc_id, 2)
        self.post("/api/knowledge/save", {"document_id": doc_id, "title": "Edited title", "content": "amber incident report changed", "source_label": "manual"})
        stale_doc = self.preview(concept)
        hit = next(h for h in stale_doc["baseline"]["hits"] if h["document_id"] == doc_id)
        self.assertTrue(hit["judgment"]["stale"])
        self.assertEqual(stale_doc["metrics"]["baseline"]["judged_count"], 0)
        self.judge(concept, doc_id, 1)
        self.post("/api/knowledge/delete", {"document_id": doc_id})
        deleted = self.preview(concept)
        self.assertEqual(deleted["metrics"]["baseline"]["stale_count"], 1)
        self.assertNotIn(doc_id, {h["document_id"] for h in deleted["baseline"]["hits"]})

    def test_corpus_fingerprint_changes_on_local_document_edit_without_returning_content(self):
        concept = self.save_concept(self.concept())
        doc_id = self.save_doc("Fingerprint source", "amber report corpus sentinel")
        first = self.preview(concept)["corpus_fingerprint"]
        self.assertEqual(self.preview(concept)["corpus_fingerprint"], first)
        self.post("/api/knowledge/save", {"document_id": doc_id, "title": "Fingerprint source", "content": "amber report changed sentinel", "source_label": "manual"})
        second_result = self.preview(concept)
        self.assertNotEqual(second_result["corpus_fingerprint"], first)
        self.assertNotIn("corpus sentinel", json.dumps(second_result, ensure_ascii=False))

    def test_rating_validation_and_authenticated_csrf_boundary(self):
        concept = self.save_concept(self.concept())
        doc_id = self.save_doc("Validation", "amber report")
        for invalid in (True, -1, 4, 1.5, "2"):
            self.post("/api/knowledge/judge", {"concept_id": concept["id"], "query_id": "q-train", "document_id": doc_id, "rating": invalid}, 400)
        status, _ = self.client.request("/api/knowledge/concept-preview", {"concept_id": concept["id"], "query_id": "q-train"}, csrf="invalid")
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
