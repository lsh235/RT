# Architecture overview

## Product boundary

The application is a local, loopback-first Elasticsearch retrieval workbench. It searches existing Elasticsearch indexes and has a separate private-knowledge path. It provides retrieval evidence, judgments/evaluation, comparison, and selected export workflows. It is not a hosted SaaS, a production multi-tenant security product, an automatic crawler/reindexer for arbitrary shared indexes, or a generated-answer quality guarantee.

## Current source map

Structural exploration was requested through the `codebase-memory` skill. The skill was read, but the codebase-memory MCP tools were not exposed in this session; graph freshness and coverage therefore remain NOT RUN. This map is grounded in the named modules and inspected source/doc paths. It is not an exhaustive call graph.

| Area | Source | Responsibility visible in source |
|---|---|---|
| HTTP application and routes | `es_rag_tuner/server.py` | Local HTTP server, request routing, same-origin/loopback checks, auth and CSRF gates, JSON responses, app startup. |
| Protected POST route table | `es_rag_tuner/post_routes.py` | Resolves authenticated POST paths to feature handlers; transport checks, session/CSRF/role checks, and owner scope stay in `server.py`. |
| Accounts and sessions | `es_rag_tuner/auth.py` | SQLite-backed bootstrap/login/session/password/account operations and CSRF tokens. |
| SQLite migrations | `es_rag_tuner/storage.py` | Per-file `control` and `state` migration ledger, recognized-legacy validation, serialized transactional migrations, and retained pre-migration snapshots. |
| SQLite maintenance | `es_rag_tuner/db_maintenance.py` | Explicit local per-file backup and offline-confirmed restore with SQLite snapshots, schema/integrity validation, restrictive permissions, and atomic install. |
| Elasticsearch transport | `es_rag_tuner/es_client.py` | Connection validation, HTTP requests, shared/private index guards and local owner scopes. |
| Shared concepts and experiments | `es_rag_tuner/concepts.py` | Concept/query validation and persistence, judgments, preview/search, comparison, tuning, runs and profile export. |
| Private documents and search | `es_rag_tuner/knowledge.py`, `chunking.py` | Account-scoped source revisions, configurable offset-preserving chunks, persisted reindex jobs, staged private Elasticsearch generation publication, search, and private evaluation helpers. |
| Retrieval strategies | `es_rag_tuner/retrieval.py`, `profile_runtime.py` | Lexical/vector/RRF retrieval and external search profile execution. |
| Embeddings and token previews | `es_rag_tuner/embeddings.py`, `token_preview.py` | Local embedding runtime and optional tokenizer preparation/preview. |
| Provider integration | `es_rag_tuner/ai_coach.py` | Optional Codex/Copilot readiness and session flows; must stay opt-in in CI and is not needed for default use. |
| Browser UI bootstrap | `es_rag_tuner/web/{index.html,app.js,style.css}` | Single-page workbench UI; `app.js` remains the classic-script bootstrap and loads its same-origin feature modules before auth initialization. |
| Browser API client | `es_rag_tuner/web/api-client.js` | Dependency-injected `POST` request helper; preserves the existing status and user-facing `error` behavior and exposes an optional stable error code. |
| Positive-target-miss feature | `es_rag_tuner/web/cycle44-positive-target-misses.js` | Isolated Cycle 44 scope fingerprinting, stale-report checks, rendering, and exact-document handoff behavior. |
| Acceptance evidence | `tests/` | Offline Python, synthetic browser, and live Elasticsearch acceptance files; R01 separates their invocation and dependency boundaries. |

## Important boundaries

- Authentication/session state and CSRF tokens are local app concerns; Elasticsearch credentials are connection inputs and should not be persisted by default.
- `corpus.filter_fields` and request-supplied owner identifiers are not authorization. Private paths derive ownership from the authenticated server session and enforce their own owner/alias checks.
- Shared-index search and account-private knowledge search are distinct routes and data paths. A shared index must not silently become an account-private corpus.
- Account-private reindexing rebuilds local chunks from authoritative SQLite documents and stages a new owner-specific Elasticsearch generation. The previous alias remains selected until refresh and expected identity/count checks pass; cancelled, failed, or interrupted jobs require inspection or explicit retry. This is an indexing lifecycle guarantee, not representative retrieval-quality evidence.
- Existing acceptance/browser fixtures may use mocks/synthetic data. Their evidence supports only the contract/UI cases they execute, not live retrieval quality, production deployment, or answer accuracy.
- Protected POST dispatch is a route table, while loopback/Host/Origin, cookie/session, CSRF, role, and owner-scope decisions remain at the HTTP boundary. Domain modules continue to own feature operations.
- SQLite schema versions are recorded per database file. The base file contains both control data and primary-account state; each secondary account has a separate UUID-named state file. Explicit backup/restore handles one file at a time, so several account files do not share a cross-file point-in-time transaction. Elasticsearch indices are excluded.
- During a schema upgrade, the migration runner retains a mode-`0600` SQLite backup snapshot beside the source file. Restore is an offline local CLI operation and validates a recognized workbench schema before replacing its destination.
- The default vector profile currently has model/dimension-specific behavior. R06 is responsible for generalization while retaining compatibility; do not assume another same-dimension model is interchangeable.

## Source fallback and recheck

On structural changes, first use the installed codebase-memory skill if its graph tools are available. If not, inspect the changed and relevant caller/source ranges directly and record the fallback. Before each stage, compare this overview to current code rather than treating the initial map as a permanent truth.
