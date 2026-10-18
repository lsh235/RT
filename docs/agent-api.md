# Novice retrieval and AI coach API contract

This document extends the existing local workbench API. The browser UI and API are loopback-only. Except for `GET /api/health` and `GET /api/auth/session`, every API route requires an active local account session. The initial deterministic workflow must work when both AI providers are unavailable. Existing concept BM25, vector/hybrid search, code-RAG, and concept judgment behavior remain available.

## Local account authentication and saved-state ownership

### Bootstrap and recovery

There is no unauthenticated HTTP bootstrap or public signup route. Create the first administrator from the service environment with `python -m es_rag_tuner auth bootstrap-admin` (or `es-rag-workbench auth bootstrap-admin`). The CLI prompts for username, display name, and password; password and confirmation are read through `getpass`, never through command-line arguments. Bootstrap is one-time. It transactionally validates legacy concept/version/judgment/run table schemas, applies the compatible `judgments.query_fingerprint` addition if needed, assigns the existing saved-state database to the initial administrator, and records the `legacy_state_claim` owner marker. An incomplete schema or an inconsistent prior marker fails closed. Existing saved rows are preserved.

For administrator credential recovery on the local machine, run `python -m es_rag_tuner auth reset-admin-password`. It prompts for an enabled administrator username and the new password twice using `getpass`; it revokes all sessions for that administrator. This is a local service-administrator recovery operation, not an HTTP endpoint. It does not reactivate a disabled account.

Passwords must be JSON strings and contain 15–1024 characters; spaces and Unicode are preserved. The minimum is the app's conservative policy for local password-only authentication without MFA, not a universal strength or compliance claim. Passwords are stored as Argon2id hashes with a per-password salt. Username and display name must also be strings; usernames are trimmed, lowercased, and limited to 3–64 letters, digits, `.`, `_`, `-`, and `@`; display names are trimmed and limited to 1–100 characters. Password values are never returned or logged.

### Session, cookie, and request checks

`GET /api/auth/session` is public and returns one of these shapes:

- Before the first administrator exists: `{ "configured": false, "authenticated": false }`.
- Configured, logged out: `{ "configured": true, "authenticated": false, "csrf_token": string }`. The response also sets `es_rag_login_nonce` with `HttpOnly; SameSite=Strict; Path=/` and `Max-Age=600`; it is used only for login CSRF validation.
- Authenticated: `{ "configured": true, "authenticated": true, "user": { "id": string, "username": string, "display_name": string, "role": "admin"|"user" }, "csrf_token": string }`.

All POST requests, including login and read-only search routes, must send the `Origin` header for the exact same `http://localhost|127.0.0.1|[::1]:<server-port>` origin and a matching loopback `Host` including the server port. Missing or mismatched values are rejected with HTTP 403. An authenticated POST must include `X-CSRF-Token` with the session-bound token returned by `/api/auth/session` or login. Login instead uses the pre-auth token and nonce cookie from the configured logged-out session response. No API accepts an owner ID or database path to select saved state.

Successful login sets `es_rag_session` as an opaque cookie with `HttpOnly; SameSite=Strict; Path=/` and `Max-Age=43200` (12 hours). Session identifiers are hashed in server-side SQLite. Logout, password change, account disable, and administrator password reset revoke the affected sessions. This HTTP loopback server cannot set the cookie's `Secure` attribute. Keep it bound to loopback; the cookie and local account boundary do not make remote or reverse-proxy deployment safe. Plain HTTP also does not encrypt traffic from other local processes. The existing Elasticsearch connection and index remain request-selected; this feature isolates local saved workbench state only and does not provide private-document CRUD, owner-forced filters, or document-level tenancy over external Elasticsearch corpora.

### Authentication API

| Route | Request | Success | Error statuses |
| --- | --- | --- | --- |
| `POST /api/auth/login` | `{ "username": string, "password": string }` | HTTP 200 `{ "configured": true, "authenticated": true, "user": user, "csrf_token": string }`; sets the session cookie | 401 generic invalid credentials or field types; 403 invalid Origin or login CSRF; 503 before bootstrap |
| `POST /api/auth/logout` | `{}` | HTTP 200 `{ "authenticated": false }`; clears the cookie | 401 unauthenticated; 403 Origin/CSRF |
| `POST /api/auth/password/change` | `{ "current_password": string, "new_password": string }` | HTTP 200 `{ "changed": true, "authenticated": false }`; revokes all user sessions and clears the cookie | 400 validation; 401 current password mismatch; 403 Origin/CSRF; 401 unauthenticated |

