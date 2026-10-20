# 단일 시작 화면 개발 — Windows 선행 검증 준비

기준 기획: [단일 시작 로딩 화면과 타이핑 대사](startup-loading-screen-spec.md).

**전체 기능은 미완료다.** 기획 8절의 순서에 따라 압축 해제 중 타이핑과 실제 창 유지부터
검증할 작은 단일 실행 파일을 구현했다. Linux 네이티브 실행은 통과했으며 Windows EXE는
아직 실행하지 않았다. 기존 제품 빌드·시작 경로를 새 화면으로 전환하지 않았다.

## 구현한 범위

- `scripts/startup_splash.py`가 spec 내부에서만 사용하는 `Splash` 하위 클래스를 만든다.
  PyInstaller 전역 객체를 바꾸지 않는다. 기존 부트로더 Tcl 창과 IPC를 확장하며 다른
  로딩 창을 만들지 않는다. 최초 `raise` 전에 크기·대사 영역을 구성한다.
- 승인 합성 로고와 고정 문구를 담은 `440×240` 배경을 사용한다. 로고 비율을 보존하며
  원본 내 거의 투명한 내보내기 흔적(alpha=1)을 제외한 여백만 잘랐다.
  얼굴·말풍선·막대는 없다.
- 기존 16개 대사는 `startup_content.py`로 옮겼다. 기존 Qt 화면도 같은 내용을 읽으며
  이 변경으로 제품의 시작 동작이 달라지지는 않는다.
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

## 실행 결과 — Windows 통과를 의미하지 않음

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

## Windows에서 다음으로 실행할 검증

수동 전용 [Startup splash proof](../.github/workflows/startup-splash-probe.yml)를 추가했다.
push/태그로 실행되지 않으며 게시·태그·제품 후보 생성은 하지 않는다. Windows Python 3.12와
PyInstaller 6.22.3만 설치해 작은 진단 EXE를 빌드·실행한다. 기록만 1일 보관한다.

main 반영 후 실행 명령:

```powershell
gh workflow run startup-splash-probe.yml --ref main -f payload_files=80000
```

압축 해제가 대사 교체보다 빨리 끝나면 검사를 실패시킨다. 이때만 `payload_files=250000`으로
재검증한다. 효과 완료를 기다리는 인위적 제품 대기를 넣어 통과시키지 않는다.
`result.json`의 `platform=win32`, 해당 소스 SHA, 첫 표시부터 단일 창·위치·크기,
Python 진입 전 대사 교체, 상태 유지와 16개 대사 영역 검사가 성공해야 한다.

성공 후 진행할 작업:

1. 제품 spec에 같은 확장을 연결하고 기존 관리자 권한·리소스·버전 정보를 유지한다.
2. Python 진입 시 기존 부트로더 창을 닫지 않고 그 IPC로 실제 업데이트 상태를 보낸다.
   일반 초기화 단계는 대사를 재시작하지 않는다.
3. 배포 부트로더가 없는 개발 실행의 Qt 대체 화면을 같은 디자인으로 구현한다.
4. 준비 완료·중복 실행·예외·업데이트 재실행에서 창과 예약 작업을 정리한다.
   트레이 시작·초기 탭·첫 사용 안내·업데이트 실패 정책을 유지한다.
5. 실제 Windows에서 DPI·모니터 변경·포커스·수명·종료/반복 실행과 전체 제품 회귀를 확인한다.

기획 8절의 “성공하면 업데이트 상태와 본 앱 진입까지 연결한다”는 순서 때문에 위 제품 연결을
선행 검증 전 완료로 보고하지 않는다. 이번 준비만으로 공개 버전·릴리즈 노트를 변경하지 않았다.

## 재현

Tcl/Tk 8.6 공유 라이브러리와 화면이 있는 환경:

```bash
python -m scripts.build_startup_probe --output startup-probe-results --files 250000
python -m scripts.render_startup_splash --output startup-splash-preview.png
```

Qt를 쓰는 기존 중복 실행 테스트와 함께 실행할 때는 QApplication을 먼저 만든다:

```bash
QT_QPA_PLATFORM=offscreen uv run python - <<'PY'
import pytest
from PySide6.QtWidgets import QApplication
app = QApplication([])
raise SystemExit(pytest.main([
    '-q', 'tests/test_startup_splash.py', 'tests/test_windows_ci.py',
    'tests/test_updater.py', 'tests/test_updater_relaunch_env.py',
    'tests/test_single_instance.py',
]))
PY
```
