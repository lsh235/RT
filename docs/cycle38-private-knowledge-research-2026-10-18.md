# Cycle 38: Private knowledge-document research

**Research checked:** 2026-10-18
**Requested model:** gpt-6-luna; **runtime identity: unverified**
**Scope:** Read-only source and official-documentation research. No code changes or tests were run.

## Decision summary

Recommend a first MVP using **per-account SQLite databases with FTS5** for private local knowledge documents. Begin with `.txt` and `.md`, store document metadata and token-counted chunks in the account's existing state database, and update the FTS index in the same transaction. This matches the existing account-state layout and avoids making local document privacy depend on Elasticsearch deployment licensing, shared-index filters, or user-supplied Elasticsearch credentials. Add embeddings later, after CRUD, search, ownership, and deletion behavior are covered by acceptance tests.

The isolation is an application boundary: accounts run under the same local process and OS user, which can access all account DB files. It is not OS-level separation or encryption at rest.

## Bounded repository source review

This review read selected paths and is not a complete structural audit.

- [retrieval.py](/home/sra235/2026/elasticsearch-rag/es_rag_tuner/retrieval.py) constructs lexical and vector searches. Existing filters are placed in the kNN `filter` field.
- [es_client.py](/home/sra235/2026/elasticsearch-rag/es_rag_tuner/es_client.py) builds the external Elasticsearch queries and has an allowlist of existing fields; the inspected query builder does not add an account-owner filter.
- [auth.py](/home/sra235/2026/elasticsearch-rag/es_rag_tuner/auth.py) and [concepts.py](/home/sra235/2026/elasticsearch-rag/es_rag_tuner/concepts.py) resolve local account state to separate SQLite files using the authenticated account context.
- [embeddings.py](/home/sra235/2026/elasticsearch-rag/es_rag_tuner/embeddings.py) optionally uses FastEmbed with `intfloat/multilingual-e5-large`. It prepares query/passage inputs and embeds existing `rag_chunk_text` or combined source fields; the inspected path does not create a persistent application-managed set of private document chunks.
- [app.js](/home/sra235/2026/elasticsearch-rag/es_rag_tuner/web/app.js) has a “chunk lab” preview based on word counts. It is illustrative UI, not the persisted chunking/indexing path.
- [pyproject.toml](/home/sra235/2026/elasticsearch-rag/pyproject.toml) declares FastEmbed as an optional dependency.

The UI accepts user-supplied Elasticsearch connection credentials, which are sent to the local app for outbound requests. It persists endpoint, index, and auth type in localStorage, not the password or API key. **Design inference:** local account scoping for saved workbench state does not secure an external Elasticsearch corpus if users provide credentials with broad rights or can access that cluster independently.

## Directly documented facts

### Elasticsearch access control and vector filtering

- Elasticsearch document-level security (DLS) is a subscription feature. Elastic describes it as intended for read-only privileged accounts; DLS does not apply to write APIs. Elastic documents limitations, including that DLS does not affect global relevance statistics and that aggregate queries may reveal information about restricted documents. Omitting a role query disables DLS for that index permission entry. See [controlling access at document and field level](https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/controlling-access-at-document-field-level) and [role management using Kibana](https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/kibana-role-management).
- Elasticsearch applies a filter supplied in the kNN query's `filter` during approximate search. Other Query DSL filters act as post-filters and can leave fewer than `k` results. See the [kNN query reference](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-knn-query).

**Design inference:** if future private documents are indexed in Elasticsearch, derive the tenant identity from the validated server session. Apply that identity in lexical filters and in the kNN prefilter, as well as in list, direct-read, count, and export operations. Client-supplied `owner_id` must not define access. DLS can provide a server-side read boundary where the deployment supports it, but the documented limits mean it should not be treated as the sole authorization design for CRUD or privacy-sensitive aggregates.

### SQLite FTS5 and storage behavior

