# E5 input visibility and chunking: research note

**Cycle:** 7
**Checked:** 2026-10-18
**Model used:** GPT-6 Luna

## Research question

How can the workbench make the input to its existing E5 document embedding easier to inspect without confusing that input with a hypothetical whitespace-based chunking preview or expanding this cycle into an ingestion migration?

## Official source findings

### `semantic_text` passage chunking

- **Source:** Elastic, “Semantic text field type reference,” https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/semantic-text-reference
- **Checked:** 2026-10-18
- **Fact:** `semantic_text` can automatically create passages and embeddings when text exceeds the configured inference input capacity. Searches consider a document's passages and use the most relevant passage to compute its score. Chunk offsets point back into the original input. Pre-chunked text arrays can also be supplied.
- **Limit:** This behavior belongs to `semantic_text` and its configured inference endpoint; it does not describe the workbench's current local E5 call. Chunking setting changes apply to existing documents only after reindexing. With chunking disabled, an over-limit input may fail for some services or be truncated by Elastic's `elastic`/`elasticsearch` services.

### Inference endpoint chunking

- **Source:** Elastic, “Default inference endpoints, adaptive allocations, and chunking,” https://www.elastic.co/docs/explore-analyze/elastic-inference/inference-api
- **Checked:** 2026-10-18
- **Fact:** Elastic describes chunking as splitting input to fit the selected model's input capacity and documents sentence- and word-based strategies. Sentence chunking aims to preserve sentence boundaries and supports a sentence overlap setting.
- **Limit:** Chunk limits and defaults depend on the selected endpoint/model. A word-count setting does not guarantee a token count for E5.

### Reindexing into a derived target

- **Source:** Elastic, “Reindex documents,” https://www.elastic.co/docs/api/doc/elasticsearch/v8/operation/operation-reindex
- **Checked:** 2026-10-18
- **Fact:** Reindex copies from a source to a different destination; the destination should be configured before the request, and source mappings/settings are not copied automatically. A request may invoke an ingest pipeline. Default destination behavior can overwrite documents with matching IDs.
- **Limit:** Reindexing is not a validation-and-publish transaction. Conflicts and ID collisions require explicit handling, and the destination must be checked for completeness.

### Ingest pipeline behavior and errors

- **Source:** Elastic, “Elasticsearch ingest pipelines,” https://www.elastic.co/docs/manage-data/ingest/transform-enrich/ingest-pipelines
- **Checked:** 2026-10-18
- **Fact:** Ingest pipelines process one document at a time and can transform or drop it, but cannot split one input document into multiple indexed documents. Existing documents need reindexing or update-by-query to pass through a pipeline.
- **Limit:** A one-document pipeline is not a one-to-many chunk-document mechanism. Pipeline failure handling does not make a larger derived-index build atomic.

### Bulk result handling

- **Source:** Elastic, “Bulk index or delete documents,” https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-bulk
- **Checked:** 2026-10-18
- **Fact:** The Bulk API response contains an `errors` flag and per-item results; `errors: true` means one or more operations failed.
- **Limit:** An HTTP-success response alone does not show that every item succeeded; callers must inspect item-level outcomes.

### E5 input limit and prefixes

- **Source:** `intfloat`, “multilingual-e5-large” model card, https://huggingface.co/intfloat/multilingual-e5-large
- **Checked:** 2026-10-18
- **Fact:** The model card says long texts are truncated to at most 512 tokens. Its example tokenizes with `max_length=512` and `truncation=True`. It instructs retrieval inputs to use `query: ` and `passage: ` prefixes, including for non-English text, and warns that omitting them degrades performance.
- **Limit:** The model card does not specify the best chunk size or overlap for this repository. It does not provide a token count for any particular document passed through this application.

## Repository observations

At the current implementation, `es_rag_tuner/embeddings.py` sets `MODEL_NAME` to `intfloat/multilingual-e5-large`. `document_text()` prefers the stripped `rag_chunk_text` value and otherwise assembles text from supported issue fields. `embed_texts()` strips each text again, prefixes it with the requested role, and calls the model's `embed()` method. The index-vectorization path calls this with role `passage` (`es_rag_tuner/indexing.py`). Thus, for a selected document, the logical text input passed to the embedding model is exactly `passage: ` followed by the stripped result of `document_text()`.

This exact logical input is distinct from any whitespace-based chunk split shown as a what-if preview. The preview's chunk boundaries are hypothetical and are not evidence that the current embedding call tokenizes or indexes those separate pieces. The 512-token figure is the model card's limit; this note does not estimate token counts for repository documents or claim how many tokens any particular input consumes.

## Product inference and selected narrow option

For this cycle, show a read-only view of the exact logical E5 input for the selected document, including the `passage: ` prefix, and label it as the current embedding input. If the interface also shows a whitespace-based split, label it explicitly as a hypothetical preview, visually separate from the exact input, and avoid implying that those parts were separately embedded. State the model's documented 512-token limit without inventing a per-document token count.

This is an inspection aid, not a claim that the current input is truncated or that a different split would improve retrieval. The source facts support displaying the model limit and prefix convention; the usefulness of exposing the current input is a product inference.

## Scope and risk boundary

Full derived-index ingestion is materially broader than input visibility. It would require a destination schema and population/reindex strategy, model-compatible chunking, stable mapping from chunks back to source documents, item-level failure handling, and checks for completeness, collisions, and overwrite behavior. Elasticsearch's ingest pipeline cannot itself fan one source document out into multiple chunk documents. `semantic_text` may manage passages within a document when a compatible inference endpoint is configured, but that is a distinct indexing/query path and chunk-setting changes require reindexing existing records. These migration and operational risks are why this note records derived-index approaches as context only, not as the selected Cycle 7 implementation.
