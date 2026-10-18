# Contributing / 기여하기

## English

Thanks for helping improve the local Elasticsearch retrieval workbench. Contributions should keep the tool local-first and preserve its evidence limits: a passing mock, synthetic fixture, or small corpus does not prove general retrieval quality, production readiness, or a security guarantee.

### Before opening a change

1. Search existing issues and documentation for the behavior or interface.
2. Keep changes scoped and explain user-visible behavior, affected data, migration needs, and any new network/model access.
3. Do not add issue dumps, customer data, credentials, private corpora, or model weights. Public issue access and the project's Apache-2.0 code license do not grant permission to redistribute third-party content. See the [asset audit](docs/release/third-party-asset-audit.md).
4. Include or update focused tests and documentation when behavior or an API changes. Do not describe test evidence beyond the fixtures and environment that actually ran.

### Development checks

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python scripts/run_offline_tests.py
.venv/bin/python scripts/package_smoke.py
npm ci
npm run test:browser
```

The browser checks require Node.js and Playwright's Chromium runtime. Live Elasticsearch checks are a separate opt-in workflow; use only an explicitly disposable task-owned endpoint and index. The CI workflow's Elasticsearch service disables security and is configured for the workflow runner, not an external host. Do not point tests at user or production data. Report skipped checks as skipped/NOT RUN, not PASS.

### Pull requests

- Describe the problem, concrete change, and verification commands/results.
- State whether behavior was validated with unit tests, mocks, synthetic data, or a disposable Elasticsearch instance.
- Include migration, backup/restore, compatibility, and rollback effects where applicable.
- Preserve unrelated work and avoid embedding secrets or unlicensed sample content.

## 한국어

로컬 Elasticsearch 검색 작업대를 개선하는 데 기여해 주셔서 감사합니다. 이 프로젝트는 로컬 우선 사용과 근거의 범위를 유지해야 합니다. mock, synthetic fixture 또는 작은 코퍼스에서 통과한 결과는 일반 검색 품질, 운영 준비 상태 또는 보안 보증을 증명하지 않습니다.

### 변경 전

1. 기존 이슈와 문서에서 같은 동작이나 인터페이스를 다뤘는지 확인합니다.
2. 변경 범위를 좁히고 사용자에게 보이는 동작, 영향 데이터, migration 필요성, 새 네트워크/모델 접근을 설명합니다.
3. 이슈 덤프, 고객 데이터, 인증정보, 비공개 코퍼스, 모델 가중치를 추가하지 마세요. 공개 이슈에 접근 가능하거나 프로젝트 코드가 Apache-2.0이라고 해서 제3자 콘텐츠 재배포 허가가 생기지 않습니다. [자산 감사](docs/release/third-party-asset-audit.md)를 확인하세요.
4. 동작이나 API를 바꾸면 범위가 맞는 테스트와 문서를 함께 갱신합니다. 실제 실행한 fixture와 환경보다 넓은 테스트 근거를 주장하지 마세요.

### 개발 점검

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python scripts/run_offline_tests.py
.venv/bin/python scripts/package_smoke.py
npm ci
npm run test:browser
```

브라우저 점검에는 Node.js와 Playwright Chromium 런타임이 필요합니다. 실 Elasticsearch 점검은 별도 opt-in 흐름입니다. 명시적으로 만든 일회용 작업 전용 endpoint와 인덱스만 사용하세요. CI의 Elasticsearch 서비스는 보안을 끄고 workflow runner 안에서 실행하도록 구성되어 있으며 외부 호스트용 설정이 아닙니다. 사용자 또는 운영 데이터를 대상으로 테스트하지 마세요. 건너뛴 점검은 PASS가 아니라 skip/NOT RUN으로 기록합니다.

### Pull request

- 문제, 구체적인 변경, 검증 명령과 결과를 설명합니다.
- 단위 테스트, mock, synthetic 데이터, 폐기 가능한 Elasticsearch 중 어떤 범위에서 확인했는지 적습니다.
- 해당하면 migration, 백업/복원, 호환성, 롤백 영향을 기록합니다.
- 무관한 작업을 보존하고 비밀정보나 라이선스가 불명확한 샘플 데이터를 넣지 않습니다.