- FTS5 `bm25()` uses lower numeric values for better matches; `ORDER BY bm25(table)` sorts best to worst. FTS5's default column-size data supports BM25 token-length calculations; omitting it saves space but may make token-size calculation slower. See [SQLite FTS5](https://www.sqlite.org/fts5.html).
- FTS5 updates and deletes may leave old full-text index entries in the DB until merge operations. FTS5 `secure-delete=1` removes old index terms at additional cost; SQLite's core `PRAGMA secure_delete=1` is also needed to address recovery from the DB file itself. See the FTS5 [secure-delete configuration](https://www.sqlite.org/fts5.html#the_secure_delete_configuration_option).
- SQLite permits multiple simultaneous readers but only one simultaneous write transaction per database. See [SQLite transaction behavior](https://www.sqlite.org/lang_transaction.html).
- SQLite's theoretical DB file maximum is much larger than a practical product quota. Real storage capacity and operational limits should be set by the application rather than inferred from that ceiling. See [SQLite implementation limits](https://www.sqlite.org/limits.html).

**Design inference:** per-account databases make owner scoping straightforward at the database-selection boundary, while a shared FTS index requires every query and result path to carry correct owner restrictions. A shared index may also let other tenants' documents influence corpus-level ranking statistics, even when those documents are filtered from returned rows. Set explicit per-file and per-account quotas. Decide the required deletion guarantees before enabling secure-delete because it changes cost and compatibility behavior.

### FastEmbed and the configured E5 model

- FastEmbed's retrieval guide describes query and passage embedding APIs and their use for retrieval. See [FastEmbed retrieval documentation](https://qdrant.github.io/fastembed/qdrant/Retrieval_with_FastEmbed/).
- The configured model card recommends `query:` and `passage:` prefixes for asymmetric retrieval tasks and states that long texts are truncated to at most 512 tokens. See the [multilingual-e5-large model card](https://huggingface.co/intfloat/multilingual-e5-large).

**Design inference:** chunking should count tokens using the model's tokenizer, including prefix and special-token budget, rather than count words. A default target in the 350–450 token range is a candidate to evaluate, not an upstream guarantee. Show boundaries and overlap in the UI and prevent silent truncation.

### Authorization guidance

- OWASP recommends permission checks on every request and checks for the particular object or functionality being accessed. See the [Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).
- OWASP's API1:2023 guidance says every endpoint receiving an object ID and acting on that object should check whether the logged-in user can perform that action on that object. UUIDs are not a substitute for authorization. See [Broken Object Level Authorization](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/).

These are design guidance sources, not empirical security evidence about this repository.

## Architecture options

| Option | Advantages | Costs and risks |
|---|---|---|
| **A. Per-account SQLite + FTS5** | Fits current account DB pattern; local keyword search; no dependency on Elasticsearch DLS licensing or shared-corpus filters. | App/process-level isolation only; same OS user/process can read every account DB. Requires quotas, backup handling, and explicit deletion policy. |
| **B. Shared SQLite + owner field + FTS5** | One DB simplifies centralized migrations and backups. | No SQLite row-level security; every query, list, snippet, count, export, and mutation must scope owner. Shared FTS statistics can be influenced by other tenants' content. |
| **C. Elasticsearch-backed private docs** | Can reuse existing search infrastructure and support lexical/vector retrieval at scale. | Needs trusted indexing credentials, owner filtering across all APIs, deployment-specific DLS/license decisions, and controlled index/write lifecycle. User-supplied broad credentials can bypass the app's intended boundary. |

## Recommended beginner-facing MVP

Implement Option A first:

1. Add, list, open, search, and delete `.txt`/`.md` documents from a simple “My documents” screen.
2. Preview extraction and token-counted chunk boundaries/overlap before saving. Show when input is rejected or too large.
3. Store document metadata and chunk rows in the authenticated account's existing SQLite state DB. Store FTS5 rows with the same owner DB and update them transactionally.
4. Return snippets and source-document links with keyword results. Keep semantic embeddings out of the first MVP or make them an optional later enhancement.
5. Set per-file byte limits and per-account storage quotas. Use restrictive file/directory permissions as defense against other OS users, while documenting that this does not protect from the local process or same OS account.
6. Choose whether deletion must resist DB-file recovery. If it does, test FTS5 secure-delete and SQLite core secure-delete behavior, including their performance and compatibility implications.

## Proposed measurable acceptance gates

1. **Tenant isolation:** two accounts with matching names/content cannot list, search, preview, read, update, delete, count, snippet, or export one another's documents/chunks, including with guessed IDs. Forged request `owner_id` cannot change the selected account. Define admin access explicitly; do not add an implicit admin bypass.
2. **Atomic indexing:** document, chunk, and FTS create/update/delete operations commit or roll back together. Injected failures leave no orphaned or partially searchable rows. Deleted docs stop appearing in search. Test backup/restore with WAL files accounted for.
3. **Chunking:** for Unicode and multilingual inputs, chunks cover the full accepted text, overlap matches configured token count, and each chunk stays below the model's 512-token maximum including prefixes/special tokens. No silent truncation.
4. **Input and resource limits:** test empty/malformed input, invalid UTF-8, maximum file size, account quota, FTS syntax metacharacters, and injection-shaped text. Requests over limits fail safely without indexing partial content.
5. **Search correctness:** verify FTS5 BM25 order (lower is better), snippets are escaped, and crafted query text cannot expose SQL or other documents.
6. **Concurrency:** concurrent fresh DB initialization and concurrent document creation do not create duplicate owner markers, orphan chunks, or cross-account rows. Confirm quota enforcement under concurrent writes.
7. **Browser and privacy:** verify upload, chunk preview, search, open-source, delete, and logout flows. Assert document content and credentials are absent from localStorage.
8. **Offline boundary:** local document CRUD/search succeeds with an unreachable Elasticsearch sentinel and mocked embeddings; verify these document operations make no external requests and do not use user-supplied ES credentials.

## Constraints and NOT RUN

- This is a decision brief, not an implementation or security assessment. No code was changed and no tests were run.
- No Elasticsearch endpoint, license entitlement, role configuration, or real corpus was available or checked.
- FastEmbed/model weights were not downloaded; tokenizer behavior, embedding quality, model dimensions, and performance were not exercised.
- SQLite FTS5 availability in packaged runtimes, disk growth, write contention, backup recovery, and secure-delete behavior were not tested.
- No threat model, penetration test, external security review, or OS-level isolation/encryption proof was performed.
- Official documentation was checked on 2026-10-18; deployment-specific Elasticsearch features and docs may differ by version or subscription.
