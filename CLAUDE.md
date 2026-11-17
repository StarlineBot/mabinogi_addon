# mabinogi_addon

마비노기 화면을 실시간으로 분석해서 버프·디버프를 오버레이로 보여주는 Windows 상주 프로그램.
**작업 규칙은 `AGENTS.md`, 현재 상태와 결과 요약은 `docs/status.md`, 기능 명세는 `docs/기획서.md`를 따른다.**

## 작업 방식

작업 범위·푸시/승인·비용·개발/독립 QA·테스트 선택/재사용·배포 정책은 [AGENTS.md](AGENTS.md)를 따른다.
사용자 실행 방법은 [Windows 검증](docs/windows-validation.md), 현재 결과는 [상태](docs/status.md)에 둔다.

## 소통

- **확인할 수 있는 건 끝까지 직접 확인하고 결론만 말한다(사용자 지시 11-17).** 답은 '된다' 또는 '안 된다(이유)'. '모른다·확인 못 했다·해 봐야 안다'로 넘기지 않는다 — 비용 없는 시험(잘못된 입력으로 권한 확인, 조회 API, 로컬 재현 등)부터 찾아 해 본다. 할 수 있는지 사용자에게 묻지 않는다.
- 한국어로 대화한다.
- `AGENTS.md`의 다음 행동 안내를 적용한다. 필요한 조작·회신·후속 처리를 명시하고,
  할 일이 없으면 추가 조작이 불필요하다고 알린다. 응답 종료 뒤 감시/작업을 약속하지 않는다.
- 사용자는 Spring 백엔드 경력 10년+ 개발자. Python 데스크톱·Windows API·이미지 처리는 익숙하지 않을 수 있으므로,
  새로운 패턴이 나오면 "코드 → 런타임 동작 → 시스템 영향"을 짧게 브리핑 톤으로 설명한다.

## QA·디버깅

[AGENTS.md](AGENTS.md)의 개발/독립 QA, 변경 영향 검사·결과 재사용, 라이브 실패 조사 절을 따른다.

### QA 세션 필수 규칙 (사용자 지시 — 이 파일은 매 세션·요약 뒤에도 자동으로 읽히므로 여기 둔다)

- 사용자가 말한 실측·사용 조건은 사실로 받는다. 사용자 실수를 의심하는 되묻기(설정·소환·확인 여부 등) 금지.
  차이가 나면 앱·공식·데이터 원인을 찾고, 필요한 자료만 묻는다.
- 검사 순서(목표 5분 안팎, 차례로 쌓지 말 것):
  1. 바뀐 파일의 테스트만 먼저(실패하면 멈춤).
  2. 배포 검사는 **CI 글꼴로 한 번만**: `FONTCONFIG_FILE=$S/fonts-ci.conf uv run --frozen python -m scripts.run_release_checks --version X.Y.Z`
     (로컬은 코어 전부 사용 ≈1.5~2.5분, CI는 `-n 2` 그대로). 같은 코드·버전으로 이미 통과했으면 스크립트가 다시 돌지 않는다(`.qa-stamps/`, 꼭 필요하면 `--again`).
  3. 전체 테스트(≈14분)는 AGENTS.md '변경 영향 검사'의 넓은 변경일 때만. 대상 없는 pytest는 **프로젝트 훅(`.claude/hooks/test_guard.py`)이 막으며**,
     필요하면 명령 앞에 `FULL_REGRESSION_REASON='이유'`를 붙이고 배포 검사와 동시에(백그라운드) 돌린다.
  4. 2분 넘는 명령은 시작 전에 예상 시간을 사용자에게 말한다.
- **배포 실행은 QA 세션이 직접**(사용자 결정 11-17): QA 통과 → 버전·노트·검사 목록 main 반영 → GitHub MCP `actions_run_trigger`로
  `windows.yml` `verify-only` 실행(묻지 않음). 사용자가 후보 확인 뒤 "배포해" → 그 run을 `candidate_run`으로 `publish-existing` 실행.
  사용자에게 `gh` 명령을 넘기지 않는다(권한 오류일 때만 오류 원문과 함께). `validate-and-publish` 금지. 자세히는 AGENTS.md 'QA 통과 후 배포 안내'.
- 후보 실행 뒤 1~2분 안에 작업 시작(jobs 수)을 확인하고, 대기 중이면 바로 알린다.
- 새 자산·모듈이 들어간 버전은 Windows 실행 확인 전에 게시를 권하지 않는다(CI는 exe를 실행하지 않음).

## 개발 환경

- 회사 맥(Apple Silicon)과 집 Windows를 오가며 개발. 게임은 Windows에서만 실행 가능.
- Python 3.12, 패키지는 uv로 관리: `uv sync`, `uv run pytest`, `uv run mabinogi-addon`
- Windows 전용 의존성(dxcam, pywin32)은 `sys_platform == 'win32'` 마커로 분리되어 있다.
- 커밋 작성자는 이 저장소 로컬 설정(StarlineBot)을 사용한다. 회사 메일을 쓰지 않는다.

## 구조

```
src/mabinogi_addon/
  capture/   FrameSource 인터페이스와 구현체 (File / Video / Live(dxcam))
  detect/    아이콘 템플릿 매칭, 시간 판독(숫자·단위 템플릿)
  tracker/   버프 상태 머신, 내부 시계, 앵커 판정
  ui/        메인 창, 영역 지정, 오버레이, 트레이 (PySide6)
  system/    OS 의존 기능: 포그라운드 감지, 자동 실행, 중복 실행 방지, DPI
tests/
  data/      테스트용 스크린샷(PNG). 영상은 용량 때문에 git 제외
docs/
  기획서.md
```

