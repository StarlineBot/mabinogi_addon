# 사용 준비: 첫 사용자 기능 선택 독립 QA

- 검증일: 2026-10-15
- 제품 소스: `53d473c7550cc03f2cc730ef3ad4f6b6efec09e2`
- 조사 중 main은 `f141d37d7189a263d842401acc62368a549b6cd8`로 갱신되었다.
  차이는 검토용 `docs/auto-setup-v2-spec.md`뿐이며 제품/테스트/워크플로 소스는 동일하다.
  2차 기획 초안을 현재 앱에 이미 적용된 요구사항으로 판정하지 않았다.
- 기준: `docs/app-usability-spec.md` 1.2.1, U-13~U-16 및 사용자의 베타 시작 화면 정책.
- 커밋 이력/메시지는 조회하지 않았다. 원격 트리와 고정 SHA의 소스를 읽었다.
- 소스·테스트·기존 QA 스크립트 804개 파일의 Git blob 해시가 원격과 일치함을 확인했다.
- 제품 구현과 기존 제품 테스트는 수정하지 않았다. 이 보고서와 독립 QA 코드만 공유한다.

## 최신 후속 QA 판정 (2026-10-15)

- 검증 제품 소스: `f02cb238a027500c9b54da5aaf4cd246b71b3257`.
- `FIRST-USER-QA-01`의 원본 재현 코드와 기대값을 바꾸지 않고 관련 회귀와 함께 실행했다.
  **143 passed, 6 warnings in 26.15s**. 원래 실패했던 종료 후 캡처 재생성은 재현되지 않았다.
- 소스·테스트·기존 QA 코드 807개 파일의 Git blob 해시가 해당 원격 트리와 일치했다.
- 새 독립 `scripts/qa_shutdown_followup.py`: **4 passed in 9.78s**.
  시작 전/후 설정 가져오기의 실제 콜백을 실행한 뒤 start, 버프/디버프 시작, 상태 재시도,
  최초 표시 콜백을 반복 호출하고 Qt 이벤트를 처리해도 새 캡처나 설정 쓰기가 없었다.
- 시작 → 중복 시작 → 완전 종료 → 중복 종료를 20회 반복했다.
  중복 시작 시 QTimer 자식 목록과 상태 타이머 객체가 같았고 파티 시작은 1회였다.
  종료 뒤 영역을 제공하고 뒤늦은 콜백을 실행해도 캡처 생성이 없었다.
  이는 제한된 반복 검증이며 장시간 메모리/Windows 핸들 누수 측정을 뜻하지 않는다.
- 트레이 숨김에서는 타이머를 유지했고, 이후 등록한 버프/디버프 영역에 대해 실제
  `BuffController`의 `_TrackWorker` 두 개가 실행됨을 확인했다. 완전 종료 후에는 재생성하지 않았다.
  이 경우에도 OS 캡처만 배열 소스로 대체했으며 제품 워커/타이머/종료 경로는 실제 코드를 사용했다.
- Linux 네이티브 오디오 생성은 기존 QA 경계로 대체했다. 이전 Linux 오디오 제한을
  Windows 통과의 근거로 사용하지 않으며 기존 누수 검사나 제품 테스트는 변경하지 않았다.
- **독립 로컬 재현 기준으로 기존 문제 해결 확인. 수정본 Windows 사전 검증 대기.**
  최신 조회까지 수정본의 새 Actions 실행은 없었다. 이전 실패 run을 재실행하는 대신
  `release`의 `Run workflow` → `main`으로 수정본의 전체 테스트와 exe 빌드를 확인해야 한다.
  종료/타이머 변경과 미해결 Windows 실패가 있어, 이 결과가 확인되기 전 릴리즈 명령은 보류한다.
