# Cycle 38 private knowledge MVP

Cycle 38 adds private, account-owned text documents for local lexical search. This is a lexical-only SQLite FTS5/BM25 MVP. It does not send a document to Elasticsearch, create semantic vectors, use concept evaluation or tuning, or add documents to AI context.

## Account boundary and storage

All endpoints are authenticated POST JSON routes. The existing session, same-origin, and CSRF checks apply. Storage resolves through the authenticated account's existing state database and preserves its `state_owner` ownership marker. The request cannot choose an account or owner. Administrator accounts use the same rule and see only their own documents.

This is an in-app per-account isolation boundary. It is not intended to protect one account from another OS user or a process with access to the application data directory. SQLite deletion does not guarantee secure erasure; WAL files, filesystem snapshots, and backups may retain prior content. Operators must manage backups and retention separately.

The server accepts text and a user-provided source label. It does not receive or open local filesystem paths. Content is not logged or included in validation error messages.

## Limits and chunking

- Content: non-empty UTF-8 text, at most 1 MiB per document.
- Account: at most 20 MiB of current document content and 100 documents.
- Title and source label: at most 200 Unicode code points each.
- Chunks: at most 1,800 Unicode code points, with 200 code points of overlap; offsets are half-open Unicode code-point offsets into the original content.
- Search: 1–20 results, default 10. Search text is tokenized into literal Unicode terms before FTS5 matching; user-entered FTS operators are not executed.

Create/update replaces document, chunk, and FTS rows in a single SQLite write transaction. Delete removes those rows transactionally. Schema setup uses `CREATE ... IF NOT EXISTS`, making initialization repeatable for existing account databases.

## API

All request/response bodies use JSON. `document_id` is an opaque identifier returned by save/list. Foreign and unknown IDs return the same 404 response. Every database lookup is scoped by the owner-resolved state database; no owner field is accepted as a scope selector.

### `POST /api/knowledge/list`

Body: `{}`. Returns `{ "documents": [...] }` with metadata only: `document_id`, `title`, `source_label`, `content_bytes`, `created_at`, and `updated_at`.

### `POST /api/knowledge/preview`

Body: `{ "title": "...", "source_label": "...", "content": "..." }`. `source_label` is optional; if omitted or empty, it is stored as an empty string. Returns validated metadata and deterministic chunks without saving.

### `POST /api/knowledge/save`

Body uses the preview fields. `source_label` is optional; if omitted or empty, it is stored as an empty string. Omit `document_id` to create; include an owned `document_id` to replace its content and chunks. Returns `{ "document": metadata, "chunks": [...] }`. A foreign or unknown ID returns 404.

### `POST /api/knowledge/get`

Body: `{ "document_id": "..." }`. Returns metadata, full content, and ordered chunks for an owned document. Foreign and unknown IDs both return 404.

### `POST /api/knowledge/delete`

Body: `{ "document_id": "..." }`. Deletes an owned document and its local index rows. Foreign and unknown IDs both return 404.

### `POST /api/knowledge/search`

Body: `{ "query": "...", "limit": 10 }`. `limit` must be an integer from 1 to 20. Returns FTS5-ranked chunks with `document_id`, title, source label, chunk ID, chunk text, a short excerpt, and the BM25 score. This route uses no Elasticsearch connection or supplied Elasticsearch credentials.

## Scope limits

The MVP does not provide semantic/vector search, Elasticsearch indexing or DLS, shared corpus access, concept evaluation/tuning, or AI-context integration. It does not claim multi-process or multi-OS-user data security. Local tests and implementation review do not establish production security or secure deletion.