Login failures use one generic message for unknown, disabled, throttled, or incorrect credentials. A per-username progressive delay is bounded and expires; it does not permanently lock an account. There is no password or hash in a response or access log. The server suppresses default HTTP request-target logging so query strings cannot enter the access log.

### Administrator account management

Every route below requires an enabled administrator session, exact same-origin `Origin`/`Host`, and session CSRF header. Admins manage accounts but cannot read another account's concepts, judgments, versions, or runs.

| Route | Request | Success | Error statuses |
| --- | --- | --- | --- |
| `POST /api/admin/accounts/list` | `{}` | HTTP 200 `{ "accounts": [{ "id": string, "username": string, "display_name": string, "role": "admin"\|"user", "created_at": number, "enabled": boolean }] }` | 401 unauthenticated; 403 non-admin or Origin/CSRF |
| `POST /api/admin/accounts/create` | `{ "username": string, "display_name": string, "password": string }` | HTTP 201 `{ "account": user }`; creates a regular user with an isolated state database | 400 invalid values/types; 401 unauthenticated; 403 non-admin or Origin/CSRF; 409 duplicate username |
| `POST /api/admin/accounts/update` | `{ "user_id": string, "display_name": string }` | HTTP 200 `{ "account": user }` | 400 invalid values/types; 401 unauthenticated; 403 non-admin or Origin/CSRF; 404 unknown user |
| `POST /api/admin/accounts/disable` | `{ "user_id": string }` (optional `"disabled": true` is accepted) | HTTP 200 `{ "disabled": true }`; revokes the target's sessions | 400 invalid fields; 401 unauthenticated; 403 non-admin or Origin/CSRF; 404 unknown user; 409 if this would disable the last enabled administrator |
| `POST /api/admin/accounts/password/reset` | `{ "user_id": string, "new_password": string }` | HTTP 200 `{ "reset": true }`; revokes the target's sessions | 400 weak/malformed password or self-reset; 401 unauthenticated; 403 non-admin or Origin/CSRF; 404 unknown/disabled target |

Use `/api/auth/password/change` for the current account; the admin reset route rejects self-reset. Disabling is reversible only through a later administrative feature (not included here); accounts are not deleted. The first administrator cannot be disabled while it is the last enabled administrator.

Saved-state isolation is enforced by the server's authenticated user ID, which is resolved from the session store. The first administrator owns the pre-existing state DB; each later account's path is derived from its UUID stored in the account table, and the DB contains a matching owner marker. A mismatched marker fails closed. Admin role does not bypass that owner boundary. AI sessions and jobs also record the owner ID and return 404 for cross-account IDs.

## Quick start and human feedback

### `POST /api/document`

Request: `{ "connection": {...}, "index": string, "id": string }`. The successful document response preserves `_source` and additively includes `embedding_input: { "text": string, "source": "rag_chunk_text|structured_fields|empty" }`. This describes the exact passage string used by vectorization: a nonempty `rag_chunk_text` is preferred and trimmed at its outer edges; otherwise the text uses the same labeled structured fields and comment bodies as document text, excluding comment authors. Nonempty text has the `passage: ` prefix. Empty input is `{ "text": "", "source": "empty" }` and is skipped by vectorization. The helper computes this value from the already-fetched `_source`; it does not load the embedding model or make another Elasticsearch request. The source-selection helper is covered by a mocked HTTP acceptance test; no Elasticsearch write is performed by this endpoint.

### `POST /api/concepts/quickstart`

Request: `{ "connection": {...}, "index": "existing-index", "query": "optional first search" }`.

Returns `{ "index": string, "fields": [...schema field objects...], "suggested_text_fields": [string], "suggested_title_field": string|null, "suggested_filter_fields": [string], "sample_documents": [{"_index": string, "_id": string, "source": object}], "warnings": [string], "warning_codes": [string] }`. Suggestions are mapping/name heuristics, not semantic guarantees. The endpoint only reads mappings and a bounded sample; the user confirms fields and filters before saving a concept. It does not create, update, or delete Elasticsearch data.

### `POST /api/concepts/ensure-query`

Request: `{ "concept_id": string, "query": string, "split": "train"|"validation" }`. Creates or reuses a stable query ID for the exact saved concept query text and returns `{ "concept_id": string, "query_id": string, "query": string, "split": string }`. Exact text is required for stable judgment identity. Rewording a saved query creates a new identity; prior judgments are not silently moved.

Use the returned `query_id` with existing `/api/concepts/preview` and `/api/concepts/judge`. A graded 1–3 document is positive feedback; grade 0 is judged irrelevant; null remains unjudged. Pins only affect visible placement. Only a human action may create a grade or pin.

