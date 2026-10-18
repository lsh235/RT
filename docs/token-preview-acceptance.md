# Exact E5 passage token preview acceptance

Status: Cycle 8 local acceptance gates were executed after coordinator approval. See the execution table below for individual results and boundaries. Requested QA model override: `gpt-6-luna`; runtime model identifier: **not independently observable or verified by this worker**. This document records local test, packaging, and synthetic-browser evidence only; it does not establish production Elasticsearch behavior or model inference.

## Contract under test

The preview counts the exact `embedding_input.text` already returned by `POST /api/document`. The caller passes that string unchanged as `input_text` to `POST /api/token-preview`. The preview helper must not derive source fields, prepend `passage: `, query Elasticsearch, or initialize FastEmbed/ONNX.

| Route/helper | Required behavior |
|---|---|
| `GET /api/token-preview/status` | Read-only local status. It may inspect the local tokenizer cache but never connects to the network or loads the embedding model. |
| `POST /api/token-preview` | Accept `{ "input_text": "<exact embedding_input.text>" }`. Return stable fields `available`, `model`, `revision`, `max_tokens`, `full_token_count`, `retained_token_count`, `truncated`, `input_text`, `retained_text`, `removed_text`, `cut_char_offset`, and `reason`. |
| `POST /api/token-preview/prepare` | No document text/body. This is the only route allowed to retrieve assets. It accepts no caller-supplied repository, revision, URL, or file list. Failure leaves preview unavailable with a clear reason. |
| `preview_input(input_text, tokenizer=None)` | Pure preview seam. The supplied string is encoded as-is, with special tokens and a 512-token right-truncation. Production adapts the pinned tokenizer behind the injected `encode(text, *, truncation=False, max_length=None)` protocol. |

Empty or whitespace-only input is unavailable/non-embeddable, not a successful encoding containing only special tokens. Counts describe one unpadded encoding and include attended special tokens. `truncated` is true exactly when the full attended count exceeds the retained count. The retained and removed strings are exact adjacent slices of the original input at the original offset of the last retained non-special token. Special tokens with `(0, 0)` offsets do not move the cut. For a non-truncated input, retained text is the entire original string and removed text is empty.

## Pinned tokenizer assets

Preparation is limited to these four files at the immutable revision below. Their content hashes are the acceptance pins; names, revision, and hashes must remain fixed in code and tests.

Repository: `Qdrant/multilingual-e5-large-onnx`
Revision: `ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b`

| File | SHA-256 |
|---|---|
| `tokenizer.json` | `f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af` |
| `tokenizer_config.json` | `f90024142df07163e5e6c5b9a6ad7c8c68b22a9112af11e3db4559a9ff90f737` |
| `config.json` | `1de8c3be1f344c0eefa4962480a006f8639f416dfafaa95a770e3cf4bceae6a4` |
| `special_tokens_map.json` | `8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835` |

The selected assets total approximately 17.1 MB. Preparation must enforce the exact file allowlist, immutable revision, and per-file SHA-256 before marking the tokenizer available. No ONNX, model-weight, or other repository files may be downloaded. No user text may leave the application. Normal page load, document fetch, status, and preview must perform no network access. Preview/status/document flows must not call `_model()`, instantiate `TextEmbedding`, or load ONNX.

## Acceptance matrix

