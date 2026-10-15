# 사용 준비·일괄 자동설정 독립 QA

- 검증일: 2026-10-15.
- 기준 소스: `92215ef5166c9cd0532091499921af6de926f07e`.
- 기준 요구사항: `docs/app-usability-spec.md`, 기존 기능/설정 보존 및 독립 QA 지침.
- 환경: Linux, Python 3.12, PySide6 offscreen. 커밋 이력/메시지는 조회하지 않았다.
- 최초 결론: **동작 오류 2건과 문서 기준 요구사항 불일치 1건을 실제 실행으로 확인했다.
  수정과 후속 QA 전에는 새 릴리즈를 권고하지 않는다.** 앱 구현과 제품 테스트는 수정하지 않았다.
- 개발 세션의 후속 수정 및 최신 사용자 지시와의 대조는 문서 마지막에 별도로 기록한다.
  아래 최초 재현 결과는 보존하며, 개발 검증을 후속 독립 QA 완료로 보지 않는다.

## 범위 및 소스 일치

이전 QA 완료 소스 `5a3a0b7`과 현재 tree의 파일을 비교했다. 변경은 24개 파일이며
사용 준비 상태/화면/순차 워커, 메인 연결, 기능 전체 사용 체크, 캡처 복원 조건,
기존 탭 문구, 테스트 및 문서/앱 노트다. 투아림 판독기 자체의 추가 수정은 없다.
로컬 실행용 미러를 원격과 동기화하고 소스/제품 테스트 및 사용한 자료·자산 249개
파일의 git blob 해시가 원격 tree와 모두 일치함을 확인했다.

제공된 렌더 스크립트로 준비/승인 후 화면과 트래커·편의기능 11개 탭의 PNG를 생성했다.
준비 화면, 버프와 커스텀 탭을 직접 확인했다. Linux 기본 배율의 해당 화면에서
새 체크/핵심 버튼의 겹침은 발견하지 못했다. 모든 PNG와 Windows DPI를 검사했다는 뜻은 아니다.

## Confirmed Bug: SETUP-QA-01 / P1

### 커스텀 오버레이를 꺼도 새로 불러온 창이 계속 표시됨

- 조건: `customOverlay.enabled=false`에서 시작 자동 프리셋, 직접 영역 추가 또는
  프리셋 불러오기를 수행한다. 각 동작은 지원되는 정상 조작이다.
- 영향: 기능 사용 체크와 실제 창 표시가 다르다. 잠금 해제 창은 게임 화면을 가리거나
  입력을 받을 수 있다. 실제 Windows 게임 입력 간섭 정도는 별도 실게임 검증 대상이다.
- 원인: 탭 생성 때 `set_paused(True)`가 `_shown=False`로 만든 뒤 프리셋을 로드한다.
  `MirrorManager._make_overlay()`는 새 창을 무조건 show하지만 `_shown`은 여전히 False다.
  `_tick()`의 일시정지 분기는 `_shown=True`일 때만 숨기므로 이후 틱에도 창이 남는다.
- 재현: 커스텀 기능 OFF와 잠금 해제 프리셋 1개를 저장한 뒤 탭을 생성한다.
  직접 추가/수동 로드도 각각 별도로 실행한다. 실제 위젯에서 사용 체크 false,
  매니저 paused true를 확인하고 5회 `_tick()`/Qt 이벤트 처리 후에도 창이 visible이다.
- 결과: 독립 테스트 3개가 모두 기대 조건인 "꺼진 기능의 창은 숨김"에서 실패했다.
  반면 정상 ON에서 만든 창을 OFF로 전환하는 대조 시험은 통과했다.
- 위치: `src/mabinogi_addon/ui/custom_overlay_tab.py:150`, `:230`, `:246`, `:298`, `:392`;
  `src/mabinogi_addon/ui/mirror_manager.py:162`, `:226`, `:234`.
- 이 공유 매니저의 숨김 상태 제약은 이전 코드에도 존재한다. 새 기능 OFF 체크와
  시작 프리셋 경로가 이를 그대로 사용해 발생하는 현재 통합 결함으로 보고한다.

## Confirmed Bug: SETUP-QA-02 / P2

### 자동설정 캡처 중 트레이로 닫은 메인 창이 다시 표시됨

- 조건: 자동설정의 화면 캡처에서 Qt 이벤트를 처리하는 동안 X/close 이벤트가 도착하고,
  설정된 닫기 동작이 완전 종료가 아니라 트레이 최소화다.
- 영향: 사용자가 숨긴 창이 캡처 복원에서 다시 나타난다. 게임 화면을 다시 가릴 수 있다.
  Windows 포커스 탈취 여부는 미검증이며 Qt visible 상태가 잘못 복원된 사실과 구분한다.
