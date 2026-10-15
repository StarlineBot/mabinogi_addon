# 자동설정 2차 독립 QA

- 검증일: 2026-10-15
- 소스: `08b4143dac915c2d5aed0d6a918bef73366d3acd`
- 기준: `docs/auto-setup-v2-spec.md`의 4단계 흐름, 로그인 사용자용 베타 조건 및 V2-01~V2-17.
- 구현자 자체 통과 결과 대신 고정 소스와 독립 실행으로 확인했다. 커밋 이력/메시지는 조회하지 않았다.
- 제품/테스트/기존 QA 코드 809개 파일의 Git blob 해시가 원격 트리와 일치했다.
- 제품 구현·기존 테스트·기획은 수정하지 않았다. 이 보고서와 `scripts/qa_setup_v2.py`만 추가한다.

## 후속 독립 QA 판정 (2026-10-15)

- 소스: `7688dc1ece1cb2248d5d8a37e22f8b72bd4d115f`.
- **SETUP-V2-QA-01 해결 확인. 검증 범위에서 새 배포 차단 문제 없음. 제한된 베타 릴리즈 가능.**
  원본 `scripts/qa_setup_v2.py`의 blob `2878751958417f8a675dffe1f52fc7bafc6067fb`와
  기존 assertion을 바꾸지 않고 **10 passed, 4 warnings in 7.32s**를 확인했다.
  실제 안내 종료 → 설정 → 기존 준비 화면의 체크 상태도 이제 저장값과 일치한다.
- V2 안내/공용 흐름/투어 구현은 앞서 검증한 상태를 유지하며, 이번 제품 수정의 핵심은
  `SetupPage.refresh()`가 저장된 skipSetup을 신호 없이 다시 읽는 것이다.
  원본 독립 QA는 전체 4단계와 현재 단계 탐색/저장/거절/실패/로그아웃/재진입도 다시 실행했다.
- 소스·테스트·테스트 경계·기존 QA 및 변경된 검증/패키징 파일 827개의 원격 blob 일치를 확인했다.
- 관련 로컬 검사 첫 실행은 **193 passed / 1 failed in 52.07s**였다.
  실패는 QA 가상환경에 새 개발 의존성 PyYAML이 없어서 YAML 검사 import가 중단된 것이었다.
  pyproject/uv.lock에 선언된 **PyYAML 6.0.3**을 설치한 뒤 CI/장치 경계/노트 집합을
  **26 passed in 1.66s**로 재실행했다. 두 집합은 중복이며 합산하지 않는다.
  제품 테스트를 수정/skip하거나 실패 assertion을 약화하지 않았다.
- 새 제품 회귀의 양방향 ON/OFF·refresh 무저장·새 화면 복원 검사도 실행했다.
  원본 종료 후 캡처 재생성 및 반복 종료 재현 스크립트는 원격과 동일하게 보존했다.
- 패키징을 YAML 파서와 shlex로 독립 비교해 기존 PyInstaller 인자 **68개 전부 동일**함을 확인했다.
  main 자동 검증과 태그 릴리즈는 같은 `packaging/build_windows.py`를 호출하며,
  버전 생성 단계는 실제 태그 버전을 앱 version.py와 exe 버전 리소스에 주입한다.
- 태그 v0.4.69의 앱 노트와 현재 v0.4.69 이하 본문을 전체 문자열로 비교해 동일함을 확인했다.
  새 V2 설명과 체크 수정은 미사용 `v0.4.70`으로 분리되어 있다.
- 아래 자동 Windows 성공을 정확한 SHA로 확인했다. 수동 Run workflow를 요청하지 않았다.
  이 결과 갱신은 QA 문서만 바꾸므로 동일 제품 소스의 성공을 재사용한다.
- 실제 배포 exe 실행, 게임/혼합 DPI/장시간 핸들·메모리 계측은 별도 미검증 범위다.
  이번 CI 성공만으로 모든 Windows 환경과 실게임 정확도를 보증하지 않는다.

