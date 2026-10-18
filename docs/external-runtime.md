# External runtime and context handoff / 외부 런타임 및 문맥 전달

This guide covers the local Python profile runtime introduced for R10. It does not deploy a profile, generate an answer, or send context to an external provider.

이 안내는 R10의 로컬 Python 프로필 실행 방법을 설명합니다. 프로필을 배포하거나 답변을 생성하지 않으며, 문맥을 외부 provider로 보내지 않습니다.

## Install and export a profile / 설치 및 프로필 내보내기

Install the workbench package, then export one saved concept version through the UI or `POST /api/concepts/export`. The export contains a version and mapping fingerprint, but no connection credentials. Keep the profile JSON private if its query, filters, field names, or index name are sensitive.

작업대 패키지를 설치한 다음 UI 또는 `POST /api/concepts/export`에서 저장된 개념 버전 하나를 내보냅니다. 프로필에는 버전 및 매핑 지문이 포함되며 연결 자격정보는 포함되지 않습니다. 질의, 필터, 필드 또는 인덱스 이름이 민감하면 JSON 파일을 비공개로 보관하세요.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
```

## Search and create a context bundle / 검색 및 문맥 묶음 만들기

Run the example with an exported profile and a query. `ES_URL` identifies the Elasticsearch origin. Credentials are read from `ES_API_KEY` or `ES_USERNAME` and `ES_PASSWORD` only for the current process.

내보낸 프로필과 질의로 예제를 실행합니다. `ES_URL`은 Elasticsearch 주소이며, 자격정보는 현재 프로세스의 `ES_API_KEY` 또는 `ES_USERNAME`과 `ES_PASSWORD` 환경변수에서만 읽습니다.

```bash
ES_URL=http://127.0.0.1:9200 \
ES_API_KEY="$ES_API_KEY" \
  .venv/bin/python examples/profile_context_handoff.py profile-export.json "your search query"
```

The JSON artifact includes selected snippets, exact `(index, document_id)` identities, ranks, profile provenance, a content fingerprint, and included/deduplicated/omitted counts. It keeps the first output slot for an exact duplicate and retains the better rank when one is present. It exports only complete entries under the configured count budget. It excludes full `_source` objects and connection details. Review query and snippet text, IDs, and index names before sharing.

JSON 파일에는 선택된 발췌, 정확한 `(인덱스, 문서 ID)` 식별자, 순위, 프로필 출처, 콘텐츠 지문, 포함·중복 제거·제외 개수가 기록됩니다. 동일 문서의 첫 출력 위치를 유지하고 더 나은 순위가 있으면 그 내용을 사용합니다. 설정한 계수 예산에 들어가는 항목 전체만 내보냅니다. 전체 `_source` 객체와 연결 정보는 제외합니다. 공유 전에 질의, 발췌, ID와 인덱스 이름을 검토하세요.

The sample uses `whitespace-word-count-v1`. This is an explicit whitespace-word estimate, not a model tokenizer and not a promise about any downstream model's token usage. For a true model-specific budget, call `build_context_bundle` from your application with that application's tokenizer function and a descriptive `counter_name`. The counter receives each complete canonical JSON context entry; the reported count covers entries, not your outer prompt or system instructions.

예제 계수기 `whitespace-word-count-v1`은 공백 기준 단어 근사치입니다. 모델 토크나이저가 아니며 후속 모델의 토큰 사용량을 보장하지 않습니다. 실제 모델별 예산에는 애플리케이션의 토크나이저 함수와 설명 가능한 `counter_name`을 `build_context_bundle`에 전달하세요. 계수기는 정규화된 JSON 문맥 항목 전체를 받으며, 보고되는 수는 항목 기준이지 외부 프롬프트나 시스템 지시문을 포함하지 않습니다.

Example application code / 애플리케이션 예시:

```python
from es_rag_tuner.context_bundle import build_context_bundle
from es_rag_tuner.profile_runtime import search_profile

results = search_profile(connection, exported_profile, query)
bundle = build_context_bundle(
    results,
    token_counter=my_model_tokenizer.count,
    counter_name="my-model-tokenizer-v3",
    max_tokens=1800,
    max_entries=8,
)
```

## Doctor and bounded measurements / doctor 및 제한된 측정

The doctor performs a read-only Elasticsearch root request. It reports the URL origin, distribution, version, and estimated features. It omits URL userinfo, path, query, fragment, and raw transport exception text.

doctor는 Elasticsearch 루트에 읽기 요청만 보냅니다. URL origin, 배포판, 버전, 추정 기능을 보고하며 userinfo, 경로, query, fragment와 전송 예외 원문을 출력하지 않습니다.

```bash
ES_URL=http://127.0.0.1:9200 .venv/bin/python -m es_rag_tuner doctor
```

The benchmark example accepts concurrency 1, 2, or 4 and at most 100 searches. It prints aggregate p50/p95 latency and throughput only. Queries and credentials come from environment variables; hit IDs and snippets are not printed. Measurements describe only the tested local machine, cluster, profile, and query set; they are not a capacity guarantee or relevance evaluation.

benchmark 예제는 동시성 1·2·4와 최대 100회 검색을 허용합니다. p50/p95 지연 시간과 처리량만 출력하며, 질의와 자격정보는 환경변수에서 읽고 결과 ID와 발췌는 출력하지 않습니다. 측정값은 실행한 로컬 머신, 클러스터, 프로필과 질의 세트에만 해당하며 처리 용량 보장이나 관련도 평가가 아닙니다.

```bash
ES_URL=http://127.0.0.1:9200 \
ES_BENCHMARK_QUERY="your search query" \
  .venv/bin/python examples/benchmark_profile_runtime.py profile-export.json --iterations 20 --concurrency 2
```

## Saved-run export and SQLite recovery / 저장된 run 내보내기 및 SQLite 복구

`POST /api/concepts/runs/export` exports one exact saved run. Its stable `content_fingerprint` covers the privacy-filtered artifact and excludes the changing `exported_at` timestamp. Re-exporting does not rerun Elasticsearch. Judgment and query text may still contain sensitive user-authored prose; review the artifact.

`POST /api/concepts/runs/export`는 저장된 run 하나를 정확히 내보냅니다. 안정적인 `content_fingerprint`는 개인정보 필터링된 산출물에 대해 계산하고 변경되는 `exported_at` 시각은 제외합니다. 재내보내기는 Elasticsearch를 다시 검색하지 않습니다. 질의와 판단 설명에 사용자가 입력한 민감 문장이 남을 수 있으므로 파일을 검토하세요.

SQLite backup/restore remains an explicit, offline per-file operation. It validates integrity and recognized schema, uses restrictive file permissions, and excludes Elasticsearch indices. A set of account DB files does not form one cross-file point-in-time snapshot. See the [API and maintenance contract](api-contract.md#explicit-backup-and-restore).

SQLite 백업·복원은 파일별로 명시적으로 수행하는 오프라인 작업입니다. 무결성과 인식 가능한 스키마를 검사하고 제한적인 파일 권한을 사용하며 Elasticsearch 인덱스는 포함하지 않습니다. 여러 계정 DB 파일을 하나의 동시점 스냅샷으로 보장하지 않습니다. [API 및 유지보수 계약](api-contract.md#explicit-backup-and-restore)을 참고하세요.
