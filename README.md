# Elasticsearch RAG Tuning Workbench

Elasticsearch에 저장된 문서를 검색하고, **어떤 문서가 왜 검색됐는지 살펴보며 검색 설정을 실험하는 로컬 웹 도구**입니다. RAG를 처음 접하는 개발자와 검색 담당자가 Jira·Confluence 등 기존 업무 문서를 대상으로 필드, 질의, BM25와 선택적 벡터 검색을 비교할 수 있도록 만들었습니다.

이 도구는 검색 결과와 평가를 탐색하는 작업대입니다. 문서 분할·재색인 파이프라인이나 답변 생성 시스템은 제공하지 않으며, 작은 샘플에서 얻은 점수는 실제 코퍼스의 품질이나 운영 적합성을 보장하지 않습니다.

## 주요 기능

- Elasticsearch 매핑과 문서 예시를 확인하고 자연어 질의로 검색 결과를 살펴봅니다.
- BM25 검색의 필드 가중치, 필터, 하이라이트와 `_explain` 점수 근거를 탐색합니다.
- 기존 호환 임베딩이 있으면 벡터 검색과 RRF 하이브리드 검색을 비교합니다. 별도 동의를 받아 로컬 E5 임베딩을 생성할 수도 있습니다.
- 검색 질의와 문서에 사람이 관련도 판단을 기록하고, 설정 전후 결과 및 평가 지표를 비교합니다.
- 개인 지식 라이브러리를 SQLite에 저장하고 FTS5/BM25로 검색합니다. 선택 기능으로 별도 Elasticsearch 벡터 인덱스에 동기화할 수 있습니다.

## 빠른 시작

필요 항목: Python 3.10 이상과 연결 가능한 Elasticsearch endpoint. BM25만 사용한다면 추가 임베딩 패키지는 필요하지 않습니다. 벡터 검색 지원은 Elasticsearch 배포판과 인덱스 매핑에 따라 다릅니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m es_rag_tuner auth bootstrap-admin
.venv/bin/python -m es_rag_tuner
```

브라우저에서 <http://127.0.0.1:8765>를 열고 방금 만든 로컬 관리자 계정으로 로그인합니다. 서버는 loopback 주소에만 바인딩됩니다. 종료하려면 실행 터미널에서 `Ctrl+C`를 누릅니다.

Elasticsearch가 아직 없다면 로컬 평가용 단일 노드 예시를 사용할 수 있습니다. 컨테이너 포트는 로컬 호스트에만 공개됩니다. 보안 비활성 설정은 이 loopback 전용 샘플 용도에 한정하세요.

```bash
docker run --name es-rag-local --detach \
  --publish 127.0.0.1:9200:9200 \
  --env discovery.type=single-node \
  --env xpack.security.enabled=false \
  --env 'ES_JAVA_OPTS=-Xms1g -Xmx1g' \
  --volume es-rag-local-data:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:9.5.5
```

## 첫 검색

1. 앱에서 Elasticsearch 주소를 입력하고 연결합니다. 기본 예시는 `http://127.0.0.1:9200`입니다. 원격 서버에는 HTTPS를 사용하세요.
2. 인덱스를 선택하고 **필드와 예시 확인**을 눌러 매핑과 일부 문서 예시를 살펴봅니다. 제안 필드는 매핑 정보에 따른 후보이며 의미상 적합성을 보증하지 않습니다.
3. 찾으려는 내용을 자연어로 입력하고 **결과 보기**를 선택합니다. 제목, 원문 발췌, 점수 근거를 함께 살펴보세요.
4. 결과 문서를 판단해 평가를 기록하고, 설정 변경 전후를 비교합니다. 자동 제안은 검토 후 직접 적용합니다.

원하는 문서가 결과에 없다면 제목이나 본문에서 기억나는 말로 후보를 찾아볼 수 있습니다. 찾기에 나오지 않아도 문서가 인덱스에 없다고 단정할 수 없습니다. 이 흐름은 읽기 전용으로 기존 Elasticsearch 인덱스를 살펴봅니다. 샘플 인덱스 가져오기는 별도 동작이며 새 인덱스를 만듭니다.

## BM25, 벡터, 하이브리드

**BM25**는 텍스트 필드의 단어 일치를 바탕으로 순위를 계산하며 기본 설치에서 사용할 수 있습니다. 먼저 BM25로 결과를 관찰하고 필드 선택과 필터를 조정해 보세요.

