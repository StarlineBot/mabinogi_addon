# 단일 시작 화면 개발 — 제품 시작 경로 연결

기준 기획: [단일 시작 로딩 화면과 타이핑 대사](startup-loading-screen-spec.md).

**제품 시작 경로 연결을 구현했다.** Windows 선행 EXE 검증 성공과 독립 QA 추가분을 확인한 뒤
제품 패키징·실제 업데이트 상태·앱 진입·종료 경로를 연결했다. 선행 EXE 검증과 연결 후 제품의
Windows 통합 검증은 별개이며, 후자는 아직 실행하지 않았다.

## 제품 연결 후 수동 업데이트 회귀 수정

- 독립 QA 소스 `ee46922`에서 기존 '지금 업데이트'의 진행률 소실(P2)을 확인했다.
  시작 화면의 `Splash.step()`에서 진행바·pct 표시를 없앴지만 수동 다운로드도 같은 클래스를
  사용하고 있었다. 10%와 90%가 같은 문구·같은 렌더 해시가 되는 원본 QA 재현을 실행해 실패를 확인했다.
- 수동 경로를 `ui/update_splash.py::UpdateSplash`로 분리하고 기존 `440×208` 로고·아바타·
  진행바 배치를 복원했다. 실제 `pct`를 문구에도 넣는다. 시작 화면의 `440×240` A안과
  무진행바·타이핑·부트로더 IPC 경로는 유지한다. 수동 화면에는 대사 타이머나 IPC를 넣지 않는다.
- 원본 QA 재현은 assertion 변경 없이 **1 passed**로 바뀌었다. 이 역사 재현은 공용 시작 화면에
  실제 진행 콜백을 보내는 검사이므로, 실제 수동 화면의 선택·진행바·종료 경로는 별도 정식 회귀로 보강했다.
- `tests/test_manual_update_progress.py`는 실제 `_on_update_clicked/_on_update_progress/_on_update_result`와
  실제 Qt 수동 화면·시그널을 사용한다. 워커/네트워크/EXE 교체 경계만 대체하고 다운로드 10/90%,
  서로 다른 렌더 픽셀, 진행바 값·숫자, 성공·다운로드 실패·적용 실패·사용자 취소,
  실패 후 메인 복귀와 늦은 시그널 차단을 검사한다.
- 수동 업데이트와 시작 화면/업데이터/Unicode IO 관련 **44 passed / 3.23초**.
  전체 Linux 재검증은 **2,246 passed / 400.88초**, 기존 Qt 폐기 예정 API 경고 3개다.
  로컬 소켓 허용 환경에서 `pytest -n 2 -m 'not windows_integration'`로 실행했으며
  Windows 전용 15개는 실행하지 않았다. 실제 Windows 다운로드·교체·재실행은 미검증이다.
  독립 QA 통과나 게시 완료로 보고하지 않는다.

![수동 다운로드 10%](qa/assets/startup_loading_20261020/manual-update-10.png)
![수동 다운로드 90%](qa/assets/startup_loading_20261020/manual-update-90.png)

재현과 관련 검사:

```bash
QT_QPA_PLATFORM=offscreen python scripts/qa_startup_manual_update_progress_20261020.py
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_manual_update_progress.py tests/test_startup_integration.py tests/test_startup_splash.py tests/test_updater.py tests/test_updater_relaunch_env.py tests/test_unicode_io_contract.py
```

## 확인한 QA와 Windows 선행 검증

- [독립 QA 추가분](qa/헤일로개발과_잡담로그_통합QA_20261020.md)의 시작 화면 절을 먼저 확인했다.
  기존 선행 구현에서 Confirmed Bug / Highly Likely Bug는 없었으며 제품 연결이 후속 범위였다.
- [실행 39397334268 / attempt 1](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39397334268),
  소스 `3748666fccf8e338f7344d9ed11d09e8d0870e8e`의 success와 필수 job/step 성공을 API로 확인했다.
- 실제 job 로그도 커넥터로 조회해 QA와 같은 결과를 확인했다. Windows Python 3.12.10 / PyInstaller 6.22.3,
  압축 파일 80,000개, Python 진입 전 갱신 233회, 대사 교체 성공, 창 1개,
  `440x240+292+264` 유지, 대사 16개 영역 통과, 전체 기록 277개다.
  [로그 결과 JSON](qa/assets/startup_loading_20261020/windows-preflight-log-result.json)에 보관했다.
  기존 실행 로그를 확인한 것이며 Windows EXE를 새로 실행한 결과는 아니다.
