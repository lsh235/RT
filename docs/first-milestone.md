# 1차 목표 결과

**상태: 달성** — Elasticsearch 9.5.5에 샘플 인덱스를 적재하고 Q01–Q10 평가를 실행했습니다.

## 목표와 결과

첨부 평가셋으로 실제 BM25 검색을 평가했습니다. 두 목표를 모두 만족했습니다.

| 지표 | 목표 | 측정 | 결과 |
| --- | ---: | ---: | --- |
| Recall@5 | ≥ 0.90 | 1.000 (14/14 정답 문서) | 통과 |
| MRR@5 | ≥ 0.80 | 1.000 | 통과 |
| Precision@5 | 참고 | 0.280 | — |
| nDCG@5 | 참고 | 0.992 | — |

10개 질의 모두 첫 번째 결과가 기대 이슈였고, 14개 기대 이슈가 모두 상위 5개에 포함됐습니다. Q01 검색 예시에서는 `GRPC-34076`이 1위, `GRPC-36328`이 3위였습니다.

## 실행 환경과 적재 결과

- Docker 이미지: `docker.elastic.co/elasticsearch/elasticsearch:9.5.5`
- 응답에서 확인한 버전: `9.5.5`, 배포판 flavor: `default`
- 컨테이너: `es-rag-955`; HTTP는 `127.0.0.1:9200`에만 바인딩하고 데이터는 `es-rag-955-data` volume에 저장합니다.
- 평가 인덱스: `jira-grpc-issues-9-5-5`
- 적재 문서: 25개. 첨부 설정 메타데이터는 20개로 실제 NDJSON 수와 다릅니다.
- `rag_embedding`의 1024차원 `dense_vector` 매핑에 임베딩 25개를 추가했습니다. 이슈 문서의 원본 필드는 유지하고 누락된 `rag_embedding`만 bulk partial update했습니다.
- Elasticsearch kNN API를 실제 검색에 연결했습니다. 25개 문서의 벡터가 저장되어 검색 결과를 반환합니다.
- 1노드 클러스터 상태는 `yellow`입니다. 설정된 replica 1개가 다른 노드가 없어 `UNASSIGNED`이고 primary shard는 모두 시작됐습니다. 검색 및 평가는 정상 실행됐습니다.

## 튜닝 결과

기본 필드 가중치로 먼저 평가했을 때 이미 Recall@5와 MRR@5가 모두 1.0이었습니다. 자동 좌표 탐색을 1회 수행해 65개 후보 프로필을 확인했습니다. objective 최고 점수도 1.0이어서 기본 프로필을 유지했습니다. 현재 측정값은 제공된 10개 질의에 대한 것이므로 이 소규모 벤치마크 밖의 검색 품질을 보장하지 않습니다.

## 벡터 검색 활성화

Elasticsearch 9.5.5 코드와 공식 kNN 문서 확인 결과 `dense_vector`/kNN은 Elasticsearch에 내장되어 있습니다. 별도의 Elasticsearch 플러그인을 내려받거나 설치하지 않았습니다. kNN에 필요한 데이터 벡터와 질의 벡터를 같은 모델로 만들도록 FastEmbed 로컬 ONNX 런타임과 MIT 라이선스의 `intfloat/multilingual-e5-large` 모델을 설치·다운로드했습니다.

| 검색 방식 | Recall@5 | MRR@5 | nDCG@5 | 목표 |
| --- | ---: | ---: | ---: | --- |
| BM25 | 1.000 | 1.000 | 0.992 | 통과 |
| Dense vector | 1.000 | 1.000 | 1.000 | 통과 |
| BM25 + vector RRF (rank constant 60) | 1.000 | 1.000 | 0.992 | 통과 |

vector와 hybrid 모두 Q01–Q10의 14개 기대 티켓을 상위 5개에서 전부 찾았고, 각 질의의 첫 결과가 기대 이슈였습니다. 한국어 질의 `느린 네트워크에서 PING ACK 지연 때문에 keepalive watchdog timeout이 발생하고 transport is closing으로 연결이 끊기는 원인`은 BM25/vector/hybrid 모두 `GRPC-22963`을 1위로 반환했습니다. 벡터 필터 사전 적용도 `issue_key=GRPC-22963` 조건에서 해당 문서만 반환하는 것을 확인했습니다.

RRF `rank_constant` 5, 10, 20, 30, 60, 100, 200을 비교했습니다. Q01–Q10의 Recall@5, MRR@5, nDCG@5와 순위가 모두 같아서 기본값 60을 유지했습니다.

현재 저장 단위는 문서당 기존 `rag_chunk_text` 1개를 1024차원 벡터화하는 방식입니다. 제공 문서의 `rag_chunk_text`는 공백 기준 75–131단어였습니다. FastEmbed 지원 정보상 모델 입력은 512 토큰에서 잘리므로 더 긴 실제 Jira/Confluence 문서는 이 미리보기의 청크 분할을 실제 인덱싱으로 연결하고 재평가해야 합니다. 청크 랩의 크기·겹침은 현재 미리보기 전용입니다.

## 배포판 호환 참고

처음 시도한 OSS 7.10.2는 첨부 매핑의 `dense_vector`를 받아들이지 않았습니다. GitHub의 7.10.2 소스에서 vector mapper는 `x-pack/plugin/vectors`에 있고 OSS 아카이브는 OSS module 세트를 조립하는 구조임을 확인했습니다. 실행 응답도 `No handler for type [dense_vector]`였습니다. 그래서 앱은 해당 타입을 지원하지 않는 배포판에서만 값이 없는 `rag_embedding` 매핑을 제외하고 lexical 적재를 재시도하도록 했습니다. 7.10.2 컨테이너와 샘플 볼륨은 삭제하지 않고 정지 상태로 보존했습니다.

2026-10-17 기준 최신 Elasticsearch는 9.5.5이며, 이번 검증은 이 기본 배포판에서 완료했습니다. 기본 배포판은 OSS 라이선스 배포판이 아니라 Elastic License를 따르며 구독 없이 사용할 수 있는 기능을 포함합니다. Elastic은 7.11부터 Apache 2.0 바이너리 배포를 중단했다고 [라이선스 FAQ](https://www.elastic.co/pricing/faq/licensing)에 설명합니다.

## 검증 범위

- 실제 Docker Elasticsearch에 연결, 샘플 매핑·bulk 적재, 문서 수 확인
- 9.5.5의 `dense_vector` 매핑 확인 및 25개 실제 vector 값 생성
- Q01–Q10의 BM25, vector, hybrid 평가 및 65개 BM25 가중치 후보 자동 탐색
- 한국어 vector 질의와 kNN 메타데이터 사전 필터 조회
- Q01 실제 검색에서 기대 문서의 상위 순위 확인
- 앱 health endpoint와 Python/JavaScript 소스 문법 검사

이 결과는 로컬 단일 노드와 첨부된 테스트 데이터에 한정됩니다. 운영 Elasticsearch 배포나 별도 문서 집합의 품질은 검증하지 않았습니다.

## 출처

- [Elasticsearch 7.10.2 vectors plugin](https://github.com/elastic/elasticsearch/blob/v7.10.2/x-pack/plugin/vectors/build.gradle)
- [Elasticsearch 7.10.2 OSS distribution build](https://github.com/elastic/elasticsearch/blob/v7.10.2/distribution/build.gradle)
- [Elastic Docker Registry](https://www.docker.elastic.co/r/elasticsearch/elasticsearch)
- [Elastic Elasticsearch downloads](https://www.elastic.co/downloads/elasticsearch)
- [Elastic software licensing FAQ](https://www.elastic.co/pricing/faq/licensing)
