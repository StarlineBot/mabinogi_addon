# 자원 등록 테스트 준비와 해제 취소 회귀 수정

- 날짜: 2026-10-19 (Asia/Seoul).
- 기준: `6b5d50e`의 전투 보조 조작 정돈 독립 QA.
- 분류: 테스트 준비/릴리즈 게이트 결함. 제품 구현과 공개 변경 설명은 수정하지 않는다.

## 재현과 원인

기존 `test_cleared_region_cannot_be_restored_by_pending_detection`을 단독 실행해
실패를 확인했다. 해제 클릭이 무시되어 빈 결과 대신 도르카/투아림 후보가 적용됐다.
실제 앱의 해제 실패가 아니라 fixture가 `_region`과 `_cfg['box']`만 대입해 버튼이
미등록 상태의 비활성으로 남은 것이다. 같은 검사를 MainWindow 새 프로세스에서
다시 실행하므로 QA의 두 실패는 하나의 준비 오류에서 발생했다.

## 변경

- `runtime` fixture는 캡처/판독/게임/로그인 대체 경계를 먼저 설치한 후 기존
  `save_boxes()`와 두 실제 `_accept_region()` 경로를 사용해 준비한다.
  디스크·컨트롤러·등록 상태/해제 버튼이 실제 등록 후와 일치한다.
- 테스트에서 직접 `setEnabled(True)`하지 않는다. 제품의 미등록 명령 비활성 정책,
  영역 세대 가드, 저장 실패/취소 동작은 바꾸지 않는다.
- 등록 준비 계약을 별도 검사하고, 진행 중 해제 검사에 클릭 전 활성 상태와 해제 후
  메모리/디스크 영역 없음·버튼 비활성·후보 승인 없음 assertion을 유지/추가했다.
- 기존 독립 QA 보고서와 재현 스크립트는 변경하지 않는다. 해당 스크립트는 이전의
  비활성 fixture 상태를 먼저 단정하는 진단 자료로, 수정된 fixture의 합격 기준은 아니다.
  원래 일반 회귀 및 QA의 실제 등록 대조 probe로 수정 결과를 검증한다.

## 검증

원래 실패와 MainWindow 새 프로세스 재실행은 **2 passed (4.16초)**로 확인했다.
공유 fixture를 사용하는 자원 조합/공통 설정/null 복구와 자동설정을 추가 검사한다.

초기 묶음 명령은 서로 다른 경로의 `probe.py` 두 개를 동시에 모아 pytest 모듈 이름
충돌로 수집 단계에서 중단됐다. 독립 probe를 별도 실행으로 분리했으며 이를 제품 실패나
테스트 통과로 집계하지 않는다. 파일 삭제나 실패 skip으로 우회하지 않았다.

최종 관련 실행은 **82 passed (65.04초)**였다. 새 프로세스 계약 13개, 자원 8개 조합,
공통 등록/해제/취소/쓰기 실패/로그아웃/종료/null 복구와 실제 공통 모델 검사를 포함한다.
독립 조작 정돈 probe **4 passed (4.80초)**, 이전 교차 기능 probe **4 passed (3.44초)**도 확인했다.
원래 null 스크립트와 일반 회귀 편입 조건은 중복되므로 모두 고유 사례로 합산하지 않는다.
`git diff --check`도 통과했다. 이전 QA의 제품 511개 통과는 기존 제품 검증 자료이며,
이번 실행으로 전체 앱을 다시 검증했다고 주장하지 않는다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_resource_common_settings.py -k cleared_region -q --tb=short
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_resource_integration.py tests/test_resource_common_settings.py tests/test_resource_null_sections.py tests/test_setup_common_resources.py docs/qa/assets/common_resource_settings_20261018/probe.py scripts/qa_common_resource_null_section_20261018.py -q --tb=short
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest docs/qa/assets/interaction_polish_20261019/probe.py -q --tb=short
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest docs/qa/assets/dialogue_registration_fix_20261018/probe.py -q --tb=short
```

## 제한

Linux Qt offscreen 및 기존 외부 장치 대체 경계의 결과다. 실제 Windows 네이티브,
exe·게임·DPI·장시간 자원 검사는 실행하지 않는다. 제품 코드가 바뀌지 않으므로
공유 fixture와 소비자 경로에 검증 범위를 맞춘다. Windows Actions·태그·릴리즈는
실행하지 않으며 수정 자료는 후속 QA를 위해 main에 반영한다.
