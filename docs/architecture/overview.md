# Architecture overview

## Product boundary

The application is a local, loopback-first Elasticsearch retrieval workbench. It searches existing Elasticsearch indexes and has a separate private-knowledge path. It provides retrieval evidence, judgments/evaluation, comparison, and selected export workflows. It is not a hosted SaaS, a production multi-tenant security product, an automatic crawler/reindexer for arbitrary shared indexes, or a generated-answer quality guarantee.

## Current source map

Structural exploration was requested through the `codebase-memory` skill. The skill was read, but the codebase-memory MCP tools were not exposed in this session; graph freshness and coverage therefore remain NOT RUN. This map is grounded in the named modules and inspected source/doc paths. It is not an exhaustive call graph.

| Area | Source | Responsibility visible in source |
|---|---|---|
| HTTP application and routes | `es_rag_tuner/server.py` | Local HTTP server, request routing, same-origin/loopback checks, auth and CSRF gates, JSON responses, app startup. |
| Accounts and sessions | `es_rag_tuner/auth.py` | SQLite-backed bootstrap/login/session/password/account operations and CSRF tokens. |
| Elasticsearch transport | `es_rag_tuner/es_client.py` | Connection validation, HTTP requests, shared/private index guards and local owner scopes. |
| Shared concepts and experiments | `es_rag_tuner/concepts.py` | Concept/query validation and persistence, judgments, preview/search, comparison, tuning, runs and profile export. |
| Private documents and search | `es_rag_tuner/knowledge.py` | Account-scoped local document/chunk lifecycle, Elasticsearch sync/search, and private evaluation helpers. |
| Retrieval strategies | `es_rag_tuner/retrieval.py`, `profile_runtime.py` | Lexical/vector/RRF retrieval and external search profile execution. |
| Embeddings and token previews | `es_rag_tuner/embeddings.py`, `token_preview.py` | Local embedding runtime and optional tokenizer preparation/preview. |
| Provider integration | `es_rag_tuner/ai_coach.py` | Optional Codex/Copilot readiness and session flows; must stay opt-in in CI and is not needed for default use. |
| Browser UI | `es_rag_tuner/web/{index.html,app.js,style.css}` | Single-page workbench UI and local API client. |
| Acceptance evidence | `tests/` | Offline Python, synthetic browser, and live Elasticsearch acceptance files; R01 separates their invocation and dependency boundaries. |

## Important boundaries

- Authentication/session state and CSRF tokens are local app concerns; Elasticsearch credentials are connection inputs and should not be persisted by default.
- `corpus.filter_fields` and request-supplied owner identifiers are not authorization. Private paths derive ownership from the authenticated server session and enforce their own owner/alias checks.
- Shared-index search and account-private knowledge search are distinct routes and data paths. A shared index must not silently become an account-private corpus.
- Existing acceptance/browser fixtures may use mocks/synthetic data. Their evidence supports only the contract/UI cases they execute, not live retrieval quality, production deployment, or answer accuracy.
- The default vector profile currently has model/dimension-specific behavior. R06 is responsible for generalization while retaining compatibility; do not assume another same-dimension model is interchangeable.

## Source fallback and recheck

On structural changes, first use the installed codebase-memory skill if its graph tools are available. If not, inspect the changed and relevant caller/source ranges directly and record the fallback. Before each stage, compare this overview to current code rather than treating the initial map as a permanent truth.