- QA 보조 Tcl 검사도 재실행했다. 100,000 콜백, 2,000 상태/재개 전환, 전체 16개 대사 완성,
  동시 예약 최대 1개·종료 후 0개를 확인했다. 동일 Windows 선행 workflow를 재실행하지 않았다.

## 제품에 연결한 경로

- `packaging/build_windows.py`가 기존 CLI 옵션으로 PyInstaller 자체 spec 생성기를 실행한 뒤,
  해당 spec 내부의 `Splash`만 검증된 확장 클래스로 바꾼다. 전역 패키지 수정은 없다.
  관리자 권한·onefile/windowed·버전·아이콘·리소스·모듈 수집/제외 옵션은 유지한다.
  임시 spec 기준으로 자산 경로가 어긋나지 않도록 입력 경로는 절대 경로로 전달한다.
- 새 배경과 고정 대사를 빌드에 사용하고 `pyi_splash`를 명시적으로 포함한다. 검증용 관찰 대기,
  가짜 업데이트 값, 파일 수 증폭, 진단 Tcl은 제품에 포함하지 않는다.
- `main()`이 무거운 Qt import 전에 `StartupScreen`으로 기존 부트로더 IPC를 잡는다.
  Python 진입 후에도 그 실제 창을 유지하며 두 번째 Qt 로딩 창을 만들지 않는다.
- 기존 `_apply_update_before_launch()`의 확인·다운로드 실제 콜백·적용 문구를 같은 IPC로 전달한다.
  일반 단계의 `step(45/95/100)`은 `@resume`만 보내며 진행 중인 대사를 다시 시작하지 않는다.
  업데이트 실패의 기존 로그·현재 버전 실행 정책은 유지한다.
- 앱 준비가 끝나면 대사 완료를 기다리지 않고 로딩 창을 닫고 기존 메인 화면으로 진입한다.
  중복 실행, 업데이트 교체/재실행, import·초기화 실패도 최상위 `finally`에서 정리한다.
  정리는 멱등이며 닫힌 화면에 늦은 상태를 보내거나 창을 다시 만들지 않는다.
- 트레이 시작 여부가 확인되면 기존 부트로더 화면을 닫고, 기존대로 초기 업데이트 확인과
  메인 창 표시를 생략한다. 메인 창의 첫 사용 안내·초기 탭·트레이·작업 시작 정책은 바꾸지 않았다.
- 부트로더가 없는 소스 실행만 같은 배치의 Qt 대체 화면을 사용한다. 단일 QTimer와
  고정 대사 영역을 사용하며 상태/종료 시 취소한다. 배포본의 IPC 실패 시 Qt 창을 새로 띄우지 않는다.
  화면 연결·표시·정리 실패는 로그를 남기고 앱 시작을 계속한다.

## 최초 제품 연결 직후 검증 기록

- 관련 검사 **65 passed / 6.48초**: Tcl 12개, 제품 시작/대체 화면 18개, 빌드 연결 4개,
  기존 Windows 정책·업데이터·재실행·중복 실행 26개, Unicode IO 계약 5개.
  실제 시작 함수를 실행하되 네트워크·
  메인 작업 경계만 대체하여 정상/트레이/중복/업데이트 재실행/오류 경로를 확인했다.
- PyInstaller 6.22.3의 실제 spec 생성기를 모든 제품 옵션으로 실행하고 확장 결과를 Python AST로
  검사했다. Splash 이미지의 위치 인자와 키워드, EXE 권한·버전·아이콘, 자산 절대 경로를 확인했다.
  이 검사는 Windows PE 빌드 실행을 뜻하지 않는다.
- 개발용 실제 Qt 화면을 offscreen으로 렌더했다. 전체 16개 대사가 고정 영역에 들어가며
  상태 표시/재개/닫힘 중 타이머·문구 처리와 중복 화면 생성을 검사했다.
- 실제 `main()`과 실제 `MainWindow`를 함께 실행한 소스 smoke도 일반/트레이 시작 모두 통과했다.
  일반 시작은 작업 시작 시 로딩 1개 → 메인 진입 시 로딩 0개·메인 표시,
  트레이 시작은 로딩 0개·메인 숨김을 확인했고 두 실행 모두 정리 후 실행 중 QThread가 0개였다.
  [관측 JSON](qa/assets/startup_loading_20261020/source-main-smoke.json),
  [재현 코드](qa/assets/startup_loading_20261020/source_main_smoke.py)를 보관한다.
  네트워크/오디오를 격리하고 캡처 3회는 샘플 프레임으로 대체했다. 진입 후 투어 자동 열기를
  생략했으며 마지막 `os._exit` 호출을 Qt 종료로 대체해 종료 후 스레드를 관측했다.
  실제 Windows 강제 종료·캡처 검증으로 해석하지 않는다.