- 최신 원격 태그는 `v0.4.68`, 앱 내부 다음 노트는 `v0.4.69`다. 태그는 생성/푸시하지 않았다.
- 이번 후속 QA에서 새 Confirmed Bug / Highly Likely Bug / Potential Risk는 찾지 못했다.
  아래 최초 실패와 개발자의 자체 검증 기록은 이력으로 보존하며, 후속 독립 결과와 구분한다.

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_setup_closed_retry.py tests/test_main_shutdown.py scripts/qa_setup_first_user.py scripts/qa_setup_tour.py scripts/qa_setup_independent.py tests/test_setup.py tests/test_memo_lock_persist.py tests/test_settings_preserve.py tests/test_settings_sync.py tests/test_release_notes_trigger.py tests/test_release_notes.py tests/test_config_atomic.py tests/test_config_bundle.py tests/test_config_buffs.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_shutdown_followup.py
```

## 최초 판정 (53d473c)

**릴리즈 보류.** 첫 사용자 UX의 관련 검사와 독립 시나리오는 통과했지만,
Windows 테스트 게이트에서 종료 후 워커 누수가 확인되어 exe 빌드에 도달하지 못했다.
아래 `FIRST-USER-QA-01`의 종료 후 캡처 재생성 경로를 Linux에서도 독립 재현했다.
테스트 격리/생명주기 문제와 일반 배포본의 종료 크래시는 구분한다.
현재 결과로 Windows 통과나 릴리즈 가능을 안내하지 않는다.

## Confirmed Bug: FIRST-USER-QA-01

- 심각도: P1 배포 검증 차단. Windows 테스트 게이트 실패이며, 일반 배포본의 크래시 확정은 아니다.
- 발생 조건: `MainWindow.start()` → 완전 종료 경로의 `close()` → 객체와 Qt 이벤트 루프가 남음
  → 이후 설정/테스트에서 버프 영역 제공 → 기존 700ms 상태 타이머 실행.
- 사용자 영향: 현재 릴리즈 CI의 테스트 단계가 실패해 exe 빌드/배포 불가.
  개발/테스트처럼 종료 후 이벤트 루프가 계속되는 환경에서는 닫은 창이 불필요한 캡처·워커를 다시 생성한다.
- 원인: `start()`가 생성한 `_status_timer`를 `closeEvent()`에서 정지하지 않는다.
  `_maybe_retry_live_capture()`와 `_start_buff_tracking()`에도 종료 상태를 거르는 검사가 없다.
  따라서 닫힌 창이 나중의 설정을 읽어 `BuffController`와 `_TrackWorker`를 생성할 수 있다.
- Windows 증거: 첫 teardown 오류는 `test_selection_copy_and_beta_guidance_fit_current_window[False]`.
  이 테스트는 `SetupPage`만 생성하므로 새 창 자체가 캡처 worker를 만드는 검사는 아니다.
  이후 종료하지 않은 `_TrackWorker` 하나 때문에 누수 검사가 170회 연쇄 오류를 냈다.
  최초 오류 테스트명이 곧 워커 생성 위치라고 단정하지 않는다.
- 독립 재현: `scripts/qa_setup_closed_retry.py`. 실제 창의 `start()`/`closeEvent()`/상태 타이머와
  실제 `BuffController`를 사용한다. OS 캡처만 배열을 반환하는 소스로 대체한다.
  닫기 직후 컨트롤러와 캡처 생성이 없음을 확인하고, 영역을 저장한 뒤 950ms 이벤트를 처리한다.
  이미 종료된 창에서 `create_live_source(Region(x=10,y=20,w=80,h=40))`가 호출되어
  캡처 생성 횟수 1, 실제 `_TrackWorker.isRunning() == True`를 확인했다.
  `closed window's status timer restarted capture`로 **1 failed, 1.56s**를 재확인했다.
  재현 뒤에는 생성된 컨트롤러와 타이머를 명시적으로 정리한다.
- 관련 위치: `src/mabinogi_addon/ui/main_window.py:1055`, `:601`, `:1130`, `:1620`.
  기존 `tests/test_memo_lock_persist.py:64`~`:75`도 start/close 후 객체를 즉시 삭제하지 않는 경로다.
- 범위 구분: v0.4.68 소스와 비교해 start/retry/close 구현은 동일하다. 새 기능 초기화가
  일반 사용자 설정을 망가뜨린다고 판단한 것이 아니라, 새 검사에서 기존 생명주기 취약점이 드러난 것이다.
  일반 실행에서는 pytest가 없으면 `closeEvent()` 끝의 `os._exit(0)`으로 프로세스를 끝낸다.
  그러므로 이 재현만으로 일반 종료 후 프로세스가 계속 남거나 게임 캡처가 재시작한다고 주장하지 않는다.
