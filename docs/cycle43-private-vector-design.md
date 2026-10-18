# Cycle 43: optional private vector and hybrid retrieval

## Purpose and boundary

The account-private knowledge library keeps SQLite as its source of truth. Ordinary Elasticsearch sync remains BM25-only and does not import FastEmbed, tokenize content, or download a model. A separate user action can build an account-specific E5 vector generation. Search keeps the configured shared-index results and the account-private results in separate lanes. Private text is not passed into AI context, exports, or error messages by this feature.

This is a loopback application using one shared Elasticsearch credential. `owner_id` filters and server-authenticated account scope provide application-side separation; this is not Elasticsearch document-level security, protection against direct use of that credential, or evidence of production multi-tenant readiness. It also does not establish semantic retrieval quality.

## User setup and consent

Install the optional dependencies with:

```sh
python -m pip install -e '.[private-vector]'
```

The normal **BM25 sync / retry** action needs no semantic extra or model. The separate **vector sync** action explains that it may cache the pinned tokenizer files (up to about 18 MB) and the `intfloat/multilingual-e5-large` model (about 2.24 GB). The browser confirmation is sent as `allow_model_download: true`; the API rejects vector sync without it. Status checks use local-only cache reads. No token or model downloads occur from ordinary BM25 sync/search.

If the optional dependencies are missing, or tokenizer preparation, model loading, embedding, or Elasticsearch vector mapping fails, vector sync reports an actionable failure and does not publish a new alias generation. BM25 remains available. The prior alias remains selected if staging or publication fails.

## Vector recipe and completeness

The recorded generation recipe is:

- Model: `intfloat/multilingual-e5-large`, 1024 dimensions.
- The installed FastEmbed package version is recorded in SQLite state and mapping metadata so a package-version change marks the generation stale.
- Query input: exact `query: ` prefix; passage input: exact `passage: ` prefix.
- Mapping: indexed `dense_vector`, `dims: 1024`, cosine similarity.
- Tokenizer: pinned `Qdrant/multilingual-e5-large-onnx` assets at the revision recorded in `token_preview.py`, with asset hash checks and 512-token context.
- Source chunks: existing BM25 chunks are unchanged. The vector generation divides each chunk into contiguous, non-overlapping source slices using tokenizer offsets. Each exact role-prefixed passage is independently checked at 512 tokens or fewer. Stored Python-codepoint start/end offsets and passage ordinal make the split reproducible. No source character is omitted from the indexed passage texts.

The generation records the recipe in its mapping metadata and account SQLite state. Status compares both copies to the active recipe before allowing vector search. The sync stages a new generation, checks every Bulk item, refreshes and verifies count visibility, confirms the source fingerprint has not changed, and only then swaps the account alias. Failures attempt to restore the previous alias.

The implementation does not hash or pin the downloaded ONNX/model artifact bytes. Recording the FastEmbed version and model name does not prove byte-identical model files or embeddings across machines or later downloads.

## Search behavior

BM25 always searches the private alias with a server-derived owner filter. Vector search embeds the query locally and puts the authenticated owner filter inside the kNN request as a pre-filter. Hybrid search performs separately owner-filtered BM25 and vector requests, then applies local reciprocal-rank fusion (constant 60) inside the private corpus. It does not add BM25 and vector scores. None of these private results are merged with shared-index results.

Before and after private searches, the server checks the account alias, local/synced fingerprint state, active recipe, and vector mapping where needed. A stale, empty, unavailable, or mismatched vector generation returns no private hits. In vector and hybrid modes, shared retrieval and private retrieval run independently: if the shared vector request fails, the response marks the shared lane unavailable and still attempts the authenticated private lane. BM25 keeps its prior shared-search behavior. The `code_rag` workflow also keeps its existing shared-vector readiness gate.

## Limits

The app uses the same configured Elasticsearch credential for account aliases. Any direct holder of that credential can access those indexes. Private search does not send private text to the AI coach, but the index itself is still visible to Elasticsearch operators and credential holders. Vector and hybrid retrieval are optional candidates, not a quality claim. Corpus-specific relevance needs a separate evaluation with trustworthy judgments.
