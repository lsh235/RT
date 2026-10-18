# Install / 설치

## English

This is a local-first Elasticsearch retrieval workbench. It does not generate RAG answers. The documented Python path binds only to loopback. Do not expose it through a public interface or reverse proxy.

### From a source checkout

Requirements evidenced by the repository: Python 3.10 or newer and an existing Elasticsearch endpoint. The CI lock was compiled with Python 3.12. A clean virtual environment is recommended.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m es_rag_tuner auth bootstrap-admin
.venv/bin/python -m es_rag_tuner --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765>. The bootstrap command prompts for an administrator name and display name, then asks for a password twice; the implementation requires at least 15 characters. It only bootstraps an uninitialized database. Stop the server with `Ctrl+C`.

For a built package, install the wheel with `python -m pip install ./dist/es_rag_tuning_workbench-<version>-py3-none-any.whl`, then use the same `python -m es_rag_tuner` commands. Independent R11 QA built and installed the wheel in a fresh virtual environment and checked the module, console entry point, version metadata, and packaged web asset. The inspected wheel also contains both third-party sample data files. Do not treat it as cleared for public redistribution while separate permission remains unresolved.

### Optional extras

Install only the extra you need:

```bash
.venv/bin/python -m pip install -e '.[semantic]'
.venv/bin/python -m pip install -e '.[reranker]'
.venv/bin/python -m pip install -e '.[token-preview]'
.venv/bin/python -m pip install -e '.[private-vector]'
.venv/bin/python -m pip install -e '.[agents]'
```

These extras use version ranges and are not pinned in `requirements-dev.lock`; pip resolves them at install time. `agents` includes a Python-version marker: the Copilot SDK is not selected on Python 3.10. Model weights, model tokenizers, and reranker files are obtained separately into local cache only after feature-level preparation/consent where implemented; they are not shipped as model assets by this project. Review the repository's model identifiers, pinned revisions, cache behavior, and upstream terms before enabling an optional feature. See [dependency and asset inventory](release/dependency-license-inventory.md).

### Local Docker Compose

The Compose setup is documented for Linux Docker Engine only and is a disposable loopback development path. Read [the Compose guide](compose.md) before starting it. It uses Linux host networking, service binds to `127.0.0.1`, defaults to app port `18765` and Elasticsearch port `19200`, and keeps data in project-scoped named volumes. The setup does not inspect or stop existing services; choose unused ports and a unique project name. Elasticsearch security is disabled in this example and must not be exposed beyond loopback.

```bash
docker compose -p es-rag-local -f compose.yaml up -d --build
docker compose -p es-rag-local -f compose.yaml exec workbench python -m es_rag_tuner auth bootstrap-admin
```

For alternate ports, set `ES_RAG_APP_PORT` and `ES_RAG_ES_PORT` to unused loopback ports on every Compose command. The app still requires explicit account bootstrap. Stop the project with `docker compose -p es-rag-local -f compose.yaml down`; this retains its named volumes. Do not add `-v` unless you intend to delete this project's persistent data. Independent R11 QA exercised loopback bootstrap, synthetic search, and named-volume persistence with disposable ports. The Compose image includes the bundled sample data, whose separate redistribution permission is unresolved; see [support matrix](support-matrix.md) and [asset audit](release/third-party-asset-audit.md).

### Data and credentials

By default, local account and workbench state is stored at `~/.local/share/es-rag-workbench/concepts.sqlite3`; additional account state files are under the neighboring `concepts.sqlite3.accounts/` directory. Set `ES_RAG_CONCEPT_DB` to choose a different base database path. The model cache defaults under `~/.cache/es-rag-workbench/`; `ES_RAG_MODEL_CACHE` changes the embedding cache. Token-preview assets use a separate cache under `~/.cache/es-rag-workbench/token-preview` and may be redirected with `ES_RAG_TOKEN_PREVIEW_CACHE`. Protect these paths as local user data. Elasticsearch credentials are entered for connections and are not part of the SQLite app account database. See [Security](../SECURITY.md).

## 한국어

이 도구는 로컬 우선 Elasticsearch 검색 작업대이며 RAG 답변을 생성하지 않습니다. Python 서버는 loopback에만 바인딩됩니다. 공개 인터페이스나 reverse proxy 뒤에 노출하지 마세요.

### 소스 체크아웃에서 설치