- 재검증 조건: 종료 상태에서 타이머/재시도/뒤늦은 이벤트가 새 캡처를 만들지 않아야 한다.
  기존 테스트의 종료·객체 정리도 점검하되 누수 assertion 삭제, skip 또는 순서 의존 우회로 통과시키지 않는다.
  독립 재현과 관련 회귀 후 수정본의 Windows 전체 테스트·exe 빌드를 재확인해야 한다.

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_setup_closed_retry.py
```

최초 `53d473c`에서는 위 명령이 실패했다. 후속 수정본은 위 최신 판정처럼 통과했다.
제품 구현은 QA에서 수정하지 않았다.

## 독립 실행

Linux/Python 3.12/PySide6 offscreen에서 실행했다. 사용자 설정 대신 임시 실제 JSON을 사용했다.
네이티브 오디오 생성만 `scripts/qa_setup_audio_boundary.py`로 대체했다.
네트워크 파티 폴링과 업데이트 확인은 독립 첫 실행 시나리오에서 대체했고,
`MainWindow` 생성, `start()`, 기능 체크/저장, 종료와 재생성은 실제 코드를 실행했다.

| 범위 | 결과 |
|---|---|
| 관련 기존 회귀와 이전 독립 QA | 118 passed, 6 warnings, 16.30s |
| 이번 독립 `scripts/qa_setup_first_user.py` | 20 passed, 8.39s |
| 관련 검사와 이번 독립 시나리오를 함께 실행 | 138 passed, 6 warnings, 22.16s |
| 메모 잠금·생명주기·자동실행·미러·단축바 추가 회귀 | 44 passed / 1 Linux 오디오 하위 프로세스 timeout, 75.80s |

추가 회귀의 실패를 숨기거나 테스트를 skip하지 않았다.
`tests/test_lifecycle.py::test_no_native_abort[shutdown_blocked]`의 하위 프로세스에는
부모 pytest의 오디오 대체가 전파되지 않아 PulseAudio `Operation not permitted` 뒤 60초 timeout이 났다.
같은 원래 종료 시나리오에 오디오 생성만 명시적으로 대체한 별도 프로세스는 종료 코드 0으로 통과했다.
이 검증은 위 20개에 포함된다. 종료 분기를 바꾸는 pytest import는 자식에 넣지 않았다.
따라서 Linux 원본 오디오 경로를 통과로 표시하지 않으며, 이 실패만으로 Windows 회귀로 단정하지 않는다.

독립 확인 항목:

- 설정/백업이 없는 첫 실행: 기능 8개 전체 OFF, 추적 컨트롤러 없음, 버프·디버프·메모 창 미표시.
- 실제 `start()` 후 표시: 사용 준비 화면 위 투어가 끝까지 진행되고 기능을 선택할 수 있음.
- 기능 8개 각각 선택 → 개별 탭 OFF → 다시 선택 → 종료/재생성: 선택한 기능만 유지됨.
- 기존 파일의 빈 내용, 빈 JSON, 손상 JSON, enabled 누락 및 `.bak`만 있는 경우: 신규 초기화로 덮어쓰지 않음.
- 기존 사용자의 혼합 ON/OFF, 메모 잠금, 프리셋, 알 수 없는 구버전 필드: 창 생성 전후 설정 바이트 동일.
- 아무 기능도 선택하지 않고 자동설정: 로그인 검사/캡처/검출/진단 실행/설정 쓰기 없이 선택 안내만 표시.
- Discord 로그인 버튼 ↔ 사용 준비 50회 왕복: 계정 버튼이 뷰포트에 보이고 인증 thread 및 설정 변경 없음.
- 실제 790×800 메인 창: 4개 행 전체와 다음 행 일부 표시, 마지막 행 스크롤 접근, 가로 잘림 없음, 하단 다시 보지 않기 접근 가능.
- 미로그인 체력바·단축바 제한 및 로그인 후 활성화, 기존 베타 시작 화면/명시적 opt-out 유지.

화면은 `/tmp/setup-first-user-qa/actual-main.png`로 렌더해 육안 확인했다. 사용자 데이터나 원본 캡처는 업로드하지 않는다.

## 실행 명령

저장소 루트에서 실행한다.

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_setup_first_user.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src uv run pytest -q -p scripts.qa_setup_audio_boundary tests/test_setup.py scripts/qa_setup_tour.py scripts/qa_setup_independent.py tests/test_settings_preserve.py tests/test_settings_sync.py tests/test_release_notes_trigger.py tests/test_release_notes.py tests/test_config_atomic.py tests/test_config_bundle.py tests/test_config_buffs.py
```

## 최초 Windows 사전 검증 (53d473c)

- 실행: https://github.com/StarlineBot/mabinogi_addon/actions/runs/38699991207
- 고정 소스: `53d473c7550cc03f2cc730ef3ad4f6b6efec09e2` (`workflow_dispatch`).
- 결과: 테스트 단계 **실패**, `669 passed, 1 skipped, 4 warnings, 170 errors in 175.04s`.
- 오류는 실행 중인 `_TrackWorker`의 teardown 누수 검사다. 아티팩트 용량 문제가 아니다.
- exe 빌드와 아티팩트 업로드는 모두 skipped. 이전 v0.4.68 성공으로 대체하지 않는다.
- `1 skipped`는 기존 Windows용 DWM fallback 분기 검사다. 실패를 통과시키려고 추가한 skip이 아니다.
- 릴리즈 명령은 제공하지 않는다. 버그 수정과 후속 독립 QA 및 Windows 사전 검증이 필요하다.