### `POST /api/concepts/tune/readiness`

Request: `{ "concept": concept }`. The aggregate-only success response is `{ "eligible": boolean, "reason_code": "train_positive_available|train_positive_required", "counts": { "training_queries": number, "training_graded": number, "training_positive": number, "training_graded_queries": number, "training_positive_queries": number, "validation_queries": number, "validation_graded": number, "validation_positive": number, "validation_graded_queries": number, "validation_positive_queries": number, "stale": number }, "scope": "label_readiness_only" }`. `training_queries` and `validation_queries` count query entries in the submitted concept's current query list by split, including entries with no labels; the request can reflect unsaved edits, so these denominators are not guaranteed to be persisted. Graded and positive document counts include only non-stale ratings 0–3 and 1–3 respectively; graded-query and positive-query counts deduplicate query IDs with at least one qualifying document. Stale judgments are excluded from every split count and reported separately. Legacy judgments without a saved query fingerprint are treated as stale. A missing database, missing `judgments` table, or malformed table lacking `concept_id`, `query_id`, or `rating` returns HTTP 503 rather than a confirmed all-zero result; a valid initialized database with a complete but empty `judgments` table returns confirmed zero counts. `eligible` means only that at least one current positive training label exists, matching the tune label gate. This route reads local judgment state without Elasticsearch or connection data and does not mutate the database. It returns no document IDs or reasons. Query counts describe label coverage, not judgment representativeness or retrieval quality; there is no minimum query-count requirement. Eligibility does not guarantee Elasticsearch connectivity, successful tuning, or improved retrieval quality; `/api/concepts/tune` remains authoritative when execution is requested.

### Plain-language outcome

`/api/concepts/tune` adds `plain_summary: {"headline": string, "details": [string], "scope": string, "caveats": [string] }`. The headline leads with how many explicitly positive-graded documents appeared in the organic top-k before and after tuning; details then show query coverage and nDCG. Each metric split reports `positive_judged_count`, `relevant_found_at_k`, and `queries_with_positive_judgments`, plus the per-query `relevant_found_at_k` counts. It describes observed train and validation changes, per-query regressions, number of rated queries/documents, judged coverage, and whether validation labels exist. It must not call scores probabilities or claim generalization without validation. This is deterministic wording over returned metrics; AI interpretation is separate.

## Missing-document diagnosis

### `POST /api/concepts/diagnose`

Request: `{ "connection": {...}, "concept": concept, "query": "optional", "query_id": "optional saved query ID", "document_index": "exact _index", "document_id": "exact _id" }`.

At least `query` or `query_id` is required; when both are present their text must match. The exact target index and ID are required so aliases/backing-index identity is preserved. The route fetches only that document and runs at most four targeted Explain probes: baseline and concept-expanded query, plus filter-free or exclusion-free probes only when needed to distinguish those causes.

Returns `{ "document_index": string, "document_id": string, "query_id": string|null, "classification": "baseline_match|expansion_match|filtered_out|excluded|matches_below_display_window|matches_outside_candidate_pool|no_selected_field_value|no_selected_field_match|inconclusive|document_not_found", "probes": [{"name": string, "matched": boolean|null, "score": number|null, "explanation": object|null}], "selected_field_presence": [{"field": string, "has_value": boolean}], "next_steps": [string], "warnings": [string], "warning_codes": [string] }`. `explanation` is the Elasticsearch Explain response for a single document; render it as a diagnostic aid, not a semantic verdict. `matches_outside_candidate_pool` is returned only after a search with the actual candidate filters confirms the exact document is outside the configured pool; `matches_below_display_window` means it is in the pool but below the displayed `size`. Explain `matched: true` alone is insufficient to classify a missing preview result. Unsupported permissions, stale mappings, or probe errors return `inconclusive` with a specific warning rather than a guessed cause. The endpoint is read-only and does not assign a grade.

The Explain API requires only `read` index privilege. Analyzer-token inspection is not part of the default diagnostic: Elasticsearch documents the Analyze API with `index` privilege, which may exceed a user's read-only grant.

## Versioned profiles and application handoff

Every successful `/api/concepts/save` creates an immutable concept version. Its response adds `version_id` and `version_number`; the current concept ID remains stable. A restore creates a new current version copied from the chosen historical version; it never deletes history.

### `POST /api/concepts/versions`

Request: `{ "concept_id": string, "limit": 50 }`. Returns `{ "versions": [{"version_id": string, "version_number": number, "created_at": string, "concept_fingerprint": string, "concept": concept}] }` newest first.

### `POST /api/concepts/restore`

