"""Source-level guardrails for the UI-only concept candidate pool.

The corresponding browser acceptance is recorded in the Cycle 16 report. These
checks keep the identity, per-lane ranking, explicit judgment, and stale-request
guards visible in the implementation without contacting Elasticsearch.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "es_rag_tuner" / "web" / "app.js").read_text(encoding="utf-8")


def section(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    finish = source.index(end, begin)
    return source[begin:finish]


class ConceptCandidatePoolAcceptance(unittest.TestCase):
    def test_pool_union_keys_concrete_index_and_id_and_is_bounded(self):
        merge = section(APP_JS, "function buildUnifiedCandidatePool(", "function clearVectorCandidatePool(")
        self.assertIn("JSON.stringify([String(index || concept.corpus.index), String(id)])", merge)
        self.assertIn("const key = identityKey(index, id)", merge)
        self.assertIn("slice(0, 2 * size)", merge)
        self.assertIn("laneRanks: { bm25: Number(rank) }", merge)
        self.assertIn("laneRanks: { vector: Number(hit.rank) }", merge)

    def test_pool_displays_only_lane_ranks_without_comparing_scores(self):
        render = section(APP_JS, "function renderResultSet(", "async function loadVectorCandidates(")
        self.assertIn("kind === \"pool\" ? (hit.laneRanks?.bm25 ?? null)", render)
        self.assertIn("BM25 ${hit.laneRanks?.bm25", render)
        self.assertIn("벡터 ${hit.laneRanks?.vector", render)
        self.assertNotIn("_score +", render)
        self.assertNotIn("_score -", render)

    def test_explicit_judgment_keeps_exact_query_index_id_and_null_zero(self):
        save = section(APP_JS, "async function saveJudgment(", "function selectedIndexFallback(")
        self.assertIn("query_id: controls.dataset.queryId", save)
        self.assertIn("document_index: controls.dataset.index", save)
        self.assertIn("document_id: controls.dataset.id", save)
        self.assertIn("ratingValue === \"null\" ? null : Number(ratingValue)", save)
        self.assertIn('"pool"', save)

    def test_stale_vector_success_error_and_finally_cannot_restore_pool_or_button(self):
        load = section(APP_JS, "async function loadVectorCandidates(", "function validVectorCandidateResponse(")
        self.assertGreaterEqual(load.count("if (requestGeneration !== state.vectorCandidateGeneration) return;"), 2)
        self.assertIn("if (requestGeneration === state.vectorCandidateGeneration) button.disabled", load)
        clear = section(APP_JS, "function clearVectorCandidatePool(", "function labelBm25Only(")
        self.assertIn("state.vectorCandidateGeneration += 1", clear)
        self.assertIn("replaceChildren()", clear)
        self.assertIn("$(\"#concept-vector-candidates\").disabled = true", clear)


if __name__ == "__main__":
    unittest.main()