후속 실행 명령(저장소 루트, 제품/QA 원본 수정 없음):

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_setup_v2.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q tests/test_setup.py tests/test_main_shutdown.py tests/test_lifecycle.py tests/test_memo_lock_persist.py tests/test_release_notes.py tests/test_release_notes_trigger.py tests/test_settings_preserve.py tests/test_settings_sync.py tests/test_config_atomic.py tests/test_config_bundle.py tests/test_test_boundaries.py tests/test_windows_ci.py tests/test_tuarim.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q tests/test_windows_ci.py tests/test_test_boundaries.py tests/test_release_notes.py
```

## 자동 Windows 검증 결과

- 실행: https://github.com/StarlineBot/mabinogi_addon/actions/runs/38710588941
- SHA: `7688dc1ece1cb2248d5d8a37e22f8b72bd4d115f`, `push` / `main` / **success**.
- Isolated regression: **719 passed, 1 skipped, 3 deselected, 3 warnings in 166.33s**.
- Native Windows integration: **3 passed, 720 deselected, 1 warning in 1.44s**.
- Verify exe build: **success**, `mabinogi-addon.exe` **123561999 bytes**.
- Optional exe upload: **skipped**(기본 OFF), 테스트/빌드 실패가 아니다.
- 네이티브 3개는 작은 MSS 데스크톱 캡처, 실제 무음 오디오 객체 생성/해제,
  실제 HWND 생성/파괴를 검사했다. dxcam import 확인은 실제 DXGI 캡처 초기화가 아니며,
  실게임·모든 장치 전환·생성된 exe의 직접 실행은 검증하지 않았다.
- 일반 회귀에서는 장치/네트워크를 명시적 경계로 격리한다. 누수 fixture가 공통 창 정리보다
  먼저 실행되는 의존성을 확인했으므로 공통 cleanup으로 QThread 누수를 숨기는 구조는 아니다.
- 새 파이프라인은 main 푸시에서 자동 실행하고 이전/다른 SHA 성공이나 required step의
  skipped/cancelled를 완료로 받지 않는다. unit/native/build의 실패는 여전히 gate 실패다.
  선택 업로드만 continue-on-error이며 보관 1일·기본 OFF로 quota와 코드 검증을 분리했다.
- 기존 플랫폼 skip 1개와 네이티브 단계 분리 deselected는 실패 검사를 삭제한 결과가 아니다.

## 최초 판정 (08b4143)

**설정 표시 불일치 1건 확인. QA 통과 및 릴리즈 명령은 보류한다.**
현재 검증에서 크래시나 기존 종료 후 워커 재생성의 회귀는 발견하지 못했다.
수정본 재검증 후 시작/안내 생명주기 변경에 대한 Windows 사전 검증이 필요하다.
이번 소스의 Windows 테스트·exe 빌드는 아직 확인하지 못했다.

## Confirmed Bug: SETUP-V2-QA-01

- 심각도: **P2**, 시작 화면 표시 설정과 UI의 불일치. 크래시/설정 파일 손상으로 확인한 문제는 아니다.
- 발생 조건: 로그인 상태의 새 첫 사용 안내에서 '시작할 때 이 화면 다시 보지 않기' 체크
  → 다음으로 4단계 투어 진입 → 투어 종료/건너뛰기 → 설정의 '자동설정 다시 열기'.
- 예상: 기존 사용 준비 화면의 같은 체크박스도 저장된 `general.skipSetup=true`를 표시한다.
- 실제: 파일에는 true가 저장됐지만 기존 화면은 체크 해제(false) 상태다.
- 사용자 영향: 표시만 보면 시작 화면이 다시 나타날 것으로 예상하지만 재실행 시 건너뛴다.
  다시 표시하려 해도 이미 꺼져 보이는 체크박스를 먼저 켰다가 다시 꺼야 하므로 설정을 오인하게 된다.
- 원인: 새 `SetupGuide`는 공용 `skipSetup`에 저장하고 refresh에서 다시 읽는다.
  반면 `SetupPage`의 같은 체크박스는 생성 시 한 번만 읽는다. `_open_setup()`이 refresh를 호출해도
  그 메서드는 skip 체크 상태를 갱신하지 않는다. 두 화면이 같은 설정을 쓰면서 UI 동기화가 빠졌다.
- 재현 결과: 실제 MainWindow의 show/start, 버튼 클릭, 투어 건너뛰기와 설정 버튼으로 재현.
  `setup_page.skip.isChecked() == config.load_general_flag("skipSetup")`가 **False == True**로 실패했다.
  네이티브 오디오와 게임 캡처 없이도 발생하며, 재현 코드에서 이 경로의 저장/위젯 동작은 대체하지 않았다.
- 위치: `src/mabinogi_addon/ui/setup_guide.py:112`, `:225`,
  `src/mabinogi_addon/ui/setup_page.py:141`, `:153`,
  `src/mabinogi_addon/ui/main_window.py:414`.
- 재검증 조건: 어느 화면에서 변경해도 다른 화면에 실제 저장값이 반영되고,
  화면을 열거나 갱신하는 것만으로 설정을 재저장하거나 초기화하지 않아야 한다.
  양방향 ON/OFF 및 재실행을 확인한다. 별도의 중복 사용자 의향 설정으로 분리하지 않는다.

저장소 루트에서 원래 실패를 재현한다. 최초 08b4143에서는 실패했고, 후속 수정본은 통과했다.

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_setup_v2.py::test_skip_checkbox_is_synchronized_when_returning_to_existing_setup
```

## 실행 결과

Linux/Python 3.12/PySide6 offscreen이다. 기존 오디오 생성 경계 대체를 사용했고,
실사용 설정 대신 한글/공백 경로를 포함한 임시 실제 JSON과 진단 저장소를 사용했다.

| 범위 | 독립 실행 결과 |
|---|---|
| 제품 관련 회귀, 기존 종료 재현·반복 검사·기존 설정 QA | **146 passed, 6 warnings in 31.60s** |
| 새 `scripts/qa_setup_v2.py` 전체 | **1 failed, 9 passed, 1 warning in 4.06s** |