- 원인: `closeEvent()`가 flow.cancel()과 hide()를 실행하지만 트레이 최소화이므로
  flow.closed는 False다. SetupFlow의 복원 허용 조건은 `not self.closed`만 검사한다.
  캡처 helper의 finally가 이전 창 목록에 show()/raise_()를 호출해 사용자 숨김을 되돌린다.
- 재현: 실제 MainWindow와 SetupFlow.run()을 사용하고, 캡처의 OS 경계만 배열로 대체한다.
  실제 트레이가 없는 환경이므로 트레이 닫기 정책을 True로 주입하고 Qt singleShot으로
  close 이벤트를 캡처 중 전달한다. sleep은 제거하지만 실제 processEvents 순서를 실행한다.
  진단 저장소는 임시 경로다. 종료 후 cancelled=True, closed=False인데 창이 visible=True다.
- 결과: "트레이로 닫은 창은 숨김 유지" assertion이 실패했다. 설정 적용이나 늦은 결과
  저장을 확인한 버그가 아니라 창 복원 상태 오류다.
- 위치: `src/mabinogi_addon/ui/setup_flow.py:165`,
  `src/mabinogi_addon/ui/screen_grab.py:164`, `src/mabinogi_addon/ui/main_window.py:1600`.

## Confirmed Bug: SETUP-QA-03 / P2 (문서 기준 요구사항 불일치)

### 등록을 마친 사용자도 준비 화면으로 시작함

- 기준: 기획서 1.1/1.2와 U-02는 선택한 기능의 필수 설정이 모두 등록됐으면 기존
  트래커 > 버프로 시작하도록 한다. 앱 v0.4.67 노트와 개발 기록도 같은 동작을 설명한다.
- 조건: 게임창과 선택한 투아림 영역을 모두 저장하고 다른 기능은 OFF,
  `skipSetup=false`인 기존 사용자 설정을 사용한다. `state.pending()==[]`다.
- 영향: 매번 불필요한 준비 화면을 거쳐야 하며 등록 완료 후 시작 동선 보존 요구와 다르다.
- 원인: `needs_start_screen()`이 pending을 보지 않고 skipSetup이 정확히 True인지로만
  판단한다. 제품 테스트도 등록 완료와 무관한 베타 기본 표시를 기대하도록 작성돼 있다.
- 재현/결과: 실제 MainWindow를 생성하면 현재 스택은 준비 화면이며 기존 탭이 아니다.
  U-02를 assertion으로 둔 별도 시험이 실패했다. 실제 표시 결정은 생성자에서 수행한다.
- 위치: `src/mabinogi_addon/setup_state.py:126`,
  `src/mabinogi_addon/ui/main_window.py:389`, `tests/test_setup.py:66`,
  `docs/app-usability-spec.md:367`, `src/mabinogi_addon/assets/release_notes.md:7`.
- 코드의 "베타 중 기본 표시" 주석만으로 요구사항이 변경됐다고 간주하지 않았다.
  별도 합의된 정책이 있다면 기획/Acceptance Criteria/앱 노트/개발 기록을 그 정책과
  일치시켜야 한다. 임의로 기존 테스트를 약화하거나 구현을 수정하지 않았다.