| Gate | PASS when | FAIL when |
|---|---|---|
| Exact input and prefix | Preview receives and returns the exact supplied `embedding_input.text`, including its single existing `passage: ` prefix and all remaining whitespace. | Preview adds another prefix, trims/reformats the input, or uses a different source string. |
| 511/512/over-512 attended tokens | Full and retained counts include special tokens; 511 and 512 stay untruncated, while an input above 512 retains exactly 512 attended tokens with right truncation. | The limit excludes special tokens, boundary behavior is off by one, or truncation is left-sided. |
| Source text offsets | Retained/removed text are lossless adjoining slices of the exact input, and the cut is taken from the original offsets of retained tokens while ignoring `(0, 0)` special-token offsets. | Text is reconstructed by decode, characters disappear/duplicate, whitespace moves, or a cut bisects a tokenizer offset. |
| Text coverage | Include multilingual/CJK text, emoji, combining marks, CR/LF, tabs, repeated/leading/trailing whitespace, empty input, and whitespace-only input. | Unicode offsets are interpreted as byte offsets or empty text is reported as a successful special-token-only count. |
| No implicit network/model/ES | With network, downloader, Elasticsearch request, `_model()`, `TextEmbedding`, and ONNX entry points guarded, status, preview, document fetch, and page load complete without touching them. The document route performs only its expected mocked read. | Any normal viewing path retrieves assets, contacts Elasticsearch beyond the document GET, sends user text externally, or loads embedding inference. |
| Explicit asset preparation | A fake transport sees only the four pinned file paths from the pinned official repo revision; each byte payload is hash-checked. Unknown file, URL/revision override, bad hash, oversize response, offline failure, and partial/corrupt cache fail closed. | Preparation accepts a mutable/untrusted location, fetches model weights/ONNX, marks invalid files available, or is invoked implicitly. |
| Unavailable states | Missing optional tokenizer dependency, absent cache, offline/download error, corrupt cache, and tokenizer exception yield stable `available: false`, a useful `reason`, and no crash. Retry occurs only after explicit prepare. | The UI/API crashes, reports a guessed count, or silently retries a network request. |
| Browser behavior | UI shows full token count, the 512-token retained limit, retained/cut preview and unavailable state. Untrusted HTML-like input renders as text. Preview does not alter the document sent by the existing workflow or search behavior. | Markup executes, displayed text/count diverges from the API, or preview mutates submitted input/search behavior. |

## Test artifact scope

`tests/test_token_preview_acceptance.py` is authored against the pure `preview_input(input_text, tokenizer=None)` seam and local HTTP routes. Its injected tokenizer is deterministic and dependency-free: whitespace tokens have source offsets, and two attended special tokens have `(0, 0)` offsets. It covers the 511/512/513 attended-token boundaries, exact right-truncated slices, the supplied prefix, Unicode and whitespace slicing, empty/non-embeddable input, synthetic tokenizer/cache failures, asset pins and size rejection, explicit prepare-body restrictions, concurrent truncation configuration, and the document/status/preview HTTP flow with exactly one stubbed document GET and a model-loading guard. The explicit preparation fixture lets the real verifier check synthetic bytes: a mismatched digest must return unavailable before `_load_tokenizer`, while valid fixture bytes use only the four fixed filenames and pinned repository revision.

The suite also contains an opt-in real-tokenizer parity test. It runs only when `ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE` points to a dedicated temporary directory containing exactly the four named files at the pinned revision. It verifies their hashes, requires FastEmbed 0.9.0, calls FastEmbed's tokenizer loader directly, and compares retained IDs plus full untruncated counts against the preview tokenizer. It must never download assets or instantiate `TextEmbedding`, ONNX, or model weights. Leave the variable unset during an ordinary offline full-suite run; that test will be skipped. Do not point it at a user/auth cache.

The UI unit check verifies text-only DOM assignment, exact passage forwarding, and the narrow-screen CSS rule. A separate headless Chrome run at 390px used synthetic HTML-like input and intercepted API responses. It checked rendered counts/status, absence of an injected image or event execution, page width, and unchanged search/document input strings. It did not use a live search service or Elasticsearch.

The HTTP and browser fixtures used synthetic input and dynamic loopback ports, with API responses intercepted and no Elasticsearch connection or user database. Ports 8765/8766 and the default `127.0.0.1:9200` endpoint were not used. The full suite was run only with `ES_RAG_ACCEPTANCE_ES_URL=offline://disabled`.

## Execution evidence