## 규칙

- 화면을 **읽기만** 한다. 키 입력·클릭 자동화, 게임 메모리 읽기는 절대 넣지 않는다.
- OS 의존 코드는 `capture/`의 Live 구현체와 `system/`에만 둔다. 나머지는 맥에서 테스트 가능해야 한다.
- OpenCV는 `opencv-python-headless`만 사용 (일반판은 PySide6와 Qt 충돌).
- 성능 목표: 탐지 1회 5ms 이하, CPU 평균 1~2% 이하. 이미지 처리에 Python 픽셀 반복문을 쓰지 않는다.
- `cv2.setNumThreads(1)` 유지.
- 경로는 `pathlib.Path`로 다룬다 (맥/Windows 공용).
- 탐지 로직을 바꾸면 `tests/data` 기반 회귀 테스트를 추가하거나 갱신한다.
- `tests/data`에 가로 1200px 이상 스크린샷을 올리는 커밋은 `tests/test_skillbar_testers.py` CASES에 그 파일의 단축바 위치 기대값도 같이 넣는다(빠지면 `test_case_list_covers_all_large_screenshots` 실패).

## 화면(UI) 개발 — 반드시 사용자 피드백을 받을 것

화면 규칙(조작 모양·버튼 크기·탭 틀·글자·색)은 [`docs/ui-rules.md`](docs/ui-rules.md)에 모아 두었다. 새 화면·변경 전에 먼저 본다.

새 탭·오버레이·화면을 만들거나 **레이아웃을 바꾸면**, 코드만 올리지 말고 **먼저 렌더해서
사용자에게 보여주고 피드백을 받는다.** 사용자는 화면을 직접 돌려보기 전엔 레이아웃을
판단하기 어렵고, 글로 설명하면 오해가 생긴다. (게임은 Windows에서만 돌지만, 화면 자체는
맥/리눅스에서도 **오프스크린으로 렌더**해 캡처할 수 있다.)

렌더 방법(맥/리눅스/CI 공용): `QT_QPA_PLATFORM=offscreen` 으로 Qt를 띄우고, 위젯을
`grab()` 해서 PNG로 저장한 뒤 사용자에게 보낸다. 네트워크·게임이 필요한 값은 **샘플
데이터를 주입**해 결과 영역까지 채워 보여준다(예: 계산 결과는 순수 계산 함수에 가짜 시세를
넣어 `_show()`/`_render()` 직접 호출). 예:

```python
# QT_QPA_PLATFORM=offscreen uv run python shot.py
import os; os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
w = SomeTab(); w.resize(760, 430)
# ... 샘플 데이터 주입(네트워크 없이 결과 영역까지 채우기) ...
w.grab().save("out.png")   # 이 PNG를 사용자에게 보여주고 피드백 받기
```

- 레이아웃은 **스펙을 글로 확정**받고(라벨 정렬·칸 배치 등), 구현 후 **렌더 이미지로 재확인**한다.
- 피드백 없이 큰 UI를 완성형으로 밀어붙이지 않는다 — 작게 보여주고 고친다.

## 버전 번호

[AGENTS.md의 버전 번호 정책](AGENTS.md#버전-번호-정책)을 따른다.

## 릴리즈 노트 (중요 — 세션이 바뀌어도 이 규칙을 따를 것)

새 버전을 처음 실행하면 `src/mabinogi_addon/assets/release_notes.md` 의 해당 버전 노트가
첫 화면에 뜬다(구현: `ui/release_notes.py`, 마지막 본 버전은 config `lastSeenVersion`).
노트는 **커밋 메시지를 그대로 붙이지 말고, 사용자가 읽을 수 있게 손으로 쓴 톤**으로 쓴다.

작성 규칙:
- **사용자에게 보이는 변경**(새 버프/기능, UI 변경, 동작 변화 등)을 만들 때마다, 그 작업
  커밋에 `release_notes.md` 맨 위 **다음 버전 섹션**에 항목을 한 줄 추가한다. (내부 리팩터링·
  테스트 전용 변경은 노트에 넣지 않는다.)
- 형식: 섹션 헤더는 정확히 `## vX.Y.Z` (버전만, 뒤에 다른 글자 없음 — 파서가 이 형식만
  버전으로 인식한다). 헤드라인(가장 큰 변화) + 필요하면 `> 인용`으로 주의사항 + "조용히
  다듬은 것들" 묶음 순으로.
- **Windows 후보 검증 전**: 맨 위 섹션 버전을 확정 버전과 맞춘다.
  검증 후에는 노트/제품을 바꾸지 않는다. 바꾸면 후보를 재검증하며 태그는 검증 SHA에 붙인다.
- 과거 섹션은 지우지 않는다(여러 버전 건너뛴 사용자가 그 사이 노트를 모아 본다).
- 후보 확인·게시 승인·태그/재검증 절차는 [AGENTS.md](AGENTS.md)의 Windows 검증과 산출물 승격 및
  QA 통과 후 배포 안내 절을 따른다.

현재 개발·QA·배포 상태는 `docs/status.md`를 확인한다.
