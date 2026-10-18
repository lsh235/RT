# Local Docker Compose setup / 로컬 Docker Compose 설정

This setup runs the workbench and a disposable Elasticsearch 9.5.5 node on a **Linux Docker Engine**. Both processes bind to `127.0.0.1`; no service is published on a LAN or public interface. Elasticsearch security is disabled, so this configuration is for loopback development only.

이 설정은 **Linux Docker Engine**에서 워크벤치와 임시 Elasticsearch 9.5.5 노드를 실행합니다. 두 프로세스 모두 `127.0.0.1`에 바인딩되며 LAN이나 외부 인터페이스에 서비스를 공개하지 않습니다. Elasticsearch 보안 기능은 비활성화되어 있으므로 이 구성은 로컬 루프백 개발 전용입니다.

## Requirements / 준비 사항

- Linux with Docker Engine and the `docker compose` plugin. Both services use host networking so the workbench can keep its loopback-only server bind and reach Elasticsearch through `127.0.0.1`. Docker Desktop on macOS/Windows does not provide this same host-network behavior for this configuration.
- Docker Compose builds the workbench image from the checked-out source. Elasticsearch uses the pinned `docker.elastic.co/elasticsearch/elasticsearch:9.5.5` image.
- Allow at least 1 GB of available memory for Elasticsearch. On Linux hosts where Elasticsearch requires it, set `vm.max_map_count` to `262144` according to your OS's persistent sysctl procedure; this project does not change host sysctls.

- Linux와 Docker Engine, `docker compose` 플러그인이 필요합니다. 두 서비스는 host network를 사용하므로 워크벤치의 루프백 전용 바인딩을 유지하면서 `127.0.0.1`로 Elasticsearch에 연결합니다. macOS/Windows의 Docker Desktop은 이 구성과 동일한 host-network 동작을 제공하지 않습니다.
- Compose는 체크아웃한 소스에서 워크벤치 이미지를 빌드합니다. Elasticsearch 이미지는 `docker.elastic.co/elasticsearch/elasticsearch:9.5.5`로 고정되어 있습니다.
- Elasticsearch가 사용할 수 있는 메모리를 1 GB 이상 확보하세요. 필요한 Linux에서는 운영체제의 지속 설정 절차에 따라 `vm.max_map_count`를 `262144`로 설정하세요. 이 프로젝트는 호스트 sysctl을 변경하지 않습니다.

## Start / 시작

Run these commands from the repository root. Defaults are workbench port `18765` and Elasticsearch port `19200`; choose unused loopback ports by setting `ES_RAG_APP_PORT` and `ES_RAG_ES_PORT` before each Compose command. Do not choose ports already used by another service.

아래 명령은 저장소 루트에서 실행합니다. 기본 워크벤치 포트는 `18765`, Elasticsearch 포트는 `19200`입니다. 사용하지 않는 루프백 포트를 선택하고 Compose 명령 앞에 `ES_RAG_APP_PORT`와 `ES_RAG_ES_PORT`를 설정하세요. 다른 서비스가 사용하는 포트는 선택하지 마세요.

```sh
docker compose -p es-rag-local build
docker compose -p es-rag-local up -d
docker compose -p es-rag-local ps
```

To use alternate ports, use the same values for every Compose command in this shell (example: `ES_RAG_APP_PORT=18766`, `ES_RAG_ES_PORT=19201`):

다른 포트를 쓰려면 이 셸에서 실행하는 모든 Compose 명령에 동일한 값을 사용하세요(예: `ES_RAG_APP_PORT=18766`, `ES_RAG_ES_PORT=19201`).

```sh
ES_RAG_APP_PORT=18766 ES_RAG_ES_PORT=19201 docker compose -p es-rag-local up -d --build
```

Compose uses Linux host networking. The `network.host` setting makes Elasticsearch itself bind to `127.0.0.1`; the workbench command explicitly binds to `127.0.0.1`. There are no wildcard host port mappings. The project name scopes the named volumes and Compose-managed containers; no fixed container names are assigned. Pick a project name unique to your checkout if you run more than one copy.

Compose는 Linux host network를 사용합니다. `network.host` 설정으로 Elasticsearch 프로세스가 `127.0.0.1`에 바인딩되고, 워크벤치 명령도 `127.0.0.1` 바인딩을 지정합니다. 전체 인터페이스에 대한 포트 매핑은 없습니다. 프로젝트 이름은 named volume과 Compose 관리 컨테이너의 범위를 구분하며 컨테이너 이름을 고정하지 않습니다. 여러 복사본을 실행한다면 체크아웃마다 고유한 프로젝트 이름을 사용하세요.

## Health, first login, and read-only search / 상태 확인, 최초 로그인, 읽기 전용 검색

Check both Compose health states, then query each loopback endpoint:

Compose의 두 서비스 상태를 확인한 다음 각 루프백 엔드포인트를 조회합니다.

```sh
docker compose -p es-rag-local ps
curl --fail http://127.0.0.1:19200/
curl --fail http://127.0.0.1:18765/api/health
```

On first use, create the local workbench administrator explicitly. The command prompts for the password; it is stored in the workbench database volume. Use the same port overrides on this command when you started Compose with alternate ports.