- 전체 Linux 회귀 **2,242 passed / 393.79초**, 기존 Qt 폐기 예정 API 경고 3개.
  로컬 소켓을 허용한 실행 환경에서 `pytest -n 2 -m 'not windows_integration'`로 모든
  비네이티브 테스트를 실행했다. 두 독립 프로세스에서 기존 격리·누수 assertion을 유지했다.
  pytest-xdist는 검증 환경에만 설치했으며 제품 의존성·Windows 검사 workflow는 바꾸지 않았다.
  Windows 전용 15개는 이 실행 대상이 아니다. Windows 제품 연결 후 전체 회귀·PE 빌드,
  실제 네트워크 다운로드/EXE 교체·재실행, 지원 DPI/모니터 변경·게임 포커스·장시간 네이티브
  리소스 검사는 미실행이다. 앞선 작은 EXE 성공으로 제품 전체 Windows 통과를 대신하지 않는다.

![개발 실행 대사](qa/assets/startup_loading_20261020/qt-dialogue.png)
![개발 실행 업데이트 상태](qa/assets/startup_loading_20261020/qt-update.png)

원래 승인받은 배치를 유지했다. 두 번째 이미지는 렌더용 샘플 값이며 실제 다운로드 증거가 아니다.

## 구현한 범위

- `scripts/startup_splash.py`가 spec 내부에서만 사용하는 `Splash` 하위 클래스를 만든다.
  PyInstaller 전역 객체를 바꾸지 않는다. 기존 부트로더 Tcl 창과 IPC를 확장하며 다른
  로딩 창을 만들지 않는다. 최초 `raise` 전에 크기·대사 영역을 구성한다.
- 승인 합성 로고와 고정 문구를 담은 `440×240` 배경을 사용한다. 로고 비율을 보존하며
  원본 내 거의 투명한 내보내기 흔적(alpha=1)을 제외한 여백만 잘랐다.
  얼굴·말풍선·막대는 없다.
- 기존 16개 대사는 `startup_content.py`로 옮겼다. 부트로더와 개발용 Qt 화면이 같은 내용을 읽는다.
- Tcl 타이머 하나로 NFC 한 글자씩 60ms, 완성 후 2초 유지, 즉시 지우고 다음 대사를
  표시한다. 파일명·내부 단계는 무시한다. `@status:`는 예약 작업을 취소하고 완성 문구를
  표시하며 `@resume`은 일반 대사를 재개한다. 닫힌 상태는 재개하지 않는다.
- 이펙트 실패·빈 목록은 기본 문구로 대체한다. 루트 창 파괴 시 예약 작업을 정리한다.
- 초기 DPI의 100/125/150/175/200% 등 25% 간격 배율을 계산한다. 모니터 변경 중 보정과
  실제 Windows DPI·포커스·최상단·반복 실행 자원 검증은 아직 하지 않았다.

## 발견하여 해결한 패키징 문제

PyInstaller **6.22.3**의 `SplashWriter`는 스크립트 길이에 `len(str)`를 기록하면서
실제 내용은 UTF-8 바이트로 쓴다. Tcl 소스에 한글이 직접 있으면 부트로더가 스크립트
뒷부분을 잘라 읽었다. 실제 Linux 동결 실행에서 IPC는 살아 있으나 효과 코드와 진단
파일이 실행되지 않는 현상을 재현했다.

확장 스크립트 전체를 ASCII hex 데이터로 보관하고 Tcl 내부에서 UTF-8로 복원해 평가하도록
수정했다. upstream 패키지를 변경하지 않는다. 생성 결과가 ASCII이고 한글·Tcl 특수문자·
이모지가 원문 그대로 표시되는지 회귀 검사한다. PyInstaller 변경 시 이 경로를 다시 검증해야 한다.

## 최초 선행 구현의 Linux 실행 기록

환경: Linux, Python 3.13, Tcl/Tk 8.6, PyInstaller 6.22.3, 별도 Xorg 가상 화면.
프로젝트 기본 Python 3.12의 정적 Tk 9는 부트로더용 공유 라이브러리가 없어 사용하지 않았다.

[`result.json`](qa/assets/startup_loading_20261020/result.json)과
[`events.tsv`](qa/assets/startup_loading_20261020/events.tsv)에 실제 실행 기록을 보관했다.

