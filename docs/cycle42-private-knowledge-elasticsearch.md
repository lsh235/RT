# Cycle 42: private knowledge in Elasticsearch

Status: implementation contract and design note. The local loopback app is not a production multi-tenant service.

## Behavior and API

- The account UUID authenticated by the server is the only namespace input. The alias is `esrag-private-<uuid-without-hyphens>`; physical generations append `-g<N>`. Request fields such as `owner_id`, `user_id`, `manager_id`, and `index` cannot select a private namespace.
- `GET /api/knowledge/es-status` is authenticated and reports account-local SQLite counts and sync metadata. Since it has no Elasticsearch connection body, it reports persisted sync status; search and sync verify the alias against the active connection.
- `POST /api/knowledge/es-sync` accepts the existing `connection` object and builds a new complete generation. Each Bulk item is checked. The generation is exposed only through an atomic alias update after indexing succeeds. A failure retains the prior alias when possible and reports an error; private search returns no results unless persisted content is current and the alias is present.
- Before changing an existing alias, sync requires exactly one target whose name is this account's `-g<N>` generation and whose generation is not ahead of the reserved generation in SQLite. This allows retry after a failed build or interrupted swap while rejecting foreign, malformed, future, or multi-target aliases without removing them.
- Saving, updating, or deleting a local document marks the mirror stale. SQLite remains the source of truth. Search does not silently use a stale generation: it returns the shared-index lane and an empty private lane labeled stale until a successful sync.
- `POST /api/search` shows the selected shared index and the authenticated account's private library in separate result lanes. Their BM25 values are not combined because corpus statistics differ. The private lane supports BM25 only. Vector/hybrid searches explicitly report that private knowledge was not included; they do not claim full private-library coverage.
- Local FTS5 search and local concept evaluation are unchanged. Private text is not added to AI context by synchronization or retrieval.

## Access boundary

The app binds the authenticated local UUID to the Elasticsearch request boundary for the protected request. The boundary rejects private aliases and physical generations belonging to another local account, including guessed document-by-ID, mapping, explain, search, count, and request-body Bulk targets. Generic routes cannot read or write even the caller's private namespace; only the private BM25 search capability can read it and only the sync capability can mutate it. Wildcard, comma-separated multi-index, broad private prefixes, and indexless global retrieval paths are rejected. `list_indices` filters private physical names to the current account. Private search also checks that the alias points to exactly the generation recorded in SQLite. Generic user-selected shared indexes continue to use the existing app behavior.

This is app-side access control. All accounts still use the Elasticsearch credential supplied by the app, so a person with direct access to that credential or endpoint can bypass the app and access indices permitted to the credential. It is not Elasticsearch document-level security (DLS), nor does it create separate Elasticsearch identities.

## Consistency and recovery

SQLite and Elasticsearch do not share an atomic transaction. A sync captures a deterministic local content fingerprint, builds a new generation, checks each Bulk response item, explicitly refreshes the staged generation, verifies all chunks are visible to search, rechecks local content before switching aliases, and rechecks under a SQLite write lock before recording `in_sync`. A per-account nonblocking in-process lock rejects concurrent sync requests with HTTP 409; after process restart a persisted `syncing` state can be retried with the next generation. If local content changes during the operation, the alias is rolled back to the prior generation when possible and private search remains closed. A later user retry rebuilds from SQLite. The alias switch is atomic within Elasticsearch, but crashes or connectivity loss between the alias switch and SQLite status commit can leave status requiring an explicit retry; SQLite always remains authoritative.

No cross-system exactly-once or provider-managed recovery guarantee is claimed. Old successful physical generations are retained after a successful swap for recovery and may require administrative cleanup later; this app does not delete the prior generation during normal sync.

## Design research (checked 2026-10-18)

- [Elastic document and field level security](https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/controlling-access-at-document-field-level): DLS is attached to Elasticsearch identities and is read-side only. With a shared credential it cannot infer the app-local account. This design therefore enforces app-local ownership at request construction and does not claim DLS.
- [Elastic user roles](https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/user-roles) and [security privileges](https://www.elastic.co/docs/reference/elasticsearch/security-privileges): index privileges provide per-user isolation only when Elasticsearch receives distinct identities. The current connection model uses a shared app credential.
- [Search shard routing](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-shard-routing) and [aliases](https://www.elastic.co/docs/manage-data/data-store/aliases): routing selects shards and aliases are names for indexes; neither is treated as an authorization boundary. The app checks the requested namespace even for document-by-ID operations.
- [SQLite transactions](https://www.sqlite.org/transactional.html), [Elasticsearch refresh](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/refresh-parameter), [Bulk API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-bulk), and [index API](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-index-2): SQLite and Elasticsearch writes are separate systems; Bulk responses can contain item failures and refresh affects visibility. The generation build plus alias swap gives a clear retry boundary, but is not an atomic cross-system write.

These sources motivate the access and consistency design. They do not establish deployment-specific Elasticsearch behavior, search quality, production readiness, or isolation from direct Elasticsearch access.
