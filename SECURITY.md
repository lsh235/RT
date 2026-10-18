# Security policy / 보안 정책

## English

### Scope and supported use

This project is a local, loopback-first developer workbench. It is not a hosted service or a production multi-tenant security boundary. The server rejects non-loopback bind hosts. Do not put it on a public interface, publish its port beyond the local machine, or place it behind a public reverse proxy. The local account database separates app users; it does not provide Elasticsearch document-level authorization or isolate processes with access to the same host and data directory.

Elasticsearch credentials are connection inputs and are not stored in the app account database. Every user of the workbench should receive only the Elasticsearch permissions they need. Shared indexes may be reachable by multiple local app accounts when their connection credentials allow it. Review queries, snippets, index names and document fields before sharing exported or copied output.

SQLite data defaults to `~/.local/share/es-rag-workbench/concepts.sqlite3`; model/tokenizer caches default under `~/.cache/es-rag-workbench/`. Protect those paths and backups as local data. Optional model downloads are separate from source installation. Optional Codex/Copilot integrations may transmit query or selected document context to the chosen provider; enable them only after reviewing the exact data flow and provider terms.

### Reporting a vulnerability

Please do not publish an exploitable vulnerability, credentials, private documents, or reproduction data in a public issue. Use GitHub's private vulnerability reporting for this repository if it is enabled. If it is not enabled, use the maintainer contact listed on the repository's hosting page to request a private channel; do not include sensitive exploit detail in the initial public message. Include the affected version/commit, impact, prerequisites, and a minimal safe reproduction. Allow maintainers reasonable time to investigate before coordinated disclosure.

This repository does not currently publish a response-time SLA, supported-version window, or security certification. The R11 public release/security gates are still in progress. Review the [support matrix](docs/support-matrix.md) and current [R11 acceptance](docs/acceptance/v1.16.0-rc.1.md) for evidence status.

## 한국어

### 범위와 사용 환경

이 프로젝트는 로컬 loopback 우선 개발 작업대입니다. 호스팅 서비스나 운영용 멀티테넌트 보안 경계가 아닙니다. 서버는 loopback이 아닌 bind 주소를 거부합니다. 공개 인터페이스에 올리거나 포트를 로컬 머신 밖으로 공개하거나 공개 reverse proxy 뒤에 두지 마세요. 로컬 앱 계정은 앱 사용자 데이터를 구분하지만 Elasticsearch 문서 수준 권한을 제공하지 않으며, 같은 호스트와 데이터 경로에 접근할 수 있는 프로세스로부터 격리하지도 않습니다.

Elasticsearch 인증 정보는 연결 입력이며 앱 계정 데이터베이스에 저장되지 않습니다. 각 사용자는 필요한 Elasticsearch 권한만 가진 인증 정보를 사용해야 합니다. 연결 권한이 허용하면 여러 로컬 앱 계정이 공유 인덱스를 조회할 수 있습니다. 결과를 내보내거나 복사해 공유하기 전에 질의, 발췌, 인덱스 이름과 문서 필드를 확인하세요.

SQLite 기본 경로는 `~/.local/share/es-rag-workbench/concepts.sqlite3`이고 모델/토크나이저 캐시는 `~/.cache/es-rag-workbench/` 아래에 기본 저장됩니다. 이 경로와 백업을 로컬 데이터로 보호하세요. 선택 모델 다운로드는 소스 설치와 별개입니다. 선택 Codex/Copilot 연동에서는 질의나 선택 문맥이 provider로 전송될 수 있습니다. 데이터 흐름과 provider 약관을 검토한 뒤 사용하세요.

### 취약점 신고

악용 가능한 취약점, 인증정보, 비공개 문서 또는 재현 데이터를 공개 이슈에 게시하지 마세요. 저장소에서 GitHub 비공개 취약점 신고가 활성화되어 있으면 그 기능을 사용하세요. 비활성화되어 있으면 저장소 호스팅 페이지에 명시된 유지관리자 연락처로 비공개 연락 경로를 요청하고, 최초 공개 메시지에는 민감한 공격 세부사항을 넣지 마세요. 영향 버전/commit, 영향, 전제 조건과 안전한 최소 재현 단계를 포함하세요. 조정된 공개 전에 유지관리자가 조사할 합리적인 시간을 주세요.

현재 저장소는 응답 시간 SLA, 지원 버전 기간 또는 보안 인증을 공표하지 않습니다. R11 공개 릴리스/보안 게이트는 진행 중입니다. 근거 상태는 [지원 범위](docs/support-matrix.md)와 [R11 acceptance](docs/acceptance/v1.16.0-rc.1.md)를 확인하세요.
