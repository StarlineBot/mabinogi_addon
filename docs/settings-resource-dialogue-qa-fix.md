# 공통 자원 설정 및 제작자 잡담 QA 후속 수정

- 날짜: 2026-10-18 (Asia/Seoul).
- 기준: `6b0df45`의 현재 소스 및 설정 그룹화 독립 QA, 제작자 잡담 클릭 무반응 재발 보고서.
- Windows Actions, 태그 및 릴리즈는 실행하지 않는다.

## 공통 자원 설정

수정 전 독립 재현은 **4 failed, 2 passed**였다. 도르카/투아림 섹션이 null이면
확인 이후 동시 변경 비교에서 AttributeError가 발생했고, 공통 해제도 실패했다.
기존 `setup_state.section()` 경계를 비교와 변경에 적용해 비-dict 섹션을 정규화했다.
영역 키만 변경하며 정상 섹션의 세부 옵션, 취소/쓰기 실패/동시 변경 가드는 유지한다.

독립 재현을 일반 회귀로 편입했다. null, 키 없음, 문자열, 목록, 숫자에서 한쪽 등록과
다른 쪽 설정 보존, 공통 해제를 추가로 검사한다. 기존 독립 QA 자료는 수정하지 않는다.

## 제작자 잡담

실제 로그는 클릭 전달과 유효 대사 52개를 확인했으나 Windows 내부 실패 경계는
기록하지 못했다. 실제 사용자 PC의 원인을 확정하지 않는다.

별도 API 대체 입력으로, 얼굴/말풍선과 겹치지 않는 창의 cloak 조회가 실패하면
전체 노출을 거부하는 경로를 재현했다. 현재 수정 전 소스를 메모리에 로드해 검사한
두 경우(HRESULT 실패/예외)는 모두 실패했다. 창 경계를 먼저 확인하고 겹치는 경우만
cloak을 조회한다. 실제 가림, 겹치는 창의 불확실한 상태, 잠금, 화면 밖은 계속 거부한다.
전역 알파 0만 제외하는 기존 보수적 투명창 정책과 포커스 비간섭도 유지한다.

호출별 진단은 실패 단계, 대상 물리 좌표, 차단 HWND/경계, 가능한 클래스·알파·HRESULT와
예외 종류/오류 번호를 담는다. 창 제목, 예외 메시지, 화면 캡처, 전체 창 목록은 수집하지 않는다.
자동 tick은 거부 로그를 남기지 않고 수동 클릭 거부 시 기존 INFO 로그에만 상세를 추가한다.
새 타이머·구독·워커·공유 진단 캐시는 추가하지 않는다.

## 검증 및 제한

집중 검사에서 공통 null 재현과 가림 판정은 **25 passed, 1 skipped**였다.
skip은 기존 실제 Windows HWND/DWM 통합 검사이며 새로 추가한 skip이 아니다.
- 관련 회귀 **176 passed, 1 skipped (59.10초)**: 잡담/투명창, null 복구, 공통 등록,
  실제 공통 모델, 자동설정, 영역 해제, MainWindow 종료 및 QA의 실제 원본 추가 검사.
- 입력 데스크톱 API 실패의 종류/오류 번호와 핸들 해제를 보완한 뒤 최종 영향 검사
  **112 passed, 1 skipped (17.69초)**. 앞선 검사와 중복되므로 합산하지 않는다.
- `compileall` 및 `git diff --check` 통과. 기존 assertion/누수 검사와 외부 장치 격리를 유지했다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dialogue_transparent_occlusion.py tests/test_resource_null_sections.py tests/test_creator_dialogue.py tests/test_resource_common_settings.py tests/test_resource_pair.py tests/test_setup_common_resources.py tests/test_region_registration.py tests/test_main_shutdown.py docs/qa/assets/common_resource_settings_20261018/probe.py -q --tb=short
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dialogue_desktop_failure.py tests/test_dialogue_transparent_occlusion.py tests/test_creator_dialogue.py tests/test_resource_null_sections.py tests/test_release_notes.py -q --tb=short
```

Linux Qt offscreen 및 명시적 Windows API 대체 입력 결과다. 실제 Windows 합성,
사용자 PC에서의 잡담 재현, 혼합 DPI, 게임 전환, 장시간 리소스, exe는 미검증이다.
기존 라이브 제보는 이 수정만으로 해결 완료라고 단정하지 않으며, 계속 거부되면 보강된
클릭 진단으로 실제 차단 단계와 창을 확인한다. 동일한 구형 로그 재수집으로 대신하지 않는다.