## 실제 실행 결과

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest -q -p scripts.qa_setup_audio_boundary tests/test_setup.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest -q -p scripts.qa_setup_audio_boundary scripts/qa_setup_independent.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest -q -p scripts.qa_setup_audio_boundary tests/test_tuarim_native_autofind.py tests/test_tuarim.py tests/test_autofind_mvp.py tests/test_autofind_diagnostics.py tests/test_skillbar_mirror.py scripts/qa_tuarim_repeat_alert.py scripts/qa_debuff_flicker.py scripts/qa_autofind_missing_assets.py scripts/qa_autofind_mvp.py scripts/qa_tuarim_autofind_crop.py scripts/qa_tuarim_native_followup.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest -q -p scripts.qa_setup_audio_boundary tests/test_mirror.py tests/test_settings_sync.py tests/test_settings_preserve.py tests/test_config_atomic.py tests/test_config_bundle.py tests/test_memo_lock_persist.py
```

- 새 개발 테스트: **45 passed in 7.32s**. 개발 기록의 39개를 이번 실행 수로 대신 사용하지 않았다.
- 기존 투아림·자동찾기·단축바·디버프 독립 회귀: **295 passed in 48.95s**.
- 미러·설정 보존·원자 저장·백업·메모 잠금: **29 passed in 2.05s**.
- 새 독립 재현/대조: **5 failed, 1 passed in 1.14s**. 실패 5개는 위 세 항목에 대응한다.
- 서로 다른 집합이며 제품/기존 QA 369개 통과와 신규 대조 1개를 합하면
  **370 passed / 5 failed**다. 전체 제품 테스트 통과나 배포 승인으로 표시하지 않는다.
- 최초 독립 하네스에서 로그인 모형에 name을 누락한 KeyError 2개를 수정했다.
  이는 하네스 오류이며 제품 finding에 포함하지 않았다. 최종 실패는 위 제품/요구사항 경로다.

### 오디오 경계와 환경 제약

오디오 분리 전 실행은 메인 창 생성 중 이 Linux 환경의 Qt 오디오 초기화에서 대기해
해당 QA 프로세스만 종료했다. `scripts/qa_setup_audio_boundary.py`는 SoundNotifier의
생성자에서 native QAudioOutput/QMediaPlayer 생성만 분리하며 실제 QObject를 유지한다.
제품 소스/테스트의 assertion은 바꾸지 않고 같은 테스트를 재실행했다.
따라서 음성·장치 전환·오디오 실패 복구는 검증하지 않았다. 이 환경 제약을 Windows 앱
크래시나 무한 대기 확정 버그로 분류하지 않는다.

## 확인한 정상 경로와 미검증

- 승인/거절, 체크 순서, 이미 등록된 영역 건너뛰기, 한글 경로의 실제 JSON 저장,
  저장 실패/미발견/캡처 실패 분리, 게임창 필수·데스크톱 폴백 차단,
  검출만 worker에서 실행, 종료/취소/로그아웃 후 적용 차단, 공유 보스바 의존성,
  실제 확인 창/버프 위 경계, 실행별 원본 PNG 진단 ZIP 재생과 기능 체크 동기화를 재실행했다.
- 이전 투아림 55%/100% 오독·잘못된 재무장과 디버프 재검출 깜빡임 회귀는 계속 통과했다.
  밝기 변형의 기존 고값 ±1 오독, 단축바 고정 격자와 혼합 DPI 한계가 해결됐다는 뜻은 아니다.
- 실제 Windows 게임/창 선택, 전체화면·Alt+Tab·UAC·혼합 DPI, 장치/절전/Explorer 재시작,
  장시간 CPU/메모리/GDI/핸들 증가와 실제 포커스·입력은 미검증이다.
  QThread 누수 검사는 제품 tests/conftest의 assertion을 유지했다. 장시간 누수가 없다는 판정은 아니다.
- 마지막 확인된 Windows 태그 CI는 v0.4.66, 소스 `5a3a0b7`, run `38665882059` 성공이다.
  현재 `92215ef`의 Windows 통과로 대신하지 않는다.
- 이번에는 시작 화면·캡처 복원·새 검출 worker 경로가 변경됐으므로 버그 수정 후
  관련 독립 QA와 main의 Windows 사전 테스트/빌드 검증이 필요하다.
  실패가 이미 확인된 현재 소스로 수동 CI를 반복 요청하거나 릴리즈 명령을 제공하지 않는다.
- 기존 공개 노트 혼입 workflow 문제는 이번 변경으로 해결되지 않았다.

## 전달

앱 구현/기존 테스트/사용자 설정/원본 진단 ZIP은 변경·업로드하지 않는다.
이 보고서와 두 독립 QA 스크립트만 main에 커밋·푸시하고 원격 내용을 확인한다.
최신 개발 세션은 위 실패 재현을 먼저 확인해 수정한 뒤 후속 QA를 요청한다.

## 개발 세션 후속 처리 (2026-10-15)

### 재현 및 수정

- 가져온 QA 기준은 `a592242`이며 앱 소스는 보고서의 `92215ef`와 같다.
  독립 스크립트를 수정 전에 그대로 실행해 **5 failed / 1 passed in 0.94s**를 확인했다.
- SETUP-QA-01: 새 미러 창을 무조건 show하던 경로를 없앴다. 생성 시 기능 일시정지와
  게임/설정 활성 상태를 확인하고 기존 창들의 표시 상태도 동기화한다. 숨긴 상태에서는
  DWM 연결을 미리 만들지 않으며, 재개 후 기존 tick의 표시/연결 경로로 복구한다.
  시작 프리셋·추가·로드·모드 재생성과 ON/OFF 복귀에 같은 규칙을 적용한다.
- SETUP-QA-02: 캡처 종료 여부와 창별 복원 여부를 분리했다. X/트레이 닫기 요청은
  복원 세대를 변경하고, 진행 중 캡처는 그 메인 창만 복원에서 제외한다. 다른 창은
  복원하며 단순 자동설정 중단은 메인도 복원한다. 이후 다시 연 창의 다음 캡처는
  새 세대를 기준으로 정상 복원한다. 완전 종료 시 전체 복원 차단은 유지한다.
- 위 두 수정 후 원래 독립 스크립트를 다시 그대로 실행한 결과는 **5 passed / 1 failed
  in 0.91s**였다. 남은 실패는 아래 최신 요구사항과 충돌하는 기존 시작 화면 assertion이다.

### SETUP-QA-03의 요구사항 대조

- 개발 세션의 최신 사용자 지시는 '메인은 현재 베타 기능이므로 설정을 전부 마친 사람도
  일단 노출하고, 보지 않기를 선택해야 숨긴다. 충분한 테스트 뒤 등록 완료 사용자를
  건너뛰는 동작을 적용한다'였다. 이는 코드 주석에서 추정한 의도가 아니라 명시적인
  사용자 요청이다. 해당 요청에 따라 직전 `92215ef`가 만들어졌다.
- 따라서 현재 베타의 기본 표시를 U-02에 맞춰 되돌리지 않는다. 기획서의 등록 완료 시
  자동 건너뛰기는 이후 안정화 단계의 목표와 구분한다. 요청대로 별도 기획 문서나 기존
  기획서를 수정하지 않는다. 이 QA 응답과 실제 앱 안내에서 현재 동작의 차이를 밝힌다.
- 앱 노트의 '설정을 마치면 버프 탭으로 시작' 문장은 현재 베타 동작과 달랐으므로
  명시적 '다시 보지 않기'만 적용하는 안내로 바로잡았다.
- 최초 독립 테스트의 실패는 위에 그대로 남겼다. 현재 실행용 시작 화면 테스트는
  **등록 완료 + skipSetup=False/True/None** 세 경우의 실제 스택을 각각 엄격히 비교하도록
  변경했다. 다른 두 버그의 기존 assertion은 변경하지 않았다. 최신 정책과 반대인
  '등록 완료면 항상 탭' 구현도 새 테스트에서 실패한다. 이는 개발 세션의 요구사항 반영이며
  새로운 독립 QA 통과 판정이 아니다.

### 개발 검증 범위

- 첫 관련 집합은 **80 passed, 3 warnings in 6.93s**였다. 이후 단순 중단/트레이 닫기
  각각에 대해 다시 열고 재시도하는 경우도 추가했다. 최종 전체 실행 결과는 아래에 기록한다.
- 추가 회귀는 생성 직후의 숨김, 비활성/일시정지 조합, 직접 추가·로드·DWM 모드 재생성,
  생성 도중 활성 상태 변경, 다시 ON 후 표시와 캡처 중 창별 복원/중단/재시도를 확인한다.
- 오디오 생성은 제공된 `scripts.qa_setup_audio_boundary` 플러그인으로 분리했다.
  실제 오디오·장치 전환·Windows의 DWM/포커스·혼합 DPI·게임 입력·장시간 자원 검증을
  통과로 표시하지 않는다. UI 레이아웃, 검출 임계값과 기존 개별 설정은 변경하지 않았다.
- 후속 독립 QA와 Windows 사전 검증 후 배포를 판단한다. 이번에는 main 수정 푸시만
  수행하며 릴리즈 명령·태그·배포를 진행하지 않는다.

### 최종 전체 실행

```bash
QT_QPA_PLATFORM=offscreen PYTHONUTF8=0 PYTHONIOENCODING=cp1252:strict PYTHONPATH=/workspace/mabinogi_addon/scripts/qa_windows_io_probe timeout --signal=TERM --kill-after=5s 240s .venv/bin/python -m pytest -q -p scripts.qa_setup_audio_boundary tests scripts/qa_debuff_flicker.py scripts/qa_tuarim_repeat_alert.py scripts/qa_autofind_missing_assets.py scripts/qa_autofind_mvp.py scripts/qa_tuarim_autofind_crop.py scripts/qa_tuarim_native_followup.py scripts/qa_setup_independent.py
```

- **791 passed, 10 warnings in 137.40s, exit 0**. 제품 전체 tests와 명시한 독립 재현
  스크립트의 현재 요구사항 기준 회귀를 함께 실행했다. 관련 80개와 합산하지 않는다.
- 제한된 샌드박스에서의 첫 전체 시도는 532개 통과와 환경 실패 2개 후 중단했다.
  Discord 로컬 콜백 포트 바인딩이 `[Errno 1] Operation not permitted`로 거부됐고,
  별도 프로세스 종료 시험은 native Qt 오디오 초기화의 IPC 거부 뒤 60초 만료됐다.
  실패 결과를 숨기거나 해당 시험을 제외하지 않고, 로컬 포트/IPC 접근이 가능한 권한으로
  같은 명령을 재실행해 위 전체 통과를 확인했다. 앱 오디오 구현을 수정하지 않았다.
- CP1252 기본 인코딩 및 OpenCV의 비 ASCII 경로 실패 주입은 기존 선택형 검증 도구를
  사용했다. 실제 Windows 실행이 아니다. 경고는 기존 mss/Qt API 사용 중단 안내다.
