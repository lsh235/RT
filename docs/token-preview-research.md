# Cycle 8: exact E5 token count and truncation preview research

**Research date:** 2026-10-18
**Repository baseline:** `b3f7f7256429c8c1b57eb3794fbab79fde3e3eec` (`v0.8.0`)
**Scope:** source research and repository inspection only. No implementation, tests, environment/secrets, user documents, database, or Elasticsearch were accessed. The codebase-memory MCP was not available in this session; repository facts below are bounded to the files named.

## Finding

An exact, local E5 token count and a retained/truncated-input preview are technically feasible without loading or downloading the 2.24 GB FastEmbed ONNX weights, but the ordinary `TextEmbedding(model_name=...)` construction path does **not** provide that lightweight behavior. FastEmbed 0.9.0 resolves/downloads the model directory in its constructor, even with `lazy_load=True`; only ONNX session creation is deferred. Once the model directory exists, FastEmbed's `token_count()` uses its already-loaded tokenizer and runs no ONNX inference. However, its tokenizer is configured for the model's 512-token truncation before counting, so the API count is capped for overlong inputs. A full pre-truncation count and source-text cut position need a separate untruncated encoding plus a truncated encoding's character offsets.

The narrow implementation route is to obtain only the tokenizer assets for the **FastEmbed model artifact**, load them with the same FastEmbed tokenizer configuration logic, and run the tokenizer on the exact current `passage: ` input. This is a small, separate tokenizer-only download/cache path, not a call to the current embedding model singleton. Pinning the FastEmbed package and tokenizer artifact revision is necessary for the result to remain reproducible. If that asset acquisition and pinning are out of scope, defer exact preview rather than silently triggering the model's multi-gigabyte download.

## Verified repository facts

- The baseline is clean at `b3f7f7256429c8c1b57eb3794fbab79fde3e3eec`, exact tag `v0.8.0`.
- `pyproject.toml` has no mandatory runtime dependencies and declares the optional extra `semantic = ["fastembed>=0.9,<1"]`. There is no dependency lockfile in the inspected root file set. This range can admit later 0.x FastEmbed releases; it does not freeze the tokenizer implementation or transitive `tokenizers`/Hub versions.
- `es_rag_tuner/embeddings.py` selects `intfloat/multilingual-e5-large`, sets 1024 dimensions, prefixes stripped text with `passage: ` or `query: `, and sends those strings to `model.embed()`. Its current lazy singleton constructor uses the standard `TextEmbedding(...)` path; it does not load a tokenizer independently.
- `document_text()` prefers nonempty stripped `rag_chunk_text`; otherwise it builds text from the supported Jira fields and comment bodies. `passage_input()` returns the exact `passage: `-prefixed text without loading the model.

## Verified primary-source facts

### Model and tokenizer identity

