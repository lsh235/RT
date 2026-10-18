# Upgrade and recovery / 업그레이드와 복구

## English

This guide covers local SQLite state only. Backups are per SQLite file; they do not include Elasticsearch indexes, model caches, container images, or a cross-file point-in-time snapshot.

### Upgrade from v1.15.0 source checkout

1. Stop the running workbench with `Ctrl+C`.
2. Preserve your current checkout and create a separate working copy or revision before changing code.
3. Back up the base/control database and every account state database separately. The default base path is `~/.local/share/es-rag-workbench/concepts.sqlite3`; additional account state files use `~/.local/share/es-rag-workbench/concepts.sqlite3.accounts/<account-uuid>.sqlite3`. Do not assume one file covers every account.
4. Install the new source or wheel in the same isolated Python environment. For source:

   ```bash
   .venv/bin/python -m pip install -e .
   ```

5. Start the application. It applies recognized control and state migrations on database open and creates a mode-restricted, SQLite-consistent pre-migration snapshot beside a database when that file needs migration. Unknown/newer schemas fail closed rather than being rewritten.
6. Sign in and inspect the account and personal-library state before resuming indexing. Reindexing a personal corpus is an explicit operation; it does not automatically rewrite shared Elasticsearch indexes.

There is no recorded automated downgrade path. Do not run an older application against a database after a newer schema migration; restore a copy of the corresponding pre-upgrade database into an offline, verified environment if rollback is required.

### Explicit backup and restore

Run one backup command per SQLite database while the app is stopped. Create the destination directory first. The command validates the source workbench schema, copies through SQLite's backup API, checks `PRAGMA integrity_check`, and writes the destination with restrictive mode `0600` on supported Unix filesystems.

```bash
mkdir -p ./private-backups
.venv/bin/python -m es_rag_tuner db-backup \
  --source "$HOME/.local/share/es-rag-workbench/concepts.sqlite3" \
  --destination ./private-backups/control.sqlite3
```

Restore is offline-only. Stop the workbench, ensure the destination has no `-wal` or `-shm` sidecar, and choose an explicit destination path. Restore verifies a recognized workbench database and SQLite integrity before installing it atomically.

```bash
.venv/bin/python -m es_rag_tuner db-restore \
  --source ./private-backups/control.sqlite3 \
  --destination "$HOME/.local/share/es-rag-workbench/concepts.sqlite3" \
  --offline-confirmed
```

Restoring the primary file does not restore separate account database files or Elasticsearch data. Make and verify a matching backup for every local database and separately plan any Elasticsearch snapshot/recovery. The command has no Elasticsearch snapshot functionality. Before relying on backups, perform a restore to a separate disposable path and verify it with `PRAGMA integrity_check` (`ok`) using SQLite.

### Vector and Elasticsearch compatibility

BM25 can be used without embedding extras or vector fields. Dense-vector behavior depends on the Elasticsearch distribution, version, and target index mapping. The repository has CI configuration and prior independent evidence for Elasticsearch 9.5.5 only; see [support matrix](support-matrix.md). A vector profile records a model and dimensions. Matching dimensions alone do not prove that existing vectors are compatible. Changing a profile requires an explicit re-embedding/sync operation and appropriate write permissions. This guide makes no search-quality claim.

## 한국어

이 안내는 로컬 SQLite 상태를 다룹니다. 백업은 SQLite 파일별로 수행하며 Elasticsearch 인덱스, 모델 캐시, 컨테이너 이미지, 여러 파일의 단일 시점 스냅샷을 포함하지 않습니다.

### v1.15.0 소스 체크아웃에서 업그레이드

