# Cycle 34 tune metric identity hotfix acceptance

## Scope

Added a synthetic regression test for `concepts.tune()` that stubs search, judgment loading, index identity, and run persistence. It does not connect to Elasticsearch or open a database. The fixture verifies that two ranked graded documents contribute to retrieval count, judged coverage, recall, and nDCG; one case uses two distinct concrete index/document pairs that collide under the old U+001F concatenation.

Requested model: `gpt-6-luna`  
Runtime identity: **UNVERIFIED**

## Pre-fix reproduction result

Command run from `/home/sra235/2026/elasticsearch-rag`:

```text
python3 -m unittest discover -s tests -p 'test_cycle34_tune_metric_identity.py' -v
```

Environment: Python 3.12.3 via `/home/sra235/.pyenv/shims/python3`; Linux shell in the project checkout. The regular `python` command is not configured in pyenv in this environment (`pyenv: python: command not found`), so the focused run used `python3`.

Output against the current source:

```text
test_bm25_ranked_graded_documents_contribute_to_metrics (test_cycle34_tune_metric_identity.TuneMetricIdentityRegression.test_bm25_ranked_graded_documents_contribute_to_metrics) ... FAIL
test_concrete_index_and_document_id_delimiter_collision_stays_distinct (test_cycle34_tune_metric_identity.TuneMetricIdentityRegression.test_concrete_index_and_document_id_delimiter_collision_stays_distinct) ... FAIL

======================================================================
FAIL: test_bm25_ranked_graded_documents_contribute_to_metrics (test_cycle34_tune_metric_identity.TuneMetricIdentityRegression.test_bm25_ranked_graded_documents_contribute_to_metrics)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/sra235/2026/elasticsearch-rag/tests/test_cycle34_tune_metric_identity.py", line 66, in test_bm25_ranked_graded_documents_contribute_to_metrics
    self.assert_ranked_judgments_are_counted([
  File "/home/sra235/2026/elasticsearch-rag/tests/test_cycle34_tune_metric_identity.py", line 60, in assert_ranked_judgments_are_counted
    self.assertEqual(baseline["retrieved_judged_count"], 2)
AssertionError: 0 != 2

======================================================================
FAIL: test_concrete_index_and_document_id_delimiter_collision_stays_distinct (test_cycle34_tune_metric_identity.TuneMetricIdentityRegression.test_concrete_index_and_document_id_delimiter_collision_stays_distinct)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/sra235/2026/elasticsearch-rag/tests/test_cycle34_tune_metric_identity.py", line 73, in test_concrete_index_and_document_id_delimiter_collision_stays_distinct
    self.assert_ranked_judgments_are_counted([
  File "/home/sra235/2026/elasticsearch-rag/tests/test_cycle34_tune_metric_identity.py", line 60, in assert_ranked_judgments_are_counted
    self.assertEqual(baseline["retrieved_judged_count"], 2)
AssertionError: 0 != 2

----------------------------------------------------------------------
Ran 2 tests in 0.002s

FAILED (failures=2)
```

Both cases fail at the first assertion because the current ranking keys do not match the graded judgment keys. The later coverage, recall, and nDCG assertions are acceptance expectations and were not reached in this run. No implementation was edited; no full suite was run; no commit or tag was created.

## Post-fix QA

Requested model: `gpt-6-luna`  
Runtime identity: **UNVERIFIED**

