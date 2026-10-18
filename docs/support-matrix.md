# Support matrix / 지원 범위

This matrix records the evidence present in this checkout as of 2026-10-19. “CI configured” describes workflow configuration; it does not mean that the current branch's remote workflow has run. R11 independent results are recorded in the [R11 QA report](acceptance/v1.16.0-independent-qa.md). No row is a production deployment or security certification.

이 표는 2026-10-19 현재 체크아웃에서 확인한 근거를 기록합니다. “CI 설정”은 워크플로 정의를 뜻하며 현재 브랜치의 원격 CI 실행을 뜻하지 않습니다. R11 독립 검증 결과는 [R11 QA 보고서](acceptance/v1.16.0-independent-qa.md)에 기록합니다. 어떤 항목도 운영 배포 또는 보안 인증을 의미하지 않습니다.

**Evidence labels / 근거 표기:** **CI configured** = workflow declares the environment, run result not present here; **independently exercised** = a prior independent report records an execution; **inferred** = source/configuration indicates an intended path, without a runtime pass; **unverified / NOT RUN** = no qualifying run is recorded.

**근거 표기:** **CI configured**는 workflow가 환경을 선언했다는 뜻이고, 이 문서에 실행 결과가 없다는 의미를 함께 가집니다. **independently exercised**는 이전 독립 보고서에 실행이 기록된 경우입니다. **inferred**는 소스/설정에 의도된 경로가 보이지만 runtime 통과 근거가 없는 경우입니다. **unverified / NOT RUN**은 인정 가능한 실행 기록이 없다는 뜻입니다.

| Area | Recorded evidence | Status / boundary |
| --- | --- | --- |
| Python 3.10, 3.12 | `.github/workflows/ci.yml` configures offline jobs for both; `.github/workflows/ci.yml` also configures ES acceptance on Python 3.12. Current R11 independent offline/package validation used Python 3.12; optional `agents` dependency resolution was separately captured on 3.10, 3.11, and 3.12. | Python 3.12 independently exercised for R11. Python 3.10 CI-configured and marker-resolution checked, but the full R11 suite was not run there. Other versions are unverified. |
| Linux | GitHub workflow uses `ubuntu-latest`; v1.15 independent QA ran in WSL2 Linux x86_64. | CI-configured / independently exercised as recorded in [`v1.15.0 independent QA`](acceptance/v1.15.0-independent-qa.md); exact hosted runner image is not pinned. Native macOS and Windows are unverified. |
| Node.js and browser | Browser workflow configures Node 20, `npm ci`, and Playwright-managed Chromium. Independent R11 QA ran the full browser suite; exact runtime versions are in the [R11 QA report](acceptance/v1.16.0-independent-qa.md). | R11 independently exercised with Chromium. Other browsers and versions are unverified. |
| npm tooling | `package-lock.json` lockfile v3 pins Playwright and Playwright Core at 1.64.1. | Locked dependency metadata; not a claim that every host/browser combination is supported. |
| Elasticsearch 9.5.5 | CI config declares `docker.elastic.co/elasticsearch/elasticsearch:9.5.5` for a disposable service; independent R11 QA records task-owned ES and Compose smoke runs. | R11 independently exercised for synthetic search/lifecycle only. No wider version range or sourced-corpus quality is established. |
| Docker / Compose | The checked-in [`compose.yaml`](../compose.yaml) uses Linux host networking, loopback service binds, project-scoped volumes, and Elasticsearch 9.5.5; see [`Compose guide`](compose.md). | R11 independent Compose bootstrap/search/persistence passed. Repeated image builds matched under the same host, toolchain, project configuration, and build arguments. Linux Docker Engine is the intended documented path; Docker Desktop, Podman, Swarm, Kubernetes, and production use are unverified. |
| Optional Python extras | `pyproject.toml` declares `semantic`, `reranker`, `token-preview`, `private-vector`, and `agents`; only the base dependency and `dev` extra are in `requirements-dev.lock`. | Extras are range-constrained, not exact-locked in this repository. Each provider/model and platform combination is unverified unless a separate acceptance record names it. |
| Retrieval quality / production security | No permission-cleared representative corpus/qrels or production security assessment is part of this evidence set. | NOT RUN. No general quality, production-readiness, or public-network claim is made. |

## Reproduction references / 재현 근거

- CI configuration: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- Locked package declarations: [`pyproject.toml`](../pyproject.toml), [`requirements-dev.lock`](../requirements-dev.lock), [`package-lock.json`](../package-lock.json)
- Historical independent evidence: [`v1.15.0 independent QA`](acceptance/v1.15.0-independent-qa.md)
- Current independent evidence: [`v1.16.0 R11 independent QA`](acceptance/v1.16.0-independent-qa.md)
- Current gate status: [`v1.16.0-rc.1 acceptance`](acceptance/v1.16.0-rc.1.md)

## 한국어 해석

Python 3.12, Chromium 브라우저 흐름, Linux Docker Engine/Compose, task-owned Elasticsearch 9.5.5는 R11 독립 QA에서 다시 검증했습니다. Python 3.10 full suite, workflow에 선언된 Python 3.10 전체 테스트, Windows/macOS native 환경, 다른 브라우저, 다른 Elasticsearch 버전, Docker Desktop/Podman, 모든 선택 기능 조합은 검증되지 않았습니다. Compose와 반복 빌드는 기록된 동일 호스트·도구 설정 범위의 결과이며 운영 배포 적합성이나 재현 가능한 검색 품질을 뜻하지 않습니다. 자세한 사용자 설치 절차는 [설치 안내](install.md), 버전 업그레이드 및 복구는 [업그레이드 안내](upgrade.md)를 참고하세요.
