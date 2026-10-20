# 원버튼 검증·배포 개발 기록

- 날짜: 2026-10-20 (Asia/Seoul).
- 요구사항: [QA 개발 전달문](qa/배포검증_수동절차_개선전달_20261020.md).
- 상태: 구현과 개발 회귀 완료. **후속 독립 QA 및 실제 Actions 실행은 별도**다.
- 앱 코드·설정·작성자 대사·버전/공개 릴리즈 노트는 변경하지 않았다. 0.7.1 재배포나
  태그·Release 생성, 무거운 Windows workflow 실행도 하지 않았다.

## 동작

`windows.yml`은 수동 실행만 받는다. main의 시작 SHA와 버전·모드·run/attempt를 작은 승인 기록에
먼저 고정한다. 기본 `verify-only`는 게시하지 않는다. `validate-and-publish`는 격리 회귀·네이티브·
exe 빌드·seal/보관을 각각 한 번 수행하며, 후보 manifest에도 동일한 승인 출처/모드를 기록한다.

검증 전체 completed/success 뒤 `release.yml`의 완료 이벤트가 연결된다. 승인 확인 단계는
공개 저장소 토큰 없이 동작한다. 검증만이면 여기서 끝나며 공개 저장소 checkout/게시 단계를
실행하지 않는다. 게시 승인일 때만 후보 다운로드·태그 전 검사·create-only 태그 생성·원격 ref
재확인·태그 필수 최종 게이트·기존 동일 바이트 게시를 이어간다. 테스트나 빌드는 다시 하지 않는다.
기존 `check_context`의 전체 실행 완료/성공 조건과 필수 단계 성공 조건을 유지했다.

`publish-existing`은 Ubuntu 승인 작업만 실행하며 Windows job 전체를 건너뛴다. 승인 시점 소스의
fingerprint/버전에 맞는 후보가 정확히 하나 있어야 한다. run/최신 attempt/아티팩트 ID와
manifest 해시를 고정해 완료 후 다른 후보로 바꾸지 않는다. 여러 후보가 일치할 때만
`candidate_run` 하나로 식별한다. 후보 없음·만료·퇴출·변조는 중단하며 재검증을 자동 시작하지 않는다.
과거 검증만 후보를 그대로 자동 게시하지 않고, 이 새 실행이 그 후보에 대한 명시적 게시 승인이다.

## 게이트와 비용

- 실행 이벤트와 API 양쪽에서 같은 저장소/head repository·workflow ID/path·main·원래 dispatch·
  정확한 SHA/attempt·전체 성공을 확인한다. 이전 완료 이벤트가 최신 attempt를 대신 승인하지 않는다.
- artifact는 정확한 실행의 보관 자료만 받는다. 제한된 flat ZIP 파일명/총 크기만 허용하며
  경로 이탈·symlink·추가 코드·중복/추가 파일을 거부한다. 내려받은 Python/shell은 실행하지 않는다.
- 일반 Markdown 차이만 허용한다. 후보 SHA, 승인 SHA, 신뢰한 실행 checkout, 현재 origin/main의
  중요 입력이 일치해야 한다. 새 workflow/scripts 자체도 입력이므로 과거 0.7.1 후보는 재사용할 수 없다.
- 태그 전에도 manifest·파일 해시/크기·수명·JUnit·버전·출처·게시 승인·기존 양 저장소 Release를
  확인한다. 태그는 원자적인 새 ref 생성 API로만 만든다. 기존 태그가 같은 SHA여도 거부한다.
- 태그 생성 후 최종 gate와 게시 직전 재검사를 유지한다. 부분 게시/중복 이벤트/재실행은 기존
  Release나 태그를 덮어쓰지 않는다. 업로드한 exe는 다시 내려받아 SHA256을 확인한다.
- 후보 payload 200MiB·1일·최대 2개와 기존 후보만 정리하는 정책을 유지했다.
  수 KiB 승인 artifact는 별도로 1일 보관한다. 양 workflow는 같은 concurrency 그룹으로 직렬화하며
  부모가 자식 완료를 기다리지 않는다. GitHub concurrency는 영구 큐가 아니므로 동시 예약을 피한다.

## 개발 검증

기존 회귀/기능 묶음 inventory를 먼저 확인하고 `tests/test_release_candidate.py`와
`tests/test_windows_ci.py`에 새 경계와 연결 사례를 추가했다. 별도 QA 경로에 같은 사례를 중복 수집하지 않았다.
기존 출처/필수 단계/해시/만료/게시 바이트 검사는 유지하고, 실제 HTTP·Git·게시 쓰기만 대체한
prepare → 완료 이벤트 → 승인/후보 게이트 → 태그 API → delivery 연결을 실행했다.

```bash
UV_CACHE_DIR=/tmp/deployment-uv-cache uv run pytest -q tests/test_release_candidate.py tests/test_windows_ci.py
UV_CACHE_DIR=/tmp/deployment-uv-cache uv run pytest -q --regression-group=delivery -m 'not windows_integration' --junitxml=/tmp/deployment-delivery-results.xml
/tmp/actionlint .github/workflows/windows.yml .github/workflows/release.yml
git diff --check
```

- 후보/게시/workflow 회귀: **148 passed**.
- 관련 delivery 기능 묶음 전체: **195 passed, 1989 deselected / 18.15초**.
- actionlint **1.7.7**: 두 workflow 오류 없음. `git diff --check` 통과.
- 성공 연결: 검증만 게시 0회, 조건부 승인 태그 1회/양 저장소 게시, 기존 후보는 원래 검증만
  모드를 보존한 채 새 승인으로 게시. 원래 후보 attempt 2와 승인 run attempt 3을 구분했다.
- 차단 연결: 승인/모드 누락·위조, 실패/취소·PR/fork·잘못된 workflow/소스/회차,
  요청 보관 실패/skip·출처/만료, 후보 만료·퇴출·손상·변경, 필수 단계 skip,
  main/checkout 입력 변경·태그 충돌. **새 태그/게시 모두 0회**를 확인했다.
- 선택/재실행: 후보 없음·만료·다른 입력·복수 후보에서 임의 최신 성공/재빌드로 전환하지 않음,
  선택한 manifest 변경 거부, 중복 완료 이벤트의 태그/게시 횟수 증가 없음.
- 외부 실패: 태그 권한 403·경합 422·생성 후 잘못된 원격 ref·기존 부분 Release에서 게시 0회.
  태그 생성 이후 오류는 이미 생긴 태그를 지우거나 이동하지 않는다.
- 기존 성공 run의 REST 메타데이터를 읽어 실제 repository/head_repository/path/attempt/event
  필드 형태를 확인했다. 이는 새 자동화 실행 성공이나 실제 태그 쓰기 권한 확인은 아니다.

## 남은 실제 환경 확인

개발 중 Actions 실행·태그 생성·게시를 하지 않았다. 후속 독립 소스 QA 후 사용자가 새 미사용
버전/노트를 준비하고 배포 모드로 실행해야 한다. 실제 Windows 검사/빌드, workflow_run 전달,
artifact 다운로드 리다이렉트, Actions 태그 생성 권한/정책과 양 저장소 게시 권한은 그 실행에서
확인해야 한다. 권한/정책 오류를 보호 우회나 수동 태그 강요로 처리하지 않는다.
실게임·혼합 DPI·장시간 자원 계측은 자동 배포 게이트가 대신하는 범위가 아니다.

사용법과 실패 복구는 [Windows 검증 문서](windows-validation.md)를 따른다.
