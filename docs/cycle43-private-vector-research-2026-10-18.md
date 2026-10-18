# Cycle 43: private vector and hybrid search research

**Checked:** 2026-10-18  
**Scope:** Official-source research for adding account-private vector and hybrid search to a knowledge library described as currently Elasticsearch-backed BM25-only. This report does not establish application or endpoint compatibility.

## Directly documented facts

### Elasticsearch vectors and kNN

- Elastic's current `dense_vector` reference documents up to 4096 dimensions. A kNN query vector must have the same dimensions as its field. Dense vectors are single-valued and do not support aggregations or sorting.
- kNN uses approximate search. Increasing `num_candidates` tends to improve result accuracy; the documented maximum is 10,000. A `filter` inside the kNN query is a pre-filter. Other filters in the Query DSL tree are post-filters and can leave fewer than `k` results.
- Elastic Stack 9.0 indexes float vectors as `int8_hnsw` by default. The dense-vector field's default similarity is cosine for non-bit element types.

Sources: [Dense vector field type](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector), [kNN query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-knn-query).

### Hybrid search with RRF

- Elastic's retriever overview says the retriever API was added in Elasticsearch 8.14.0 and became generally available in 8.16.0.
- An RRF retriever combines at least two child retrievers. Its formula combines ranks, rather than requiring raw scores from different retrievers to share a scale. `rank_constant` defaults to 60. A larger `rank_window_size` can improve relevance at a performance cost.

Sources: [Retriever overview](https://www.elastic.co/docs/solutions/search/retrievers-overview), [RRF retriever reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/rrf-retriever).

### Index refresh and search visibility

- The default refresh parameter does not make a write immediately searchable. `refresh=wait_for` waits for a scheduled refresh; `refresh=true` forces a refresh and can add indexing and search cost.
- The documented default refresh interval is 1 second for Elastic Stack and 5 seconds for Elastic Cloud Serverless.

Source: [The refresh parameter](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/refresh-parameter).

### `multilingual-e5-large` and FastEmbed

- The Hugging Face model card reports 1024 dimensions, 24 layers, and truncation at 512 tokens. For retrieval, it requires the `query: ` prefix for queries and `passage: ` for passages, including non-English text. It warns that low-resource languages may see performance degradation. The card lists the model license as MIT.
- Qdrant's current FastEmbed supported-model listing reports `intfloat/multilingual-e5-large` at 1024 dimensions, 2.24 GB, MIT, with 512-token truncation and required query/document prefixes. The listed FastEmbed model uses the Qdrant ONNX export `Qdrant/multilingual-e5-large-onnx`, with `model.onnx` and an additional `model.onnx_data` file. The 2.24 GB value is the library's listed model size, not a guaranteed transfer size.
- FastEmbed documents ONNX Runtime inference. Its current `TextEmbedding` source documents `FASTEMBED_CACHE_PATH`, a default cache under the system temporary directory, and `local_files_only` for loading only cached model files. The current model-management source recognizes `HF_HUB_OFFLINE`.
- FastEmbed's generic `query_embed` and `passage_embed` methods delegate to regular embedding unless a model implements a specialized method. The current E5 `PooledEmbedding` class does not override these methods; therefore, callers should explicitly apply the required prefixes rather than assume those methods add them automatically.
- FastEmbed initialization may download model files. Once loaded, the documented inference path uses ONNX Runtime locally. The cited sources do not establish that a wider application has no other network traffic or telemetry.

Sources: [Hugging Face model card](https://huggingface.co/intfloat/multilingual-e5-large), [FastEmbed supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/), [FastEmbed overview](https://qdrant.github.io/fastembed/), [FastEmbed `TextEmbedding` source](https://raw.githubusercontent.com/qdrant/fastembed/main/fastembed/text/text_embedding.py), [FastEmbed base text-embedding source](https://raw.githubusercontent.com/qdrant/fastembed/main/fastembed/text/text_embedding_base.py), [FastEmbed E5 pooled model source](https://raw.githubusercontent.com/qdrant/fastembed/main/fastembed/text/pooled_embedding.py), [FastEmbed model-management source](https://raw.githubusercontent.com/qdrant/fastembed/main/fastembed/common/model_management.py).

## Design inferences

- Enforce account privacy from server-side identity. Apply the account restriction to both lexical and kNN branches in a hybrid request; keep the kNN restriction as a pre-filter. Do not rely on a browser-supplied account ID as the security boundary.
- Use an explicit 1024-dimension vector mapping and cosine similarity unless the selected embedding path is confirmed to normalize both passage and query vectors. Record the model artifact/version, prefixes, and chunking settings so re-embedding can be reproduced.
- Split long knowledge-library material into passages suitable for the model's 512-token limit. Long text sent as one input will be truncated by the model.
- Make first-run model download and cache behavior visible to novice users. The listed model size is 2.24 GB, and FastEmbed's default cache is under a temporary directory. Provide a stable configurable cache location and a clear cache-missing message for cache-only/offline use.
- Check the target Elasticsearch version before selecting the retriever API. RRF retrievers are GA from 8.16. This report does not verify the version or distribution in use.

## Compatibility and UX risks

- Elasticsearch version/distribution may not support the chosen mapping or RRF syntax. Verify the actual endpoint before implementation; no compatibility conclusion is made here.
- A dimension mismatch between the stored-vector field and query vector prevents a valid kNN request. Model changes or different prefix/chunk settings require regeneration of stored embeddings and renewed evaluation.
- Approximate kNN and default vector quantization can affect recall. Candidate counts and ranking behavior need to be measured on the target collection.
- Missing E5 prefixes can silently reduce retrieval performance. In current FastEmbed main, `query_embed` and `passage_embed` do not add E5 prefixes by default.
- First use may require a large model download. A temporary cache can be cleared or unavailable after restart, and cache-only mode cannot load a model that has not been staged.
- Local ONNX inference avoids requiring a hosted embedding inference service, but the cited library documentation does not prove zero network traffic for the complete application.

## Acceptance gates

1. **Endpoint/API behavior:** Confirm the target Elasticsearch version. On a disposable index, create an explicit vector mapping, index 1024-dimensional vectors, and verify kNN plus BM25-and-RRF requests. Confirm the expected write-to-search visibility behavior for the chosen refresh option.
2. **Privacy:** Prove that one account cannot retrieve another account's documents through BM25-only, vector-only, and hybrid search. Exercise requests that tamper with browser-supplied account parameters.
3. **Embedding plumbing:** Confirm that the chosen FastEmbed artifact produces 1024-dimensional vectors and that passage and query inputs receive the exact required prefixes. Record the library and model artifact identities.
4. **Retrieval quality:** Use a fixed, human-judged set from the private library to compare BM25, vector-only, and hybrid at the same result depth. Include exact identifiers, paraphrases, languages present in the corpus, long inputs, and negative cases. Agree on thresholds before tuning; measure Recall@k and ranking metrics, and check that hybrid does not harm important exact-match queries. Vendor benchmarks or a successful API response do not establish private-corpus quality.
5. **Operations:** Measure first-run download, warmed-cache and cache-only startup, disk/memory use, query latency, and when newly indexed content becomes searchable.

## Evidence boundary

- The deployed runtime model identity is **unverified**; it was not exposed during this research.
- No repository code was inspected for this research report, no code was run, and no Elasticsearch endpoint was checked. No application compatibility or semantic-retrieval quality claim is made.
- No tests were run.