| 검사 | 결과 |
|---|---|
| 실제 onefile 압축 해제 | 512바이트 파일 250,000개. 효과를 위한 부트로더 대기 없음 |
| Python entry 이전 | 타이핑 29회, 완성·유지 후 다음 대사 표시 확인 |
| 창 식별자·위치·크기 | 첫 Map부터 `wm frame` 1개, `440x240+420+280` 유지 |
| 업데이트 상태 유지 | 진단용 확인/37% 문구를 즉시 표시하고 각각 400ms 후에도 유지 |
| 전체 번들 대사 | 16개 모두 실제 Tcl canvas bbox가 고정 문구 영역 내에 들어옴 |
| 대사 복귀 | 같은 창에서 재개 |
| 관련 회귀 | 38 passed — 신규 Tcl 12개와 기존 Windows 빌드·업데이터·재실행 환경·중복 실행 검사 |
| workflow 문법 | actionlint 1.7.7 통과 |

진단 entry의 관찰 대기(400ms, 3.5초)는 검증 EXE에만 있으며 제품 시작 코드에 넣지 않았다.
진단 업데이트 문구의 37%는 샘플이다. **제품의 실제 다운로드 연동을 검증한 결과가 아니다.**
이 작은 검증은 앱의 전체 회귀나 독립 QA를 대체하지 않는다.

실제 Tcl 8.6 화면 캡처(가장 긴 대사, Linux 글꼴 대체 적용):

![실제 Tcl 시작 화면](qa/assets/startup_loading_20261020/tcl-longest.png)

이미지는 배치 확인 자료이며 Windows EXE 실행 증거는 아니다. 사용자에게 실제 렌더를 공유했고
2026-10-20 “이 배치 유지”로 승인받았다. 이 승인은 배치 확정이며 Windows 실행 검증과는 별개다.

## 선행 검증 도구의 범위

수동 전용 [Startup splash proof](../.github/workflows/startup-splash-probe.yml)를 추가했다.
push/태그로 실행되지 않으며 게시·태그·제품 후보 생성은 하지 않는다. Windows Python 3.12와
PyInstaller 6.22.3만 설치해 작은 진단 EXE를 빌드·실행한다. 기록만 1일 보관한다.

선행 검증 실행에 사용한 명령(현재 통과했으므로 제품 연결 확인을 위해 반복할 필요 없음):

```powershell
gh workflow run startup-splash-probe.yml --ref main -f payload_files=80000
```

압축 해제가 대사 교체보다 빨리 끝나면 검사를 실패시킨다. 이때만 `payload_files=250000`으로
재검증한다. 효과 완료를 기다리는 인위적 제품 대기를 넣어 통과시키지 않는다.
`result.json`의 `platform=win32`, 해당 소스 SHA, 첫 표시부터 단일 창·위치·크기,
Python 진입 전 대사 교체, 상태 유지와 16개 대사 영역 검사가 성공해야 한다.

기획 8절의 “성공하면 업데이트 상태와 본 앱 진입까지 연결한다”는 순서를 지켰다.
제품 연결 후에는 후속 QA와 변경된 소스의 Windows 제품 검증이 필요하다. 태그·게시·배포 모드는
이번 개발에서 실행하지 않는다. 미공개 `0.8.0` 노트에 시작 화면 설명을 추가하며 버전은 올리지 않는다.

## 재현

Tcl/Tk 8.6 공유 라이브러리와 화면이 있는 환경:

```bash
python -m scripts.build_startup_probe --output startup-probe-results --files 250000
python -m scripts.render_startup_splash --output startup-splash-preview.png
```

제품 소스 시작 smoke:

```bash
QT_QPA_PLATFORM=offscreen python docs/qa/assets/startup_loading_20261020/source_main_smoke.py
QT_QPA_PLATFORM=offscreen python docs/qa/assets/startup_loading_20261020/source_main_smoke.py --tray
```

Qt를 쓰는 기존 중복 실행 테스트와 함께 실행할 때는 QApplication을 먼저 만든다:

```bash
QT_QPA_PLATFORM=offscreen uv run python - <<'PY'
import pytest
from PySide6.QtWidgets import QApplication
app = QApplication([])
raise SystemExit(pytest.main([
    '-q', 'tests/test_startup_splash.py', 'tests/test_startup_integration.py',
    'tests/test_startup_build.py', 'tests/test_windows_ci.py',
    'tests/test_updater.py', 'tests/test_updater_relaunch_env.py',
    'tests/test_single_instance.py',
]))
PY
```