저장소가 명시하는 요구사항은 Python 3.10 이상과 연결할 Elasticsearch 주소입니다. CI lock은 Python 3.12로 생성되었습니다. 새 가상환경을 권장합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m es_rag_tuner auth bootstrap-admin
.venv/bin/python -m es_rag_tuner --host 127.0.0.1 --port 8765
```

<http://127.0.0.1:8765>를 엽니다. 최초 관리자 설정 명령은 관리자 이름과 표시 이름을 입력받고 암호를 두 번 확인합니다. 구현상 암호는 15자 이상이어야 합니다. 초기화되지 않은 데이터베이스에서만 부트스트랩할 수 있습니다. 서버는 실행 터미널에서 `Ctrl+C`로 종료합니다.

wheel 설치는 `python -m pip install ./dist/es_rag_tuning_workbench-<version>-py3-none-any.whl`을 사용한 뒤 같은 `python -m es_rag_tuner` 명령을 사용할 수 있습니다. 독립 R11 QA는 새 가상환경에 wheel을 설치해 모듈, 콘솔 entry point, 버전 metadata와 포함된 web asset을 확인했습니다. 검사한 wheel에는 제3자 샘플 데이터 두 파일도 포함됩니다. 별도 재배포 허가가 해결되지 않았으므로 공개 배포가 허가된 산출물로 간주하지 마세요.

### 선택 기능

필요한 항목만 설치합니다.

```bash
.venv/bin/python -m pip install -e '.[semantic]'
.venv/bin/python -m pip install -e '.[reranker]'
.venv/bin/python -m pip install -e '.[token-preview]'
.venv/bin/python -m pip install -e '.[private-vector]'
.venv/bin/python -m pip install -e '.[agents]'
```

선택 의존성은 버전 범위로 선언되어 있으며 `requirements-dev.lock`에 고정되어 있지 않습니다. 설치 시 pip가 버전을 해석합니다. `agents` extra는 Python 버전 marker를 사용하므로 Python 3.10에서는 Copilot SDK가 선택되지 않습니다. 모델 가중치, 토크나이저, 재순위화 모델 파일은 프로젝트 패키지에 포함해 배포하는 자산이 아닙니다. 구현된 기능에서는 별도 캐시에 저장하며 다운로드 준비/동의 절차가 적용되는지 기능별로 확인하세요. 모델을 사용하기 전 식별자, 고정 revision, 캐시 동작, upstream 사용 조건을 검토하세요. [의존성 및 자산 목록](release/dependency-license-inventory.md)을 참고하세요.

### 로컬 Docker Compose

Compose 구성은 Linux Docker Engine 전용 일회용 loopback 개발 환경입니다. 실행 전 [Compose 안내](compose.md)를 읽으세요. Linux host network를 사용하고 두 서비스는 `127.0.0.1`에 바인딩되며, 기본 포트는 앱 `18765`, Elasticsearch `19200`이고 데이터는 project-scoped named volume에 저장됩니다. 기존 서비스를 검사하거나 중지하지 않으므로 사용하지 않는 포트와 고유 프로젝트 이름을 선택하세요. 이 예제는 Elasticsearch 보안을 끄므로 loopback 밖으로 노출하면 안 됩니다.

```bash
docker compose -p es-rag-local -f compose.yaml up -d --build
docker compose -p es-rag-local -f compose.yaml exec workbench python -m es_rag_tuner auth bootstrap-admin
```

다른 포트를 쓰려면 `ES_RAG_APP_PORT`와 `ES_RAG_ES_PORT`에 사용하지 않는 loopback 포트를 지정하고 모든 Compose 명령에 동일하게 적용합니다. 앱 계정 부트스트랩은 별도로 해야 합니다. `docker compose -p es-rag-local -f compose.yaml down`은 named volume을 보존합니다. `-v`는 해당 프로젝트의 저장 데이터를 지우려는 경우에만 추가하세요. 독립 R11 QA는 임시 포트에서 loopback 부트스트랩, synthetic 검색과 named-volume 영속성을 확인했습니다. Compose image에는 별도 재배포 권리가 해결되지 않은 제3자 샘플 데이터가 포함되므로 공개 배포 산출물로 간주하지 마세요. 자세한 내용은 [지원 범위](support-matrix.md)와 [자산 감사](release/third-party-asset-audit.md)를 확인하세요.

### 데이터 및 인증 정보

기본 로컬 계정 및 workbench 상태 경로는 `~/.local/share/es-rag-workbench/concepts.sqlite3`이고 추가 계정 상태 파일은 이 경로 옆의 `concepts.sqlite3.accounts/`에 있습니다. `ES_RAG_CONCEPT_DB`로 기본 DB 경로를 지정할 수 있습니다. 모델 캐시 기본 경로는 `~/.cache/es-rag-workbench/`이고 임베딩 캐시는 `ES_RAG_MODEL_CACHE`로 변경합니다. 토큰 미리보기 자산은 `~/.cache/es-rag-workbench/token-preview`에 별도로 저장되며 `ES_RAG_TOKEN_PREVIEW_CACHE`로 경로를 바꿀 수 있습니다. 이 경로는 로컬 사용자 데이터로 보호하세요. Elasticsearch 인증 정보는 연결 시 입력하며 로컬 앱 계정 DB에 저장하지 않습니다. 자세한 내용은 [보안 안내](../SECURITY.md)를 참고하세요.
