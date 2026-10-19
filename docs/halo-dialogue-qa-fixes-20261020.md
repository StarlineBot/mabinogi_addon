# 헤일로·잡담 통합 QA 수정

- 기준: `docs/qa/헤일로개발과_잡담로그_통합QA_20261020.md`의 P1 1건과 P2/P3 API 오호출.
- 수정 전: 영역 해제 3개와 API 계약 2개를 함께 실행해 **5 failed / 31 deselected / 2.28초**로 재현했다.

## 수정

1. 공통 영역 해제 회귀가 가상의 `halo_timer_tab` 대신 실제 `boss_tab.halo_capture`와 `clear_btn`을 사용한다. REGIONS의 새 항목을 제외하지 않는다. 성공 시 해당 영역만 제거하고 옵션·다른 영역을 보존하며 시계/표시를 정리한다. 취소·권한 오류에서는 디스크와 메모리를 유지한다. 헤일로의 실제 오류 안내는 팝업이 아닌 상태 라벨이므로 그 안내도 검증한다.
2. 헤일로 지정 해제 확인은 공통 region_registration의 확인 경로를 호출 시점에 가져오도록 통일했다. 기능/권한/저장 순서는 바꾸지 않는다.
3. 잡담 region은 실제 export인 `win32gui.CreateRectRgnIndirect((0,0,0,0))`로 생성하고 기존 finally에서 DeleteObject한다. 빈/비중첩 region만 노출 근거로 사용하며 정보 없음과 겹침은 여전히 보수적으로 차단한다.
4. 프로세스 진단은 없는 `win32process.QueryFullProcessImageName` 대신 typed `kernel32.QueryFullProcessImageNameW`를 호출한다. HANDLE·DWORD·LPWSTR·길이 포인터·BOOL 서명을 지정하고 기존 limited-information PyHANDLE을 int→HANDLE로 전달해 64비트 절단을 막는다. 조회 뒤 HWND의 PID를 재확인하고 PyHANDLE.Close를 finally에서 실행한다. 전체 경로는 helper 밖으로 반환하거나 로그에 기록하지 않는다.
5. region 증거를 empty/outside/intersects/unavailable로 구분하고 프로세스 진단 실패 단계와 정수 WinError를 추가했다. 클래스 이름 허용 목록, layered/입력 통과 플래그만 보고 허용하는 변경, 화면 캡처 폴링은 추가하지 않았다.

## 테스트

- 기존 unit region 모델을 실제 export 이름으로 수정했다. 프로세스 모델에는 없는 pywin32 함수를 만들지 않으며 OS 조회 helper와 typed ctypes 계약을 분리해 검증한다. 이전 QA probe도 같은 원칙으로 모델을 갱신했다.
- Strict export 모델, 64비트 HANDLE·실패 반환, GDI 임시 핸들 정리, PID 변경, basename만 진단, 성공·취소·저장 실패를 유지한다. 실패를 skip하거나 assertion을 완화하지 않았다.
- 실제 Windows 전용 검사에 no-region/empty/shaped/overlap HWND 4개, 실제 프로세스 이미지 조회 1개를 추가했다. 임시 GDI region과 프로세스 핸들 반복 100회에서 자원 수가 증가하지 않는지 확인하도록 구성했다. 해당 검사는 이번 Linux 세션에서 실행하지 않았다.

| 묶음 | 결과 |
| --- | --- |
| QA API 원본·공통 영역 해제·region/ctypes 계약·Windows 전용 파일 | 54 passed, 6 skipped / 15.23초 |
| 잡담·가림·네트워크/데스크톱 실패·선택기·헤일로 수집/자동찾기 | 165 passed, 1 skipped / 116.40초 |
| 이전 잡담 probe·추가 헤일로 probe·기존 보스/경고/선택기 | 69 passed / 29.68초 |

묶음 사이 일부 사례가 중복이므로 고유 테스트 수로 합산하지 않는다. 첫 묶음의 6 skipped는 기존 Windows 검사 1개와 이번에 추가한 실제 Windows 검사 5개다. 두 번째의 1 skipped도 기존 실제 Windows 가림 검사다. 모두 플랫폼 경계이며 unit에서 실패한 5개를 skip한 것이 아니다.

과거 probe 두 파일이 같은 `probe.py` 이름이어서 첫 동시 호출은 import mismatch로 수집 전에 종료됐다. 파일·assertion을 제외하지 않고 `--import-mode=importlib`로 같은 두 probe를 재실행해 위 69개를 확인했다.

## 한계

- 현재 실행은 Linux Qt offscreen·격리 경계 검증이다. 최신 Windows unit 전체·네이티브·exe 빌드·실제 CEF 창의 region과 투명 픽셀은 미검증이다.
- 실제 CEF가 명시적 region 없이 per-pixel 합성 창이라면 수정 뒤에도 차단될 수 있다. API 오호출 해결을 라이브 잡담 표시 해결로 단정하지 않는다. 새 진단은 이 경우를 구분하기 위한 것이며 같은 로그 재제출이나 다른 프로그램 종료를 먼저 요구하지 않는다.
- Windows Actions·태그·Release는 실행하지 않는다. 후속 독립 QA 뒤 배포할 코드를 모아 Windows 후보 검증을 별도로 수행한다.

```bash
env PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_dialogue_native_api_contract_20261020.py tests/test_region_registration.py tests/test_dialogue_window_region.py tests/windows/test_dialogue_visibility.py -q --tb=short
env PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_creator_dialogue.py tests/test_dialogue_transparent_occlusion.py tests/test_dialogue_network_lifecycle.py tests/test_dialogue_desktop_failure.py tests/test_region_selector_lifecycle.py tests/test_halo_capture.py tests/test_halo_autofind.py -q --tb=short
env PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --import-mode=importlib docs/qa/assets/dialogue_region_fix_20261019/probe.py docs/qa/assets/halo_combined_20261020/probe.py tests/test_pattern_overlay.py tests/test_boss_tab.py tests/test_boss_pattern.py tests/test_region_selector_lifecycle.py -q --tb=short
```