**벡터 검색**은 인덱스에 호환 벡터가 이미 있거나, 로컬에서 임베딩을 생성한 경우 사용할 수 있습니다. 외부 문서용 선택 기능은 다음과 같이 설치합니다.

```bash
.venv/bin/python -m pip install -e '.[semantic]'
```

앱에서 임베딩 생성 동작을 직접 선택하면 `intfloat/multilingual-e5-large` 모델 파일(약 2.24 GB)이 로컬 캐시에 처음 다운로드될 수 있습니다. 다운로드 전 UI의 안내를 확인하세요. 임베딩은 선택 인덱스의 문서에 `rag_embedding` 필드로 부분 업데이트됩니다. 이 데이터 변경은 일반 BM25 조회와 다르므로 사용할 인덱스와 권한을 확인한 뒤 실행하세요.

**하이브리드 검색**은 BM25와 벡터 결과의 순위를 RRF 방식으로 합칩니다. 서로 다른 검색 방식의 점수는 직접 비교할 수 없고, 점수는 관련성 확률이 아닙니다. 벡터 생성·검색 가능 여부는 Elasticsearch 배포판과 매핑에 따라 다릅니다. 검색 준비 안내가 실패하면 BM25부터 사용할 수 있습니다.

개인 지식 라이브러리의 Elasticsearch 동기화는 기본적으로 BM25 전용이며 외부 문서 임베딩 흐름과 별도입니다. 해당 라이브러리의 벡터 동기화는 추가 설치와 화면 내 명시적 다운로드 동의가 필요하며, 토크나이저 파일(약 18 MB)과 E5 모델(약 2.24 GB)을 받을 수 있습니다. BM25 동기화·검색은 모델을 다운로드하지 않습니다.

개인 지식 라이브러리의 벡터 동기화 기능을 사용하려면 다음 선택 패키지를 설치합니다. 설치만으로 모델이 다운로드되지는 않습니다.

```bash
.venv/bin/python -m pip install -e '.[private-vector]'
```

## 선택 기능: AI 개념 도우미

AI 개념 도우미는 선택 기능이며, 앱 전용 대화에서 질의·개념 초안을 만들거나 관찰된 검색 결과를 요약하고 문서 진단을 도울 수 있습니다. Codex 또는 GitHub Copilot SDK와 사용자의 해당 provider 계정·구독 상태에 따라 이용할 수 있으며, 사용 전 인증이 필요합니다. Python 3.11 이상 환경에서 설치합니다.

```bash
.venv/bin/python -m pip install -e '.[agents]'
```

도우미는 기존 Codex desktop 또는 Copilot 채팅을 재사용하지 않습니다. 선택한 문서 필드와 질의 등 필요한 문맥이 provider로 전송될 수 있습니다. 제안과 요약은 검색된 답변이나 검증된 사실이 아니며, 답변 생성 시스템도 아닙니다. 사용자가 검토하고 명시적으로 저장·적용해야 합니다. 동작과 데이터 경계는 [AI API 안내](docs/agent-api.md)와 [연구 및 제한](docs/agent-research.md)을 참고하세요.

## 계정, 개인정보와 저장 위치

첫 실행 전에 로컬 계정을 부트스트랩합니다. 계정별 개념, 평가, 실험 기록, 세션, 개인 지식 데이터는 로컬 SQLite에 저장됩니다. 기본 경로는 `~/.local/share/es-rag-workbench/`이며, `ES_RAG_CONCEPT_DB`로 상태 DB 경로를 바꿀 수 있습니다. 모델 캐시 경로는 `ES_RAG_MODEL_CACHE`로 설정할 수 있습니다.

Elasticsearch 주소, 인덱스와 연결 인증 정보는 브라우저에서 연결할 때 입력하며 앱 계정 DB에는 Elasticsearch 비밀번호나 API 키를 저장하지 않습니다. 연결된 Elasticsearch 인덱스는 계정 간에 공유될 수 있고 Elasticsearch가 부여한 자격 증명 권한을 따릅니다. 앱의 계정 분리는 Elasticsearch 보안 기능(DLS 등)이 아니며, 같은 호스트의 다른 프로세스나 앱 데이터 디렉터리에 접근 가능한 사용자에 대한 격리도 아닙니다. 공개 네트워크에 노출하거나 reverse proxy 뒤에 배포하지 마세요.