- The [E5 model card](https://huggingface.co/intfloat/multilingual-e5-large) specifies the exact model's `query: ` / `passage: ` use, including non-English text, shows `AutoTokenizer(..., max_length=512, truncation=True)`, states that long texts are truncated at 512 tokens, and identifies the model as initialized from XLM-RoBERTa with support for 100 languages (with quality caveats for low-resource languages).
- FastEmbed v0.9.0's E5 model registry is in [`pooled_embedding.py`](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/pooled_embedding.py), not `onnx_embedding.py`. It registers public name `intfloat/multilingual-e5-large` to the Qdrant ONNX artifact, declares 2.24 GB, 1024 dimensions, 512-token truncation, and required query/document prefixes, and lists `model.onnx` plus `model.onnx_data`. The registered artifact is the [Qdrant multilingual-e5-large ONNX model repository at the checked revision](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/tree/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b), not the original model weights repository. Its [tokenizer config at that immutable revision](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/tokenizer_config.json) declares `model_max_length: 512` and `XLMRobertaTokenizer`; its [model config at the same revision](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/config.json) identifies the upstream name as `intfloat/multilingual-e5-large` and `xlm-roberta` architecture. These facts support using the FastEmbed artifact's tokenizer files to preview the FastEmbed path, but do not establish byte-for-byte identity of all asset revisions with the upstream Hugging Face repository.
- The current Hugging Face model-repository commit as of the research date is `ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b`. The repository tree at this exact revision contains all four relevant files plus a 2.24 GB ONNX external-data file. `tokenizer.json` is 17,082,756 bytes, `tokenizer_config.json` is 1,147 bytes, `config.json` is 716 bytes, and `special_tokens_map.json` is 964 bytes. This gives a reproducible immutable asset revision and shows that staging the selected small files need not include the ONNX weights.
- I streamed each file from its official Hugging Face `resolve/<full-commit>/<filename>` URL and computed SHA-256 over the downloaded bytes. The resulting checksums are below; `tokenizer.json` also matches the SHA-256 published in its Hub/Xet LFS pointer (`oid sha256:...`). Its distinct Xet object ID is `0abd02c8ae3c446b4b196b4041ef6b8dc3dce7d172091fa5ca5ce17b4eb7d627`. HF's API separately exposes the repo commit and file object metadata; those identifiers are **not** interchangeable with file-content SHA-256. The repo commit identifies the tree snapshot, the Xet object ID identifies the stored object, and the SHA-256 values below identify the bytes consumed by the tokenizer implementation. For the three small JSON files, the Hub API does not publish a file-content SHA-256 in the pages inspected; their hashes below are my calculations over bytes served at the immutable revision, not official Hub-published checksum claims.

| Asset at commit `ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b` | Bytes | SHA-256 of downloaded file bytes | Source |
|---|---:|---|---|
| `tokenizer.json` | 17,082,756 | `f59925fcb90c92b894cb93e51bb9b4a6105c5c249fe54ce1c704420ac39b81af` | [immutable file](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/tokenizer.json) |
| `tokenizer_config.json` | 1,147 | `f90024142df07163e5e6c5b9a6ad7c8c68b22a9112af11e3db4559a9ff90f737` | [immutable file](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/tokenizer_config.json) |
| `config.json` | 716 | `1de8c3be1f344c0eefa4962480a006f8639f416dfafaa95a770e3cf4bceae6a4` | [immutable file](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/config.json) |
| `special_tokens_map.json` | 964 | `8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835` | [immutable file](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/special_tokens_map.json) |

FastEmbed's v0.9.0 loader requires `tokenizer.json` and `tokenizer_config.json`; it reads `config.json` and `special_tokens_map.json` conditionally. For safest parity with the registered artifact, pin and stage all four files, verify each SHA-256 during packaging/startup, and keep the immutable Hub commit in the manifest. The commit is the revision identifier; do not label a Git object ID or Xet pointer ID as the file's SHA-256.
- FastEmbed v0.9.0's [tokenizer loader](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/common/preprocessor_utils.py) requires `tokenizer.json` and `tokenizer_config.json`, reads optional `config.json` and `special_tokens_map.json`, sets truncation using the configured context length and truncation side, and enables padding. The Qdrant tokenizer config fixes the context at 512. This is the relevant tokenizer configuration/API path for matching FastEmbed's preprocessing. `tokenizers.Tokenizer.from_file()` alone does not reproduce FastEmbed's config handling unless those truncation/special-token settings are also applied.

### Counts, offsets, and model loading

- In FastEmbed v0.9.0, [`TextEmbedding.token_count()`](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/text_embedding.py) delegates to `_token_count()`. The [ONNX text tokenizer implementation](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/onnx_text_model.py) documents that its tokenizer-only path does not need an ONNX session, and `_token_count()` sums `attention_mask` values from `encode_batch()`. Since the tokenizer is already configured for truncation, this counts retained encoded tokens, not the full over-limit input. It also includes model-added special tokens as they are attended tokens; padding does not add tokens to the count.
- The v0.9.0 [FastEmbed model constructor](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/onnx_embedding.py) calls `download_model()` before checking `lazy_load`. Therefore `lazy_load=True` defers ONNX session loading but does not itself avoid model-directory resolution/download. Using `token_count()` on a newly constructed normal FastEmbed model object is not a safe guarantee against the large download.
- FastEmbed v0.9.0 declares `tokenizers>=0.15,<1.0` and `huggingface-hub>=0.20,<2.0` in its [package metadata](https://github.com/qdrant/fastembed/blob/v0.9.0/pyproject.toml). The official [Hugging Face Hub API](https://huggingface.co/docs/huggingface_hub/en/package_reference/file_download) supports downloading an individual named file; its [download guide](https://huggingface.co/docs/huggingface_hub/en/guides/download) supports revision/commit selection. This makes selective retrieval of small tokenizer/config files possible without requesting the ONNX weights. The Hugging Face API contract does not guarantee file size or immutability when `revision="main"`; use an immutable commit revision and verify asset hashes for reproducibility.
- The official [`tokenizers.Encoding` API](https://huggingface.co/docs/tokenizers/main/api/encoding) exposes token IDs, `attention_mask`, and per-token `offsets` that can slice back to the source input. It describes offsets as spans into the original input that produced each token and documents truncation behavior. Therefore the display boundary can be derived from the last retained content token's end offset, ignoring special tokens with empty/zero spans. For this app, that offset must be applied to the exact complete string `passage: ${document_text.strip()}`; the prefix consumes part of the 512-token budget. Do not reconstruct text by joining token strings, and do not infer the boundary from a whitespace-word count.

### Multilingual and whitespace behavior

The tokenizer is XLM-R/XLM-RoBERTa based. Token counts are tokenizer subword IDs, not words, whitespace splits, Unicode code points, or bytes. English, Korean, Japanese, mixed scripts, punctuation, repeated spaces, and line breaks can tokenize to different counts for strings with similar word counts. Offset-based slicing handles source characters without assuming whitespace boundaries. The model card describes language support but does not specify count equivalences across languages; none should be implied.

## Product inference and implementation boundary

**Inference:** A novice-facing exact count and cut preview is practical if the app uses the FastEmbed tokenizer bundle without initializing `TextEmbedding` or invoking `_model()`. Use the FastEmbed artifact (`Qdrant/multilingual-e5-large-onnx`) as the tokenizer source, because that is what the current FastEmbed registry uses. The source evidence provides an immutable snapshot (`ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b`) and SHA-256 values for all four assets. For production, do not download assets at runtime: stage those four files from the pinned snapshot during release/build, include a manifest with repository commit, filenames, byte lengths, and SHA-256, and verify them before loading. This avoids user-visible network/model downloads and mutable `main` references. Feed the exact `passage_input()` text into the FastEmbed v0.9-compatible tokenizer setup.

Expose two clearly labeled counts:

1. **Full input token count:** count all attended tokens before truncation, including the tokenizer's model-added special tokens and the literal `passage: ` prefix. This requires encoding with truncation disabled.
2. **Retained token count:** apply FastEmbed's configured 512-token right truncation and count attended tokens (at most 512). If the full count is at most 512, show no truncation. Otherwise use the last retained non-special token's source-character offset to display the exact retained prefix and mark the remainder as truncated. The returned text should preserve the original source substring; trim trailing whitespace only for presentation and make clear that the cut is token-driven.

Do not call `TextEmbedding.token_count()` if that initializes the full model directory. Although it is useful for confirming FastEmbed's retained-token semantics when a model is already cached, the installed v0.9.0 API lacks a public tokenizer-only construction path. Depending on internal `fastembed.common.preprocessor_utils.load_tokenizer` is version-sensitive. A maintainable implementation should either narrowly pin FastEmbed and wrap this internal loader with compatibility checks, or separately own and test the exact documented FastEmbed-compatible tokenizer setup. No generic whitespace split, arbitrary Transformers tokenizer, or original-model `tokenizer.json` should be substituted without verifying parity against the Qdrant FastEmbed artifact.

This preview describes what the configured E5 tokenizer would retain for the current logical passage input. It does not change indexing, split into multiple chunks, update already stored vectors, or establish that a separate truncation preview equals the ONNX model's resulting embedding. Current embedding execution uses FastEmbed's Qdrant ONNX artifact; the model card example uses Transformers and the original model. Both document the same model and 512-token input contract, but exact vector parity, artifact-revision parity, and all pooling/runtime implementation details are outside this research and remain unverified here.

## Dependency and version risks

- `fastembed>=0.9,<1` does not pin a specific FastEmbed release; v0.9.0 is the exact source version analyzed here. Do not assume later 0.x releases preserve its internal `token_count`, tokenizer setup, truncation defaults, or model artifact layout.
- `tokenizers` and `huggingface-hub` are transitives with broad upper bounds in FastEmbed v0.9.0. No repository lockfile freezes them.
- Model assets at a mutable `main` revision can change independently of the Python package. Record and pin the Qdrant Hub commit plus hashes for the tokenizer files. Revalidate when updating FastEmbed, `tokenizers`, Hub client, or tokenizer assets.
- The full count must use an untruncated encoding; the retained count must use a separately configured truncating encoding. Reusing FastEmbed's truncating `tokenizer` for both silently returns a capped count for long texts.
- FastEmbed's tokenizer loader uses private implementation APIs and requires model-config interpretation. A direct `Tokenizer.from_file()` using default settings can diverge on truncation, padding, added special tokens, or direction.
- Offset semantics should be covered with multilingual and Unicode fixtures. Special tokens may have `(0,0)` offsets; boundary detection must ignore them. Never calculate a cut using `len(token_string)`, joined token strings, or whitespace word positions.

## Limits and unresolved questions

- **Unresolved:** this research did not compare the actual `tokenizer.json` bytes from the Qdrant artifact against the upstream `intfloat` repository's tokenizer. Do not claim exact upstream-tokenizer identity.
- **Unresolved:** the official sources inspected do not promise a stable, public FastEmbed API that initializes only the tokenizer from arbitrary staged assets. The v0.9.0 internal loader is concrete evidence, not a public compatibility guarantee.
- **Unresolved:** exact codepoint behavior at edge cases involving normalized/decomposed Unicode should be proven against the installed `tokenizers` version; offset docs establish source slicing generally, not every normalization edge case.
- No actual end-user input was tokenized, and no numeric sample count or cut position is claimed.
- No live runtime, installed FastEmbed version, model cache, or embedding parity was inspected or tested.

## Recommended narrow scope and acceptance tests

Implement an opt-in, read-only preview for the selected document's exact `passage_input()` string. Use only the FastEmbed model's tokenizer/config assets, not ONNX weights; keep tokenizer initialization lazy and cache it separately. If the assets are unavailable or the compatible runtime is not installed, show an explicit unavailable state without falling back to whitespace estimation or initializing the embedding singleton. Display the model/artifact version source, full token count, retained count, retained source text, and explicit truncation state.

Acceptance checks for a later implementation:

1. An input of 511, exactly 512, and over 512 attended tokens reports the correct full count; retained counts are respectively unchanged, unchanged, and 512, with the truncation indicator only for the over-limit input.
2. Count and retained-text calculation use the exact current passage string, including `passage: ` and the same stripped text selection used by `document_text()`.
3. The boundary matches the source substring indicated by tokenizer offsets, including when the 512th token is in the prefix-adjacent text, in the middle of a word, or before punctuation/whitespace.
4. English, Korean, Japanese, mixed-script text, emoji, combining marks, repeated spaces, tabs, newlines, and punctuation produce token counts from the model tokenizer rather than a word splitter; source rendering is escaped and preserves line breaks.
5. Instrumentation proves tokenizer preview does not construct `TextEmbedding`, call `_model()`, start ONNX Runtime, or download any ONNX/weight/external-data file. It may fetch only the allowlisted tokenizer/config asset filenames.
6. Tokenizer assets resolve from a pinned immutable Qdrant model-repository revision, and a version/hash mismatch fails visibly instead of presenting stale counts as exact.
7. With FastEmbed missing, tokenizer files unavailable, or an asset download error, the UI stays responsive, shows a clear unavailable state, preserves cache-only document semantics, and makes no Elasticsearch request beyond the existing document fetch.
8. A parity fixture compares retained IDs/count and truncation offsets from the separate tokenizer path with FastEmbed v0.9.0's configured tokenizer for the same exact input, using an already available test fixture/model directory; the test must not fetch the 2.24 GB model.

## Sources (official/primary only; checked 2026-10-18)

- [intfloat multilingual-E5-large model card](https://huggingface.co/intfloat/multilingual-e5-large)
- [Qdrant FastEmbed ONNX model tree at pinned commit `ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b`](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/tree/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b)
- [Pinned tokenizer JSON](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/tokenizer.json)
- [Pinned tokenizer config](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/tokenizer_config.json)
- [Pinned model config](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/config.json)
- [Pinned special tokens map](https://huggingface.co/Qdrant/multilingual-e5-large-onnx/blob/ac6781cd1cf88b8306a536d7c9d18a5bd57cc14b/special_tokens_map.json)
- [FastEmbed v0.9.0 E5 model registry](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/pooled_embedding.py)
- [FastEmbed v0.9.0 ONNX model constructor](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/onnx_embedding.py)
- [FastEmbed v0.9.0 public `TextEmbedding` API](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/text_embedding.py)
- [FastEmbed v0.9.0 tokenizer loader](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/common/preprocessor_utils.py)
- [FastEmbed v0.9.0 tokenizer/count/ONNX path](https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/onnx_text_model.py)
- [FastEmbed v0.9.0 dependency metadata](https://github.com/qdrant/fastembed/blob/v0.9.0/pyproject.toml)
- [Hugging Face Hub single-file download API](https://huggingface.co/docs/huggingface_hub/en/package_reference/file_download)
- [Hugging Face Hub file download and immutable revision guide](https://huggingface.co/docs/huggingface_hub/en/guides/download)
- [Hugging Face Tokenizers `Encoding` IDs, masks, offsets, and truncation](https://huggingface.co/docs/tokenizers/main/api/encoding)
- [Hugging Face Tokenizers source-offset reference](https://huggingface.co/docs/tokenizers/python/latest/api/reference.html)
