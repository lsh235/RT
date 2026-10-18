# Local API and storage contract

This document describes the loopback HTTP API and local SQLite boundaries through v1.15.0. The workbench is a local application; these routes are not an externally hosted service contract.

## Transport and authentication

- Bind the server to `127.0.0.1`, `localhost`, or `::1`. Requests must use a matching loopback `Host` and the active server port.
- All `POST` requests require a same-origin HTTP `Origin`. Protected `GET` and `POST` requests require an authenticated session cookie. Protected `POST` requests also require `X-CSRF-Token`.
- Login uses the short-lived nonce cookie and token returned by `GET /api/auth/session`. The session cookie is `HttpOnly` and `SameSite=Strict`.
- The authenticated account ID is taken from the server session and owner scope. A request body cannot select another account's database.
- `POST` bodies must be JSON objects no larger than 2 MiB. Elasticsearch connection input uses a `connection` object with `url` and optional `auth` (`none`, `basic`, or `api_key`). Put credentials only in the authentication fields; do not embed credentials, queries, or fragments in the URL.

## Response and error envelope

Successful requests return JSON with the route-specific result. Errors retain the HTTP status and the existing human-readable `error` field, and add a stable machine-readable `code`:

```json
{"error":"요청을 처리할 수 없습니다. 입력값을 확인하세요.","code":"INVALID_REQUEST"}
```