| Gate | Result | Evidence |
|---|---|---|
| Tune identity regression | **PASS** | `./.venv/bin/python -m unittest discover -s tests -p 'test_cycle34_tune_metric_identity.py' -v` — 2 tests passed. Both normal identity and U+001F collision cases report `retrieved_judged_count=2`, judged coverage `1.0`, relevant found `1`, recall `1.0`, and nDCG `1.0`. |
| Cycle 34 mode comparison focused tests | **PASS** | `./.venv/bin/python -m unittest discover -s tests -p 'test_concept_mode_comparison_acceptance.py' -v` — 7 tests passed. |
| Full offline suite | **PASS with skips** | `env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 ES_RAG_CONCEPT_DB=/tmp/cycle34-hotfix-qa.vrWoMW/concepts.sqlite3 ./.venv/bin/python -m unittest discover -s tests -v` — 110 tests, `OK (skipped=2)`. The live Elasticsearch fixture skipped after connection refused at the deliberately unreachable loopback endpoint; real tokenizer parity skipped because the pinned fixture was absent. Neither skip is a live Elasticsearch or tokenizer-parity pass. Two existing `ResourceWarning`s for open HTTP fixture handles were emitted; there were no failures. |
| Isolated wheel/package smoke | **PASS** | Built and installed the v0.22.1 wheel in a temporary staging copy using `/usr/bin/python3`; package metadata, installed module, CLI startup, packaged page, served page, and health endpoint all reported v0.22.1. Wheel SHA-256: `ff5895bf334061a3d0edd27141a4cd80ed4c7fab5f91866e2c46703b99d6253f`. |
| Syntax and diff checks | **PASS** | `node --check es_rag_tuner/web/app.js`, `node --check tests/cycle34_mode_comparison_browser.js`, `.venv/bin/python -m py_compile tests/test_cycle34_tune_metric_identity.py es_rag_tuner/concepts.py es_rag_tuner/server.py`, and `git diff --check` all exited 0. |

The full suite used only the temporary SQLite path above. The tune test mocked search and persistence; the mode-comparison suite uses synthetic fixture data and mocked Elasticsearch; the suite's live Elasticsearch class skipped before search. No user database, corpus, credentials, model download, or user study was used. The previous v0.22.0 Cycle 34 acceptance report and browser fixture were not modified.

### Package smoke details

The first build attempt used the project `.venv` and failed because that environment lacks `setuptools.build_meta`. A read-only check found `/usr/bin/python3` is Python 3.12.3 with setuptools 68.1.2 and wheel 0.42.0, so the isolated smoke was rerun with that interpreter without installing dependencies or altering the environment. One initial `/usr/bin/python3` smoke harness ran from the checkout and therefore read the checkout's old `egg-info`; its CLI output was also buffered. The final run used a fresh staging directory and ran the installed package from outside the checkout with unbuffered CLI output.

Final temporary staging directory: `/tmp/cycle34-hotfix-package-final-kqn7qiih`; staging contained copies of `pyproject.toml`, `README.md`, and `es_rag_tuner/`. Exact build and install commands:

```text
/usr/bin/python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/cycle34-hotfix-package-final-kqn7qiih/wheelhouse /tmp/cycle34-hotfix-package-final-kqn7qiih/source
/usr/bin/python3 -m pip install --no-deps --target /tmp/cycle34-hotfix-package-final-kqn7qiih/install /tmp/cycle34-hotfix-package-final-kqn7qiih/wheelhouse/es_rag_tuning_workbench-0.22.1-py3-none-any.whl
```

Both commands exited 0. The wheel was 198,163 bytes with SHA-256 `ff5895bf334061a3d0edd27141a4cd80ed4c7fab5f91866e2c46703b99d6253f`. Running `/usr/bin/python3` from the temporary directory with `PYTHONPATH=<install>` reported package metadata `0.22.1`, imported module version `0.22.1`, and installed page `v0.22.1`. The installed CLI was launched with a fresh temporary SQLite path on loopback port 55195 and reported:

```text
ES RAG Tuning Workbench 0.22.1 is ready at http://127.0.0.1:55195
GET /api/health: {"ok": true, "version": "0.22.1"}
GET / page version: v0.22.1
```

The original `docs/cycle34-mode-comparison-acceptance.md` and `tests/cycle34_mode_comparison_browser.js` evidence files were not modified. No user database, corpus, credentials, model download, live Elasticsearch request, or user study was used. No commit or tag was created. Unrelated untracked user documents remain untouched.