| Gate | Status | Evidence/boundary |
|---|---|---|
| Focused preview acceptance | **PASS** | Final command: `python3 -m unittest discover -s tests -p 'test_token_preview_acceptance.py' -v` using the system Python 3.12.3. Result: 18 tests passed, 1 skipped, 0 failures. The skipped real-tokenizer test was then run separately with its fixture and passed. An earlier run exposed three incorrect call-count expectations in the test draft; those assertions were corrected, and the final focused run passed. |
| Real pinned asset hash and FastEmbed 0.9.0 parity | **PASS** | Fetched only the four listed assets from the immutable revision into `/tmp/cycle8-tokenizer-qa.iMlPFs/fixture`; all four SHA-256 values matched the table. Command: `ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE=/tmp/cycle8-tokenizer-qa.iMlPFs/fixture /tmp/cycle8-tokenizer-qa.iMlPFs/venv/bin/python -m unittest discover -s tests -p 'test_token_preview_acceptance.py' -v`. Result: 18 passed, no skips. Environment: Python 3.12.3, FastEmbed 0.9.0, tokenizers 0.23.3, huggingface-hub 1.33.0, onnxruntime 1.31.0 (installed for FastEmbed package imports only). No `TextEmbedding` was constructed and no model weights or ONNX session were loaded. |
| Safe offline regression suite | **PASS** | Command: `env -u ES_RAG_ACCEPTANCE_TOKENIZER_FIXTURE ES_RAG_ACCEPTANCE_ES_URL=offline://disabled /tmp/cycle8-tokenizer-qa.iMlPFs/venv/bin/python -m unittest discover -s tests -v`. Result: 45 tests passed, 2 skipped, 0 failures. `LiveConceptAcceptance.setUpClass` skipped with `unknown url type: offline`, before any network connection; real tokenizer parity skipped because its opt-in variable was unset. No live Codex/Copilot provider calls were made by this run. |
| Oversize asset rejection and explicit preparation | **PASS** | Unit coverage rejects a file over the configured 18 MiB tokenizer JSON bound before hashing. Synthetic prepare bytes pass through the real verifier: a mismatched digest returns unavailable before tokenizer loading; valid bytes use the fixed four filenames and repository revision. |
| Wheel build, install, and CLI health/assets | **PASS** | Built wheel outside the workspace with `/tmp/cycle8-tokenizer-qa.iMlPFs/venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/cycle8-tokenizer-qa.iMlPFs/wheelhouse .`; wheel `es_rag_tuning_workbench-0.9.0-py3-none-any.whl`, 170,817 bytes, SHA-256 `ce081003525de84ab5ca5020dc298ac35981b03aecfe0eedf6f46d72cc4f3fa7`. Created `/tmp/cycle8-tokenizer-qa.iMlPFs/install-venv` with Python 3.12.3 and installed using `/tmp/cycle8-tokenizer-qa.iMlPFs/install-venv/bin/python -m pip install --no-deps /tmp/cycle8-tokenizer-qa.iMlPFs/wheelhouse/es_rag_tuning_workbench-0.9.0-py3-none-any.whl`; `es-rag-workbench --help` succeeded. The installed CLI returned `/api/health` HTTP 200 with `{"ok":true,"version":"0.9.0"}` and served `/`, `/app.js`, and `/style.css` HTTP 200 with expected markers on an ephemeral loopback port. Runtime used a temporary `HOME` and SQLite path. The wheel output was directed to `/tmp`; the pre-existing workspace `dist/` directory was left untouched. |
| Headless browser at 390px | **PASS** | Playwright CLI 0.1.22 with Google Chrome 154.0.8037.97, on a dynamic loopback port. Synthetic API responses supplied an HTML-like `<img ... onerror=...>` passage. The UI rendered counts `513` and `512` and truncation status; `textContent` preserved the string, no image node was created, and the event did not run. At viewport width 390, both document and body scroll widths were 390; token preview used one 310px column. Search query and document source input strings were unchanged after opening the synthetic document and previewing. APIs were intercepted; this was not live search/Elasticsearch evidence. |
| Search, vectorization, or production Elasticsearch behavior | **NOT RUN** | Outside this acceptance scope. The offline sentinel intentionally prevented a live Elasticsearch test. |

All required local gates above completed successfully. This is not a production-readiness or live Elasticsearch claim. The requested QA model override was `gpt-6-luna`; the runtime model identifier remained unavailable for independent verification.