1. 실행 중인 workbench를 `Ctrl+C`로 종료합니다.
2. 코드를 바꾸기 전에 기존 체크아웃을 보존하고 별도 작업 사본이나 revision을 만듭니다.
3. 기본/control 데이터베이스와 각 계정 state 데이터베이스를 따로 백업합니다. 기본 경로는 `~/.local/share/es-rag-workbench/concepts.sqlite3`이고 추가 계정 상태 파일은 `~/.local/share/es-rag-workbench/concepts.sqlite3.accounts/<account-uuid>.sqlite3` 형식을 사용합니다. 하나의 파일만 백업하면 충분하다고 가정하지 마세요.
4. 격리된 동일 Python 환경에 새 소스 또는 wheel을 설치합니다. 소스 설치:

   ```bash
   .venv/bin/python -m pip install -e .
   ```

5. 애플리케이션을 시작합니다. 데이터베이스를 열 때 인식 가능한 control/state migration을 적용합니다. 해당 파일의 migration이 필요하면 SQLite 일관성이 있는 제한 권한 사본을 원본 옆에 저장합니다. 알 수 없거나 더 새로운 스키마는 변경하지 않고 오류로 끝납니다.
6. 로그인해 계정과 개인 지식 상태를 확인한 뒤 필요한 경우 색인 작업을 명시적으로 재개합니다. 개인 코퍼스 재색인은 명시적 동작이며 공유 Elasticsearch 인덱스를 자동으로 다시 작성하지 않습니다.

자동 downgrade 경로는 검증 기록에 없습니다. 새 스키마로 변환한 데이터베이스를 이전 앱 버전으로 열지 마세요. 롤백이 필요하면 해당 업그레이드 전 DB 사본을 오프라인 검증 환경의 별도 경로에 복원하세요.

### 명시적 백업과 복원

앱을 중지한 상태에서 SQLite 데이터베이스마다 백업 명령을 한 번씩 실행합니다. 대상 디렉터리를 먼저 만드세요. 명령은 workbench 스키마를 검사하고 SQLite backup API로 복사한 뒤 `PRAGMA integrity_check`를 확인합니다. Unix 파일시스템에서는 대상 파일에 제한 권한 `0600`을 설정합니다.

```bash
mkdir -p ./private-backups
.venv/bin/python -m es_rag_tuner db-backup \
  --source "$HOME/.local/share/es-rag-workbench/concepts.sqlite3" \
  --destination ./private-backups/control.sqlite3
```

복원은 오프라인에서만 합니다. workbench를 종료하고 대상 옆에 `-wal` 또는 `-shm` 파일이 없는지 확인한 뒤 명시적인 경로를 지정합니다. 복원은 인식 가능한 workbench 스키마와 SQLite 무결성을 검사한 다음 원자적으로 설치합니다.

```bash
.venv/bin/python -m es_rag_tuner db-restore \
  --source ./private-backups/control.sqlite3 \
  --destination "$HOME/.local/share/es-rag-workbench/concepts.sqlite3" \
  --offline-confirmed
```

기본 파일 복원은 별도 계정 DB나 Elasticsearch 데이터를 복원하지 않습니다. 로컬 DB 전체에 대해 대응하는 백업을 각각 만들고 검증하며 Elasticsearch 스냅샷/복구는 별도로 계획하세요. 이 명령은 Elasticsearch 스냅샷 기능을 제공하지 않습니다. 백업에 의존하기 전에 폐기 가능한 별도 경로로 복원하고 SQLite에서 `PRAGMA integrity_check` 결과가 `ok`인지 확인하세요.

### 벡터와 Elasticsearch 호환성

BM25는 임베딩 extra나 벡터 필드 없이 사용할 수 있습니다. dense vector 동작은 Elasticsearch 배포판, 버전, 대상 인덱스 매핑에 따라 다릅니다. 저장소 CI 설정과 이전 독립 검증 근거는 Elasticsearch 9.5.5만 포함합니다. [지원 범위](support-matrix.md)를 확인하세요. 벡터 프로필은 모델과 차원을 기록합니다. 차원 수만 같다고 기존 벡터가 호환되는 것은 아닙니다. 프로필 변경에는 명시적인 재임베딩/동기화 작업과 적절한 쓰기 권한이 필요합니다. 이 안내는 검색 품질을 주장하지 않습니다.
