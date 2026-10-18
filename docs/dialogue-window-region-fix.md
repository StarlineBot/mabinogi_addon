# 제작자 잡담 창 영역 판정 보완

- 날짜: 2026-10-19 (Asia/Seoul).
- 기준: `977015b` 및 CEF 전체창 가림 거부 로그 QA.
- 체력바 전환 수정은 후속 QA에서 통과했다. 이번 변경은 잡담의 창 가림 판정과 진단이다.

## 실제 로그와 분류 한계

v0.4.90의 수동 클릭 12건은 CEF-OSC-WIDGET/전체 화면 경계/전역 알파 flags=0에서
가림으로 차단됐다. 클릭 미전달/대사 부재/추첨 실패가 아니다. 로그는 픽셀별 투명도나
실제 window region을 담지 않아 오차단의 정확한 시각적 원인은 확정하지 않는다.
클래스명이나 alpha=0만으로 무조건 표시하는 예외는 넣지 않는다.

## 변경과 확인한 결함

- 명시적인 실제 창 영역이 대상과 겹치지 않아도 전체 사각형만으로 차단하는 조건을
  API 대체 입력으로 재현했다. 수정 전 현재 소스를 메모리로 로드한 검사 3개가 실패했다.
- 전역 알파 0으로 제외하지 못한 가림 후보에 GetWindowRgn을 적용한다. NULLREGION은
  명시적으로 빈 영역이며 ERROR(정보 없음)와 구분한다. SIMPLE/COMPLEX 영역은
  얼굴·말풍선의 사각형 전체와 RectInRegion으로 교차 여부를 검사한다.
- 창 영역 좌표는 DWM 확장 경계가 아닌 GetWindowRect의 원점을 사용한다. 중심 한 점만
  검사하지 않으므로 모서리 한 픽셀 또는 말풍선만 가려져도 보수적으로 차단한다.
- 정보 없음/조회 실패/불투명 겹침/부분 알파/flags=0만 있는 경우는 여전히 보류한다.
  이 변경은 per-pixel 합성 투명도를 읽거나 CEF 창을 일괄 무시하는 기능이 아니다.
- 임시 GDI 영역은 finally에서 해제한다. 새 캡처, 폴링, 워커, 타이머, 입력 자동화,
  타 프로세스 메시지 호출이나 포커스 이동은 없다.
- 수동 클릭의 차단 진단에만 PID/실행파일 basename 조회를 추가했다. 제한 정보 조회로
  연 핸들을 finally에서 닫고 HWND의 PID가 바뀌면 파일명/PID를 채택하지 않는다.
  자동 tick은 프로세스 조회를 하지 않으며 제목/전체 경로/예외 메시지는 기록하지 않는다.

## 검증

새 회귀는 빈/분할/정보 없는 영역, 모서리/두 번째 대상 겹침, 다른 원점, API 실패,
반복 1000회 핸들 잔존 없음, 실제 Qt 클릭 복구/재차 차단, 진단 조회 실패/PID 변경과
프로세스 핸들 해제를 검사한다. 기존 실제 로그 probe는 바꾸지 않고 계속 통과해야 한다.
flags=0이고 실제 영역 정보도 없는 기존 probe의 차단 기대값을 완화하지 않았다.

초기 회귀에서 `_eligible`에 추가한 진단 인자를 기존 무인자 테스트 대체 함수가 받지
못했다. 대체 함수에 진단 인자를 추가하고 수동/자동에 맞는 값까지 검사했다.
기존 거부/로그/만료/표시 불가 assertion은 유지했다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dialogue_window_region.py docs/qa/assets/dialogue_cef_occlusion_20261019/probe.py tests/test_dialogue_transparent_occlusion.py tests/test_dialogue_desktop_failure.py tests/test_creator_dialogue.py tests/test_main_shutdown.py tests/test_release_notes.py -q --tb=short
```

- **120 passed, 1 skipped (30.49초)**. skip은 기존 실제 Windows HWND/DWM 통합 검사다.
- 프로세스 핸들을 닫기 전에 HWND/PID를 다시 확인하도록 마지막 경계를 보완하고
  창 영역/소유자 회귀 **15개를 재검증**했다. 공개 노트 변경 뒤 검사도 **7개 통과**했다.
  이 수치는 앞선 120개와 중복이므로 합산하지 않는다.
- `compileall`, `git diff --check` 통과. 기존 v0.4.90 이하 공개 노트는 원격 태그와 동일하다.

## 남은 확인

실제 CEF 창이 region 정보를 제공하지 않는 per-pixel 합성 창이면 이번 수정 후에도
거부될 수 있다. **사용자 PC의 라이브 해결 완료로 판정하지 않는다.** 보강한 수동 클릭
진단의 영역 결과와 실행파일 식별자로 실제 차단 상태를 이어서 구분할 수 있다.
같은 구형 로그 재수집이나 다른 앱 종료를 요구하는 것으로 조사를 대신하지 않는다.

Linux Qt offscreen/명시적 Windows API 대체 검사이며 실제 Windows 합성·DPI·게임·
GDI 카운터/장시간 자원·exe는 미검증이다. Actions·태그·릴리즈는 실행하지 않는다.
이미 배포된 v0.4.90 노트를 보존하고 다음 미사용 v0.4.91에 변경 설명만 추가한다.
