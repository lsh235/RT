# Cycle 21 no-ID lookup README acceptance

## Scope and baseline

- Baseline supplied for this cycle: `v0.17.1`, commit `1c63dd0`.
- Package checked: `0.17.2`.
- Requested QA model assignment: `gpt-6-luna`; runtime identity is **UNVERIFIED** because available task telemetry does not prove it.
- QA-owned files: [static acceptance check](../tests/cycle21_no_id_lookup_readme.py) and this report. The implementation worker owned README/package metadata. Unrelated user files `docs/agent-sdk-upstream-review-2026-10-18.md` and `docs/novice-retrieval-improvements-2026-10-18.md` were preserved. QA performed no Git operations.
- Scope is README guidance and package version metadata only. No application behavior changed. No live Elasticsearch, database, corpus, or provider was accessed.

## Acceptance results

| Gate | Status | Evidence |
|---|---|---|
| Step six does not require a known document ID | **PASS** | `python3 tests/cycle21_no_id_lookup_readme.py` checks the concept-search workflow step six for the conditional unknown-ID flow and rejects wording that makes ID entry mandatory. |
| Link points to an existing heading | **PASS** | The static check parses the Markdown heading slug and resolves the step-six link `#초보자-먼저-개념-검색` to `## 초보자: 먼저 개념 검색`. |
| Candidate -> query -> diagnosis/load sequence | **PASS** | Checked in order: select a candidate, fill its document ID, choose a saved query, then diagnose the missing result or load/evaluate the document. |
| Manual ID lookup remains available | **PASS** | Step six still says users who know the ID can enter it directly. |
| No-result limitation | **PASS** | Step six explicitly says no candidates do not prove that a document is absent from the index. |
| Package/module/UI versions | **PASS** | Static check found `0.17.2` in `pyproject.toml`, `es_rag_tuner.__version__`, and the visible version badge in `es_rag_tuner/web/index.html`. Isolated wheel installation independently reported module and distribution metadata as `0.17.2`. |
| Full offline suite | **PASS (limited)** | `ES_RAG_ACCEPTANCE_ES_URL=http://127.0.0.1:1 python3 -m unittest discover -s tests -v` — `Ran 101 tests in 6.342s`, `OK (skipped=2)`, exit 0. Live Elasticsearch acceptance skipped because the loopback endpoint refused connection; tokenizer parity skipped because required tokenizer assets were unavailable. These are not live Elasticsearch or tokenizer-parity passes. |
| Isolated wheel/install/module/CLI smoke | **PASS** | Staged `pyproject.toml`, `README.md`, and `es_rag_tuner/` to a temporary source directory, excluding `*.egg-info`; built `es_rag_tuning_workbench-0.17.2-py3-none-any.whl`; installed to a temporary target; verified module version `0.17.2`, distribution metadata `0.17.2`, packaged `web/app.js` present, and `es-rag-workbench --help` exit 0 (`usage: es-rag-workbench [-h] [--host HOST] [--port PORT]`). Metadata checks ran with the temporary directory as cwd to avoid repository-local metadata. Temporary artifacts were removed. |
| Browser/live/provider/user validation | **NOT RUN** | Not needed for this documentation and metadata change. No live Elasticsearch, user corpus/database, provider, or user study was used. |
| Runtime model identity | **UNVERIFIED** | `gpt-6-luna` was the requested assignment; runtime identity is not established by available telemetry. |

## Commands and iteration notes

The direct static check printed:

```text
Cycle 21 README and version checks: PASS
Resolved link: ['#초보자-먼저-개념-검색'] -> 초보자: 먼저 개념 검색
Versions: pyproject=0.17.2, module=0.17.2, UI=0.17.2
```

The full test suite command is recorded in the table above. The isolated package smoke used Python 3's `tempfile.TemporaryDirectory`, `pip wheel --no-deps --no-build-isolation`, `pip install --no-deps --target`, installed metadata/module inspection, and the installed console script's `--help` from outside the checkout.

While constructing the static check, its first draft searched the novice quickstart for numbered item six, but that section contains only three numbered steps; the target is step six under the nested **개념 검색 실험** workflow. The check was corrected to scope that workflow and then passed. No product or acceptance failure remained open.