기존 V1의 `qa_setup_tour.py`와 `qa_setup_first_user.py` 일부는
'최초 실행은 바로 옛 하이라이트', '투어 다시 보기로 기존 준비 화면을 연다'는 예전 계약을 검사한다.
V2 명세가 로그인 사용자용 첫 안내와 별도 앱 둘러보기로 바꾼 동작이므로 원본을 고쳐 통과시키지 않았다.
그 스크립트 전체를 V2 통과 근거로 세지 않고, 새 독립 코드로 해당 동선을 다시 검증했다.
기존 오디오 timeout이 알려진 하위 프로세스 시험도 새 전체 Windows 통과인 것처럼 재사용하지 않았다.

실제로 확인한 정상 경로:

- 실제 첫 표시 → 로그인 사용자 안내 → 게임 미등록 상태에서도 나중에 설정 → 2/3단계 → 실제 4단계 TourOverlay → 앱.
- 미선택 기능을 건너뛰어도 기능 ON이나 좌표 등록으로 바뀌지 않음. 메모/커스텀은 단계 선택 목록에 없음.
- 미로그인 자동/명시 진입·재개·탐색 호출은 무동작이며 설정/캡처를 변경하지 않음.
- 단계별 선택 순서와 현재 단계 범위로만 탐색. 다른 단계는 건드리지 않고, 승인한 영역은 실제 탭 저장 경로로 저장.
- 다시 탐색할 때 기존 승인 영역과 공유 보스 영역을 재캡처/덮어쓰지 않음.
- 거절/미발견/저장 실패/전체 캡처 실패를 등록 성공으로 표시하지 않고 다음 단계로 진행 가능.
- 전체 캡처 실패 뒤 아직 시도하지 않은 다음 기능을 거짓 실패로 채우지 않음.
- 실제 검출 워커 실행 중 logout 이벤트를 발생시키면 취소되고, 늦은 결과를 승인/저장하지 않음.
- 뒤로 이동·명시적 다시 보기·창 종료 후 새 MainWindow 진입은 1단계에서 시작하고 승인된 영역을 보존.
- 790×800 실제 메인 창의 단계별 다음/나중에 설정 버튼과 가로 잘림 여부를 확인.
  1~4단계를 PNG로 렌더하고 2단계 및 투어의 실제 표시도 육안 확인했다.

OS 캡처·자동찾기 검출 결과·영역 승인 응답·외부 네트워크는 시나리오 목적에 맞게 대체했다.
SetupFlow 워커/스코프/승인 후 실제 설정 저장, 위젯 전환, 실제 투어는 실행했다.
따라서 이것은 검출 알고리즘의 새로운 실게임 정확도 검증이 아니다.
실제 승인 UI와 게임 창 캡처, Windows DPI/전체화면/포커스, 절전/로그아웃 복귀 및
장시간 CPU·메모리·핸들 계측은 별도 미검증 범위다.

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary tests/test_setup.py tests/test_main_shutdown.py scripts/qa_setup_closed_retry.py scripts/qa_shutdown_followup.py scripts/qa_setup_independent.py tests/test_memo_lock_persist.py tests/test_release_notes_trigger.py tests/test_release_notes.py tests/test_settings_preserve.py tests/test_settings_sync.py tests/test_config_atomic.py tests/test_config_bundle.py tests/test_config_buffs.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_setup_v2.py
```

합성/임시 입력의 렌더는 `/tmp/setup-v2-qa/stage-1.png`~`stage-4.png`,
설정 불일치는 `skip-in-guide.png`, `skip-in-existing-setup.png`에 남겼다.
사용자 원본 화면·설정·진단 ZIP은 업로드하지 않는다.

## 최초 검증 당시 Windows 및 배포 준비

- 조회한 새 V2 소스의 Actions 실행은 없다. `release.yml`은 기존 blob
  `92a1fc9516c9ee397898240316465eed2fcb7abd` 그대로이고 main 푸시 자동 검증은 이번 변경에 포함되지 않았다.
- 성공한 v0.4.69 실행 `38705813223`은 **이전 제품 소스 dec6f28**이다.
  이를 새 V2 소스의 Windows 통과로 간주하지 않는다. 이미 발견한 설정 결함의 수정 후 검증을 우선한다.
- `v0.4.69` 태그는 이미 `dec6f28cecd00ac528bdde1d7cd88a89ab936b44`로 존재한다.
  새 V2 설명이 현재 앱 노트의 같은 v0.4.69 항목에 추가되어 있으므로 다음 릴리즈 준비에서는
  V2 설명을 새로운 미사용 버전으로 분리하고 이미 배포한 v0.4.69 본문은 보존해야 한다.
  이번 QA에서는 제품/릴리즈 노트를 고치거나 태그를 이동하지 않았다.
- 기존 공개 노트 원시 커밋 제목 노출 이슈는 별개로 남아 있으며 이번 V2 변경으로 해결된 것은 아니다.
- 새 Highly Likely Bug / Potential Risk는 추가로 확정하지 않았다. 환경 미검증을 버그로 부풀리지 않는다.