처음 사용할 때 로컬 워크벤치 관리자를 명시적으로 생성합니다. 명령이 비밀번호를 입력받으며, 계정 정보는 워크벤치 데이터 볼륨에 저장됩니다. 다른 포트로 Compose를 시작했다면 이 명령에도 동일한 포트 설정을 사용하세요.

```sh
docker compose -p es-rag-local exec workbench python -m es_rag_tuner auth bootstrap-admin
```

Open `http://127.0.0.1:18765`, sign in, and create a connection with URL `http://127.0.0.1:19200` and authentication type `none`. If you selected alternate ports, substitute the values of `ES_RAG_APP_PORT` and `ES_RAG_ES_PORT` in the URL, health check, and `curl` examples below. The bundled Elasticsearch node starts empty. For a minimal synthetic search, create an index with the nested `comments` mapping used by the default lexical query, insert one throwaway document, then run a read-only BM25 search. In its search page, use index `compose-smoke` and query `"loopback smoke"`.

`http://127.0.0.1:18765`를 열고 로그인한 뒤 URL이 `http://127.0.0.1:19200`이고 인증 유형이 `none`인 연결을 만드세요. 다른 포트를 선택했다면 아래 URL, 상태 확인 및 `curl` 예제에서 `ES_RAG_APP_PORT`와 `ES_RAG_ES_PORT` 값을 바꿔 사용합니다. 포함된 Elasticsearch 노드는 빈 상태로 시작합니다. 최소 합성 검색을 위해 기본 lexical 질의가 사용하는 중첩 `comments` 매핑으로 인덱스를 만들고 임시 문서를 색인한 후 BM25 읽기 전용 검색을 수행합니다. 검색 화면에서 인덱스 `compose-smoke`, 검색어 `"loopback smoke"`를 사용하세요.

```sh
curl --fail -X PUT http://127.0.0.1:19200/compose-smoke \
  -H 'Content-Type: application/json' \
  -d '{"mappings":{"properties":{"summary":{"type":"text"},"comments":{"type":"nested","properties":{"body":{"type":"text"}}}}}}'

curl --fail -X PUT http://127.0.0.1:19200/compose-smoke/_doc/1 \
  -H 'Content-Type: application/json' \
  -d '{"summary":"Loopback smoke document","comments":[{"body":"A synthetic loopback smoke search document."}]}'
```

The `curl` request writes only the synthetic document. Search actions in the workbench are read-only. Remove this throwaway index from Elasticsearch when finished if you want an empty node again.

위 `curl` 요청은 합성 문서만 기록합니다. 워크벤치의 검색 동작은 읽기 전용입니다. 다시 빈 노드가 필요하면 사용 후 Elasticsearch에서 임시 인덱스를 삭제하세요.

## Data and cleanup / 데이터와 정리

Elasticsearch indices are stored in the project-scoped `elasticsearch_data` volume. Workbench accounts, SQLite state, and private knowledge records are stored in `workbench_data`. Ordinary `docker compose down` stops and removes this project's containers but keeps both named volumes, so restarting with the same project name preserves data. Host networking does not create a Compose bridge network for these services.

Elasticsearch 인덱스는 프로젝트 범위의 `elasticsearch_data` 볼륨에 저장됩니다. 워크벤치 계정, SQLite 상태, 개인 지식 레코드는 `workbench_data` 볼륨에 저장됩니다. 일반 `docker compose down`은 해당 프로젝트의 컨테이너를 중지하고 제거하지만 두 named volume은 보존하므로 같은 프로젝트 이름으로 다시 시작하면 데이터가 유지됩니다. Host network를 사용하므로 Compose bridge network는 생성하지 않습니다.

```sh
docker compose -p es-rag-local down
```

`docker compose down -v` also deletes this project's named volumes and permanently removes their contents. Run it only when you intend to discard both Elasticsearch and workbench data. Never use a broad Docker prune command for this cleanup.

`docker compose down -v`는 프로젝트의 named volume도 삭제하고 내부 데이터를 영구 제거합니다. Elasticsearch와 워크벤치 데이터를 모두 폐기하려는 경우에만 실행하세요. 정리에 범위가 넓은 Docker prune 명령을 사용하지 마세요.

## Security boundary / 보안 경계

The bundled Elasticsearch node disables authentication and TLS and is intended only for this local loopback setup. Do not expose it by changing either service to `0.0.0.0`, adding wildcard port publishing, or placing it on an externally reachable network. For shared, remote, or production Elasticsearch, use an independently secured deployment and configure its endpoint and credentials in the workbench.

포함된 Elasticsearch 노드는 인증과 TLS가 비활성화되어 있으며 이 로컬 루프백 설정 전용입니다. 서비스를 `0.0.0.0`으로 변경하거나 전체 인터페이스에 포트를 공개하거나 외부에서 접근 가능한 네트워크에 연결해 노드를 노출하지 마세요. 공유/원격/운영용 Elasticsearch는 별도로 보안을 적용하고 워크벤치에 해당 엔드포인트와 인증 정보를 설정하세요.