## 제한 및 기존 이슈

- 실제 Windows exe 실행, UAC/NTFS ACL/디스크 부족, 모니터별 DPI, 게임 전환/캡처,
  로그아웃/절전 복귀, 실오디오, 장시간 CPU·메모리·핸들 계측은 이 Linux 실행으로 검증하지 못했다.
- 이 변경은 검출기·판독기·게임 프로세스 감지·워커 구현을 바꾸지 않았다.
  기존 등록 상태 보존과 자동설정 승인/취소 회귀는 실행했지만 전체 실게임 정확도를 재보증하지 않는다.
- 앱 내부 노트는 `v0.4.69`의 한국어 사용자 설명이다. 과거 v0.4.68 이하 본문은 원격 기준으로 보존한다.
- 기존 `NOTES-QA-01`: `.github/workflows/release.yml:151`의 공개 노트 생성은 여전히 원시 커밋 제목을 사용한다.
  영어·내부 작업 제목이 공개 노트에 섞일 가능성은 이번 수정으로 해결되지 않았다. 앱 내부 수동 노트와 별개다.

## 개발 후속: FIRST-USER-QA-01 수정 (2026-10-15)

- 원본 독립 재현은 수정 전에 **1 failed in 1.55s**, 수정 후 **1 passed in 1.54s**였다.
  `scripts/qa_setup_closed_retry.py`의 assertion과 정리 코드는 변경하지 않았다.
- 완전 종료 분기에 진입하면 종료 상태를 먼저 설정하고 상태 타이머를 정지한다.
  캡처 재시도, 버프/디버프 추적 시작, 상태 갱신, 뒤늦은 최초 표시 콜백과 start()는
  종료 또는 설정 가져오기 후 재시작 대기 상태에서 새 작업을 시작하지 않는다.
- start()는 중복 호출해도 폴링/상태 타이머를 추가하지 않는다. 트레이 숨김은 완전 종료와
  구별해 기존 상태 타이머와 캡처 재시도를 유지한다.
- `tests/test_main_shutdown.py`에 늦은 직접 콜백 및 900ms 이벤트 처리, 중복 start(),
  트레이 숨김의 타이머·캡처 재시도 유지 시험 3건을 추가했다.
- 관련 실행: `tests/test_main_shutdown.py scripts/qa_setup_closed_retry.py tests/test_memo_lock_persist.py`
  (offscreen 및 기존 오디오 경계 대체): **5 passed in 3.77s**.
- 화면 검토 중인 자동설정 V2 작업은 이 배포 차단 수정과 분리한다. 이 수정의 검증/푸시는
  기존 main 제품 구조를 기준으로 하며, V2 구현/문서/테스트를 몰래 포함하지 않는다.
- 검증할 index를 `/tmp/qa-shutdown-verification/`에 내보내고 해당 `src`를 PYTHONPATH로
  지정해 원래 전체 제품 테스트를 실행했다. 메인 파일 blob은 실제 staged 파일과 같은
  `abef8b4a8ac79ffc098700005a500520cba721b9`임을 확인했다.
  분리용 스냅샷의 초기 구성 오류로 수집이 중단된 시도는 통과로 세지 않으며,
  구성을 바로잡은 뒤 전체 명령을 다시 실행했다.
- 최종 전체 제품 회귀: **673 passed, 7 warnings in 140.72s**.
  생명주기 테스트의 로컬 IPC/콜백 소켓을 허용한 Linux 실행이며 기존 오디오 경계 대체를
  사용했다. QThread 누수 검사나 assertion을 제거하지 않았다.
- 같은 분리 소스에서 원본 독립 스크립트 `qa_setup_closed_retry.py`, `qa_setup_first_user.py`,
  `qa_setup_tour.py`, `qa_setup_independent.py`를 함께 실행해
  **35 passed, 1 warning in 13.85s**를 확인했다. 독립 QA 스크립트의 기존 기대값은 보존했다.
  경고는 기존 mss/Qt API 사용 중단 안내다.
- Linux 검증과 수정 자체가 후속 독립 QA 또는 수정본 Windows 테스트·exe 빌드 성공을
  의미하지 않는다. 이 환경에서는 수정본의 Windows 워크플로를 실행하지 않았으며,
  실패했던 Windows 전체 테스트와 exe 빌드는 후속 재검증이 필요하다.
  릴리즈 명령/태그는 실행하지 않는다.