Common codes are `AUTH_REQUIRED`, `REQUEST_FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `REQUEST_TOO_LARGE`, `RATE_LIMITED`, `INVALID_REQUEST`, `STORAGE_ERROR`, `STORAGE_SCHEMA_INVALID`, `KNOWLEDGE_UNAVAILABLE`, `RETRIEVAL_UNAVAILABLE`, `DEPENDENCY_UNAVAILABLE`, and `INTERNAL_ERROR`. SQLite operation failures return HTTP 500 with `STORAGE_ERROR`; a recognized-schema or migration-layout failure returns HTTP 503 with `STORAGE_SCHEMA_INVALID`. The code is for programmatic handling; callers should display `error` to a person. Remote Elasticsearch bodies and transport details, local filesystem paths, SQLite messages, stack traces, credentials, and private document content are not returned as error text. Partial bulk failures use a stable item code and generic message rather than echoing a remote error body.

## Route catalog

`GET /api/health` is public and returns `{ "ok": true, "version": "…" }`. `GET /api/auth/session` is public and reports configuration/authentication state plus the login or session CSRF token. The following `GET` routes require a session:

| Route | Purpose |
|---|---|
| `/api/knowledge/es-status` | Current account's private knowledge sync/vector state. |
| `/api/embedding/profiles` | Safe metadata and local readiness for the fixed E5 and multilingual MiniLM embedding profiles. |
| `/api/token-preview/status` | Local tokenizer preparation status, without returning cache paths. |
| `/api/reranker/status` | Optional local cross-encoder runtime/cache readiness and pinned model identity, without returning local cache paths. |
| `/api/codebase-status` | Optional codebase helper readiness. |

All `POST` routes below require a JSON object. Unless stated otherwise, a successful route returns HTTP 200.

| Routes | Purpose |
|---|---|
| `/api/auth/login`, `/api/auth/logout`, `/api/auth/password/change` | Login, end the current session, and change the current user's password. Login accepts `username` and `password`; password change accepts `current_password` and `new_password`. |
| `/api/admin/accounts/list`, `/api/admin/accounts/create`, `/api/admin/accounts/update`, `/api/admin/accounts/password/reset`, `/api/admin/accounts/disable` | Administrator-only account administration. Account creation returns HTTP 201. |
| `/api/connect`, `/api/sample-info`, `/api/sample-import`, `/api/vectorize`, `/api/mapping` | Inspect a connection, inspect/import the bundled sample, prepare vectors, and inspect an index mapping. Connection, search, vectorization, and private vector sync accept a registered `profile_id`; omission retains the default E5 profile. |
| `/api/search`, `/api/code-rag`, `/api/explain`, `/api/document` | Shared-index lexical/vector/hybrid search, code search, explanation, and exact-document lookup. These routes do not modify a shared index except the explicitly requested sample import or vectorization operation. |
| `/api/reranker/prepare` | Prepare the fixed local reranker only with `{ "consent": true }`; downloading is never triggered by search or status checks. |
| `/api/token-preview`, `/api/token-preview/prepare` | Preview tokens locally and explicitly prepare the optional tokenizer. |
| `/api/evaluate`, `/api/tune` | Evaluate and run the bounded concept/search tuning workflow. |
| `/api/corpus/schema` | Inspect fields for the selected corpus. |
| `/api/concepts/list`, `/api/concepts/save`, `/api/concepts/quickstart`, `/api/concepts/ensure-query`, `/api/concepts/diagnose` | Read and update the current account's saved search concepts and query diagnostics. |
| `/api/concepts/versions`, `/api/concepts/restore`, `/api/concepts/export` | List/restore a concept profile version or export a profile. `/restore` restores a concept version; it is not a database restore operation. |
| `/api/concepts/preview`, `/api/concepts/information-need-preview`, `/api/concepts/vector-candidates`, `/api/concepts/mode-comparison`, `/api/concepts/mode-comparison-group`, `/api/concepts/locate-document`, `/api/concepts/document`, `/api/concepts/judge` | Preview/evaluate a concept, compare retrieval modes, locate an exact document, and save a human relevance judgment. |
| `/api/concepts/tune/readiness`, `/api/concepts/tune`, `/api/concepts/runs`, `/api/concepts/runs/export` | Check tuning readiness, run bounded tuning, inspect saved runs, and export a run. |
| `/api/evaluation/datasets/create`, `/api/evaluation/datasets/versions/create`, `/api/evaluation/datasets/list`, `/api/evaluation/datasets/detail`, `/api/evaluation/datasets/import`, `/api/evaluation/datasets/export` | Create account-scoped immutable query/qrel dataset versions and list, inspect, or exchange CSV/JSONL artifacts. |
| `/api/evaluation/datasets/evaluate`, `/api/evaluation/runs/list`, `/api/evaluation/runs/export`, `/api/evaluation/runs/compare` | Evaluate a versioned query split against a selected index, persist/export results, and compare compatible runs by query. |
| `/api/knowledge/list`, `/api/knowledge/preview`, `/api/knowledge/save`, `/api/knowledge/get`, `/api/knowledge/delete`, `/api/knowledge/search` | Manage and search documents in the authenticated account's private SQLite knowledge store. |
| `/api/knowledge/chunks/preview`, `/api/knowledge/chunks/policy`, `/api/knowledge/chunks/policy/get` | Preview character, paragraph, or pinned-token chunk boundaries and inspect or save the current account's chunk policy. Preview is read-only; token chunking requires the exact pinned tokenizer. |
| `/api/knowledge/reindex/start`, `/api/knowledge/reindex/status`, `/api/knowledge/reindex/latest`, `/api/knowledge/reindex/cancel`, `/api/knowledge/reindex/retry` | Start and inspect a persisted account-private reindex job, request cancellation, or retry a failed/interrupted job. The server derives account ownership and alias; jobs stage and verify a generation before publishing it. |
| `/api/knowledge/es-sync`, `/api/knowledge/es-vector-sync`, `/api/knowledge/concept-preview`, `/api/knowledge/judge` | Sync the authenticated account's private corpus, preview/evaluate it, and save a human judgment. Private Elasticsearch aliases and owner filters remain server-derived. |
| `/api/ai/status`, `/api/ai/sessions/create`, `/api/ai/sessions/message`, `/api/ai/sessions/history`, `/api/ai/sessions/reset`, `/api/ai/jobs/get`, `/api/ai/jobs/cancel` | Optional provider-session readiness and account-scoped session/job operations. Provider access remains opt-in. |

The route table is implemented in `es_rag_tuner/post_routes.py`. The HTTP handler in `es_rag_tuner/server.py` validates transport, session, CSRF, role, and account scope before invoking protected routes. Feature behavior remains in the existing `auth`, `concepts`, `knowledge`, `evaluation`, `retrieval`, and Elasticsearch client modules.

### Local embedding profiles

`GET /api/embedding/profiles` requires an authenticated session and returns the default profile ID plus a fixed registry. Each profile exposes its model/source identity, source revision when cached, dimension, cosine similarity, query and passage prefixes, context limit, license label, runtime-installed flag, cache state, and a safe next-step message. It never returns local cache paths or loader exception details. The current profiles are `e5-multilingual-large` (1024 dimensions; `query: ` and `passage: ` prefixes; default) and `paraphrase-multilingual-minilm-l12` (384 dimensions; no role prefix).

Pass `profile_id` to `/api/connect`, `/api/search`, `/api/code-rag`, `/api/vectorize`, private `/api/knowledge/es-vector-sync`, and the vector candidate/comparison routes to select a registered profile. Successful new vectorization records the resolved shared-index recipe and its SHA-256 in mapping `_meta`; private account state and the staged generation record the selected model and tokenizer revisions, tokenizer runtime, context-bounded passage-slicing recipe, and matching vector metadata. A profile mismatch, different model revision, or different recipe fails before vector search. Untagged legacy 1024-dimensional vectors remain an explicit E5 compatibility case; dimension equality alone does not establish compatibility. Selecting a new private profile marks old vectors stale until that account's explicit sync succeeds. BM25 does not load or download a vector model.

### Search comparison and local reranking

`POST /api/search` accepts `mode` (`bm25`, `vector`, or `hybrid`), `size` for final top-K (integer 1–50, default 10), `candidate_pool` (integer from `size` through 200, default `size`), existing `boosts`, `filters`, and `profile_id`, and `rank_constant` (integer 1–200 for hybrid search). `rerank` is an optional boolean defaulting to `false`. Malformed and out-of-range values fail explicitly. `/api/code-rag` forwards the same candidate and reranker settings to its hybrid issue lane before code composition.

Each returned hit includes the concrete `_index` and `_id`, `retrieval_ranks`, and `retrieval_scores`; hybrid results additionally include `rrf_score`. With `rerank: true`, the response preserves the original candidate evidence and adds each hit's `reranker.before_rank`, `after_rank`, raw `score`, and input `truncated` flag, plus top-level pinned `model`, `revision`, runtime, device, maximum input length, candidate count, score interpretation, and elapsed inference time. BM25, vector, RRF, and cross-encoder values are raw diagnostics and are not relevance probabilities or directly comparable scales.

The optional `reranker` extra installs the local CrossEncoder runtime. `GET /api/reranker/status` reports only safe readiness and model identity. `POST /api/reranker/prepare` requires explicit `consent: true` before downloading the pinned `BAAI/bge-reranker-v2-m3` model. Search loads only a prepared local snapshot; it never downloads. A missing runtime/cache or load/inference failure returns an explicit error when reranking was requested; base BM25/vector/hybrid search remains available without this extra. The model is an integration candidate; this API does not claim retrieval-quality gains.

### Evaluation datasets, query/qrel provenance, and runs

Evaluation routes are authenticated POST requests using the normal JSON, same-origin, session, and CSRF requirements. They use the active account's state database. `create` and `versions/create` take a name, provenance object, query array, qrel array, and an unjudged policy. A query row has `query_id`, `query`, `split` (`train`, `validation`, or `test`), and optional `information_need` and `related_query_group`. A qrel row is keyed by `query_id`, concrete `document_index`, and concrete `document_id`; it has `grade` (`null` or integer 0–3) and optional `document_family_id`.

The provenance object requires `source_name`, `source_license`, `permission_status`, ISO `collection_date`, `extraction_rules`, `omitted_known_relevant_items`, `judgment_source`, and `assessor`. `source_uri` may be empty for synthetic datasets. Permission status is one of `permission_cleared`, `user_authorized`, `synthetic`, or `not_verified`. The judgment source is one of `synthetic`, `public_qrels`, `human`, or `ai_suggestion`; an AI-suggestion dataset cannot be evaluated as ground truth. Reviewers must create a new version with accurate human-verified provenance before evaluating those judgments. Permission metadata is recorded evidence supplied by the dataset owner; it is not a legal determination by the workbench.

Dataset artifacts use format `es-rag-evaluation-dataset`, format version 1. JSONL begins with a dataset/version envelope, then typed `query` and `qrel` records. CSV uses a fixed header and one dataset envelope row followed by typed query and qrel rows. Both preserve dataset/version IDs, canonical content fingerprint, query split/group fields, concrete document IDs, explicit null grades, policy, and provenance. Import validates the entire artifact before an atomic insert; re-importing the same version ID and fingerprint is idempotent. Versions are immutable; edits create a new version from the current latest version. State migration v5 adds account-local version and run snapshot tables.

The default `judged_only` policy removes retrieved qrels that are absent or explicitly null while preserving the order of numeric grades. `P@k` divides relevant judged hits by `min(k, numeric judged hits returned)`. `Recall@k` divides retrieved known-relevant qrels by all known-relevant qrels. MRR and nDCG use the judged ranking; nDCG uses gain `2^grade-1` and an ideal ranking of all numeric qrels. A known-positive query with no relevant result has MRR 0; a query with no known relevant qrels has unavailable MRR and is excluded from its macro denominator. Binary relevance defaults to grade >= 2. Judged coverage is numeric judged hits divided by all hits returned at k. Runs report numeric, explicit-null, and absent qrel counts separately; a query with no known relevant qrels has unavailable Recall/MRR/nDCG values and is excluded from those macro denominators.

`unjudged_as_nonrelevant` is accepted only when the dataset explicitly asserts `qrels_complete: true`; each run/export records the policy and its consequences. Evaluation request fields include `dataset_id`, `version_id`, `split`, `mode`, `settings`, `cutoff`, and `configuration_frozen`. Test evaluation requires `configuration_frozen: true`, an available Elasticsearch index UUID, and a complete successful query batch. Only one successful test run may be saved per dataset version and corpus UUID identity; failed test batches reveal failure categories without exposing held-out metrics and do not consume that run. Per-query run comparisons require identical dataset fingerprint, split, index/corpus and mapping fingerprints, cutoff, and metric policy; candidate settings may differ so regressions and missed known-relevant documents can be shown.

These routes provide evaluation workflow and auditable metrics; they do not establish the license, completeness, or representativeness of imported qrels, nor do synthetic fixtures establish retrieval quality. Do not use the existing 25-document Jira fixture as a general benchmark.

### Bounded concept tuning (R09)

`POST /api/concepts/tune` accepts an optional `max_candidates` integer (1–30, default 30, counting the baseline) and `time_budget_seconds` integer (1–600, default 600). Invalid bounds are rejected before an Elasticsearch request is constructed. The response records effective limits, evaluated candidate count, elapsed time, and a `completed`, `candidate_budget`, or `time_budget` stop reason. Candidate IDs are ordered as `baseline`, then `candidate-001` onward; each trace row contains settings, train metrics, validation metrics, and evaluation status. Train judgments evaluate the finite candidate grid; validation judgments alone choose a candidate. A candidate must improve macro judged-only nDCG@K, with judged coverage@K as the next tie-breaker. Exact ties, worse candidates, unavailable/failed validation, or an incomplete validation run retain the stored baseline. No `test` judgments are loaded by this route, and the selected settings are never written to the saved concept automatically.

The response and immutable saved run include selection reason, candidate/settings/metric/output fingerprints, index UUID and mapping identity when available, exact input snapshots, and per-validation-query diagnostics. These identify only known-relevant judged targets. Absent qrels and explicit-null judgments remain unknown, and incomplete qrels do not support an exhaustive missed-relevant claim. The run is stored under the active account and the existing list/export routes preserve owner scoping.

## SQLite ownership and schema migrations

- `ES_RAG_CONCEPT_DB` selects the base database; otherwise the application uses `~/.local/share/es-rag-workbench/concepts.sqlite3`.
- The base database contains auth/control tables and the primary account's application state. A secondary account uses a separate UUID-named file under `<base filename>.accounts/`.
- Knowledge documents, chunks, FTS data, judgments, and Elasticsearch sync/vector state live in the current account's state database. Elasticsearch indices are outside this SQLite backup boundary.
- State migration v3 records chunk source revision, policy fingerprint, and exact token count when available; it also stores the account's selected chunk policy and persisted reindex jobs. State migration v4 stores each account's vector profile ID and recipe so query and passage embeddings use the same space. Existing documents and judgments remain the source of truth. A job rebuilds local chunks, stages a private Elasticsearch generation, verifies expected IDs and owner identity, refreshes it, then switches only that account's alias. A failed or cancelled publication retains the previous alias; restart recovery marks unfinished jobs interrupted for an explicit retry.
- Chunk offsets are 0-based half-open positions in the original source text. Character and paragraph policies use source offsets; token policy uses the pinned E5 tokenizer's source offsets and fails if that tokenizer is unavailable rather than substituting an estimate. Chunk policy changes make the private sync state stale until a successful reindex.
- `app_schema_migrations` records a `component` and `version` for each SQLite file. The base file can have both `control` and `state` migration entries. Current schema setup recognizes the existing legacy tables and adds only declared fields/tables; unknown table layouts and future version numbers fail closed.
- Before a component migration changes a file, the migration runner creates a SQLite backup snapshot through Python's `Connection.backup`, verifies `PRAGMA integrity_check`, and stores a mode-`0600` recovery file beside the database named `<database>.pre-<component>-v<target-version>.bak`. A failed migration rolls back its transaction and retains the snapshot. Keep these files private; they contain the same data as the database. See the [SQLite Online Backup API](https://www.sqlite.org/backup.html) and [Python `sqlite3.Connection.backup`](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).

## Explicit backup and restore

The maintenance commands operate on one explicit SQLite file at a time. Back up the base file and each secondary account database separately. Each snapshot is SQLite-consistent and validated; there is no cross-file transaction covering all accounts. Use a directory accessible only to the local operator.

```sh
es-rag-workbench db-backup --source /path/to/concepts.sqlite3 --destination /secure/backups/concepts.sqlite3
```

Stop the workbench before restore. Restore requires an explicit offline confirmation and refuses a destination that still has SQLite `-wal` or `-shm` sidecars. It verifies both the backup integrity and recognized workbench schema before atomically installing the destination. Repeat separately for each account database. These commands do not back up or restore Elasticsearch indices.

```sh
es-rag-workbench db-restore --source /secure/backups/concepts.sqlite3 --destination /path/to/concepts.sqlite3 --offline-confirmed
```

The existing `/api/concepts/restore` route remains limited to restoring a saved concept profile version. Whole-database maintenance is an explicit local CLI operation, not an account-controlled HTTP route.