Request: `{ "concept_id": string, "version_id": string }`. Returns `{ "concept": restoredConcept, "version_id": string, "restored_from": string }`. The restored copy is saved as a new version, preserving the previous current profile and the selected source version.

### `POST /api/concepts/export`

Request: `{ "connection": {...request-scoped existing connection fields...}, "concept_id": string, "version_id": "optional; defaults to current" }`. The route reads the current mapping to validate selected searchable/filter fields and to generate nested-query wrappers. Credentials are used only for that request and never appear in the artifact. Returns `{ "format": "es-rag-profile-v1", "profile": {"concept": concept, "version_id": string, "fingerprint": string, "mapping_fingerprint": string}, "runtime": {"python": "from es_rag_tuner.profile_runtime import search_profile; search_profile(connection, profile, query)", "search_template": {"lang": "mustache", "source": string}, "example_params": object, "example_search_body": object, "install_template_example": string, "invoke_template_example": string}, "warnings": [string] }`. Both generated Search API forms include the saved metadata filters and mapping-aware nested clauses. The export strips all connection credentials, judgment reasons, source-document content, local paths, and provider/account identifiers. It includes the selected version and mapping fingerprints. It is a generated handoff artifact only; export does not install a stored script or change cluster state.

The Python `search_profile(connection, profile, query)` helper is the supported runtime path for Python consumers. It uses the same validated BM25 concept query builder as preview and returns organic hits. Other consumers can use the emitted ordinary Search API body or install the optional Mustache search template themselves. Parity is defined by result `_index`/`_id` ordering for the same index snapshot, query, filters, and profile version. The workbench does not deploy or activate an external application's profile. Applications should retain the previous version ID and verify their own held-out queries before rollout.

### `POST /api/concepts/runs/export`

Request: `{ "concept_id": string, "run_id": string }`. Both values must identify a saved concept and a persisted run belonging to that concept; an unknown concept or mismatched/unknown run returns 404. This is a local SQLite read only: it requires no Elasticsearch connection, performs no live query, and writes nothing to Elasticsearch. Returns `{ "format": "es-rag-experiment-run", "version": 1, "exported_at": string, "run": {"run_id": string, "concept_id": string, "created_at": string, "kind": "preview|tune", ...}, "completeness": {"truncated": false, "judgment_count": number, "output_entry_count": number}, "limitations": [string] }`. The `run` object contains the selected run's stored input/output snapshots, saved concept and query/split information, judgments, baseline/candidate or baseline/tuned metrics, ranked document IDs/source hashes, and reproducibility fingerprints. The export reads the exact run row and does not use the summary/truncated `/api/concepts/runs` response. It projects only documented run fields and excludes connection credentials/auth fields, provider/account identity, local/database paths, and full fetched source document bodies. It retains user-authored query text and judgment reason/note text; common credential patterns are redacted, but arbitrary sensitive content in free text cannot be reliably detected, so review the artifact before sharing it. IDs and `source_sha256` values are retained. `completeness.truncated` is false because this endpoint exports the selected run's stored snapshot in full; counts describe the included judgment rows and output entries. The artifact describes measured evidence at the time of the run and does not establish current index state, semantic relevance, or downstream RAG answer quality. This is separate from `/api/concepts/export`, whose existing profile handoff contract is unchanged.

## AI coach

AI uses the user's existing Codex subscription or GitHub Copilot subscription through their documented SDK sign-in. No provider API key is requested. The user selects a provider. A missing SDK/runtime, missing sign-in, unavailable subscription, rate limit, or provider error is reported as unavailable; the app must not read, copy, or scrape provider auth files. Copilot runs in SDK `mode="empty"` with no native tools and uses its `auto` default model. Explicit Copilot model IDs are rejected because the empty-mode SDK does not expose a model catalog. Codex uses the SDK-bundled runtime, requires ChatGPT account mode, reports the current account model catalog/default, and forces ChatGPT sign-in. It uses a read-only sandbox, denied approvals, an isolated temporary working directory, and per-process plus per-thread disabled shell, image-view, web-search, browser, apps, and MCP configuration. The host checks every Codex turn result and fails closed on any unexpected native event. The only observed native calls allowed through that guard are two Codex MCP metadata discovery methods, and only when the completed result is valid and its resource/template list is empty. This is inert metadata discovery, not a claim that zero native events occurred; non-empty metadata, any other MCP server/tool, or any command, image, browser, app, web, computer, or dynamic tool event fails the job. `model` is optional; omitted means the provider SDK's reported default. Explicit Codex models must appear in its current SDK catalog.