설정 가능한 경로와 계정 처리 세부 내용은 [`docs/cycle37-local-account-acceptance.md`](docs/cycle37-local-account-acceptance.md), 개인 라이브러리 경계는 [`docs/cycle38-private-knowledge-api.md`](docs/cycle38-private-knowledge-api.md)와 [`docs/cycle43-private-vector-design.md`](docs/cycle43-private-vector-design.md)를 참고하세요.

## 평가와 한계

검색 결과는 평가 질의와 사람이 남긴 관련도 판단에 비춰 비교합니다. Recall@k, MRR@k, nDCG 등의 수치는 **기록된 질의, 판단 문서, 데이터 분할 및 cutoff에 대한 결과**입니다. 판단되지 않은 문서는 무관 문서와 다르며, 검색 점수는 사용자 관련도나 답변 품질을 뜻하지 않습니다. 작은 표본의 지표만으로 일반화, 통계적 유의성 또는 운영 품질을 주장하지 마세요.

샘플 Jira 데이터에 대한 첫 평가 결과와 실행 조건은 [`docs/first-milestone.md`](docs/first-milestone.md)에 기록되어 있습니다. 이는 재현 가능한 샘플 실험이지 외부 코퍼스 평가가 아닙니다. 실제 사용 전에는 대상 인덱스에서 대표 질의와 기대 문서를 직접 준비하고, 변경 전후를 같은 조건으로 평가해야 합니다.

통합 검증은 다음과 같이 실행할 수 있습니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

전체 검증에는 로컬 Elasticsearch와 설정된 provider 계정이 필요한 항목 및 결정적 모의 검사가 포함됩니다. 해당 의존성이 없는 환경에서 일부 실패/건너뜀은 서비스 결함 판정이나 전체 PASS 증거가 아닙니다. 게이트, 실행 환경, 판정 한계는 [`docs/agent-acceptance.md`](docs/agent-acceptance.md)를 확인하세요.

## 문서 안내

- [개념 검색 API와 평가 규칙](docs/concept-api.md)
- [연구 및 검색 품질 해석 한계](docs/concept-research.md)
- [평가 준비 상태와 질의 coverage](docs/tune-readiness-research.md), [coverage 해석](docs/query-coverage-research.md)
- [비공개 지식 라이브러리 API](docs/cycle38-private-knowledge-api.md)
- [비공개 벡터 동기화 설계와 제한](docs/cycle43-private-vector-design.md)
- [실험 비교와 증거 내보내기](docs/experiment-comparison-research.md), [내보내기 제한](docs/experiment-export-research.md)
- [통합 acceptance 기준](docs/agent-acceptance.md)

## 문제 해결과 다음 단계

- **로그인할 계정이 없음:** `python -m es_rag_tuner auth bootstrap-admin`을 한 번 실행해 최초 관리자를 만듭니다. 이미 초기화된 DB에서는 다시 bootstrap할 수 없습니다.
- **Elasticsearch 연결 실패:** 주소·포트·인증을 확인하고 서버 상태를 점검합니다. 앱과 Elasticsearch가 다른 컨테이너/호스트에 있으면 앱 컨테이너 안의 `127.0.0.1`은 Elasticsearch를 가리키지 않습니다.
- **벡터 기능이 준비되지 않음:** BM25를 먼저 사용하세요. 벡터 필드 매핑, 저장 벡터, 설치된 선택 패키지와 모델 캐시를 점검합니다.
- **모델 다운로드가 예상보다 큼:** 외부 임베딩 생성과 개인 라이브러리 벡터 동기화는 서로 다른 선택 기능입니다. 실행 전에 각각의 동의 안내와 캐시 용량을 확인하세요.
- **샘플 점수만 좋음:** 실제 코퍼스의 대표 질의와 관련 문서 판단을 추가하고 동일한 평가 조건으로 다시 비교합니다.

향후 작업은 실제 문서 집합의 평가를 넓히고, 판단 근거를 추적할 수 있는 비교를 개선하며, 문서 청크 정책을 실제 인덱싱 파이프라인에 연결하는 방향입니다. 현재 청크 랩은 미리보기 기능이며 기존 외부 문서를 자동으로 재분할하거나 재색인하지 않습니다.