AI can draft concepts, summarize observed results, and investigate a missing document. It may call only host-interpreted tools `get_schema`, `sample_documents`, `preview_search`, `get_document`, and `diagnose_document`, all scoped to the selected index and fields. It cannot make arbitrary HTTP/Query DSL requests, read local files, run shell commands, save concepts, grade/pin documents, tune/apply settings, modify Elasticsearch, create scripts, or deploy an application profile. Tool execution is host-side, read-only, allowlisted, and capped at six calls per message. Model output is an untrusted draft; the user must review and explicitly save/apply it.

Only selected query text, chosen concept fields, and bounded selected document excerpts are sent to the chosen provider when needed. Credentials remain in the host request path and are never included in model context, job history, SQLite, or output. Document text is treated as untrusted evidence, not tool instructions. Session history is provider- and corpus-scoped and bounded. Reset clears local history, archives the Codex provider thread, or deletes the Copilot SDK session; Codex may retain its archived thread in the signed-in account history. Changing index closes/resets that context.

### `POST /api/ai/status`

Request: `{}`. Returns `{ "providers": [{"id": "codex"|"copilot", "available": boolean, "auth_state": "ready|sign_in_required|sdk_missing|cli_missing|unavailable|unknown", "default_model": string|null, "models": [string], "setup_hint": string, "error_code": string|null}] }`. Codex catalog/default values come from the signed-in SDK. Copilot reports only its supported `auto` default; explicit model IDs are rejected. Do not expose usernames, tokens, auth paths, or environment values.

### `POST /api/ai/sessions/create`

Request: `{ "provider": "codex"|"copilot", "model": "optional", "connection": {...request-scoped existing connection fields...}, "corpus": {"index": string, "text_fields": [string], "filter_fields": [string]}, "concept_id": "optional" }`. Returns `{ "session_id": string, "provider": string, "model": string|null, "corpus": {...}, "status": "ready" }`. Validate the connection and index/field scope using the current mapping. Do not retain this connection in the session. A session cannot change provider or corpus; create a new session for those changes.

### `POST /api/ai/sessions/message`

Request: `{ "session_id": string, "connection": {...request-scoped existing connection fields...}, "message": string, "context": {"query": "optional", "query_id": "optional", "concept": "optional concept object", "document": {"index": string, "id": string}|null} }`. Returns `{ "job_id": string, "status": "queued" }`. Messages are bounded; context must match the session corpus and its selected fields. Connection credentials are used only in memory to perform scoped host tools and are stripped before storage/provider calls.

### `POST /api/ai/sessions/history`

Request: `{ "session_id": string, "limit": 20 }`. Returns `{ "messages": [{"role": "user|assistant", "text": string, "created_at": string, "result": object|null}] }` with bounded history and no credentials. Tool traces include action names, counts, and warnings, not raw request headers or full source documents.

### `POST /api/ai/sessions/reset`

Request: `{ "session_id": string }`. Returns `{ "reset": true, "provider_delete_pending": boolean }`. Ends provider conversation state when supported (Codex threads are archived, Copilot sessions are deleted) and deletes local bounded history; subsequent work needs a newly created session. Provider sessions are created lazily on the first actual user message so opening a session does not consume an unrequested inference turn.

### `POST /api/ai/jobs/get` and `/api/ai/jobs/cancel`

Get request: `{ "job_id": string }`. Returns `{ "job_id": string, "status": "queued|running|succeeded|failed|cancelled", "progress": {"stage": string, "completed_steps": number, "max_steps": 6}, "tool_trace": [{"tool": string, "summary": string, "result_count": number|null}], "result": {"text": string, "concept_draft": concept|null, "diagnosis": {"kind":"model_hypothesis","text":string}|null, "summary": {"kind":"model_summary","text":string}|null, "warnings":[string]}|null, "error": {"code": string, "message": string}|null }`. Model-generated diagnoses and summaries are explicitly marked as hypotheses; only host-returned read-only diagnostics and metrics are observations.

Cancel request: `{ "job_id": string }`. Returns `{ "job_id": string, "status": "cancelled|running", "cancellation_requested": boolean }`. Provider/network errors have stable safe codes and short user-facing messages. A job deadline and per-provider concurrency limit are enforced; no credentials or unbounded excerpts are retained in job snapshots.

## Limits and evaluation

The current concept workflow is BM25; AI does not add semantic/vector retrieval. Tuning remains a deterministic bounded search over concept and related weights; selected field boosts remain fixed. A model can explain observed query/evidence and propose edits, but cannot certify relevance or cause a better result. Use representative saved queries and separate validation labels. Relevance is query-specific human feedback; do not interpret a small or selective set as objective ground truth.
