# v0.4.89 Windows 릴리즈 실패 분석

- 일자: 2026-10-18 (Asia/Seoul).
- 실패 소스: `3abd09b09891b46b6df3b784e3684fe7c6d87f7a` / 태그 `v0.4.89`.
- 실행: https://github.com/StarlineBot/mabinogi_addon/actions/runs/39124144038
- job: `build-windows` / `117665629018`. 실제 다운로드한 job 로그와 소스를 대조했다.
- 실패 단계: `Test gate (pytest)`. **7 failed, 1717 passed, 1 skipped, 10 deselected,
  3 warnings (522.42초)**. 의존성 설치는 성공했다.
- 네이티브 검사/exe 빌드/Release 첨부/공개 저장소 갱신/배포 공지는 모두 skipped다.
  무료 한도·결제·아티팩트 quota 또는 PyInstaller 실패가 아니다. 이 실행으로 배포되지 않았다.

## P2 / Confirmed Bug: Windows 큰 글꼴에서 체력바 페이지 가로 넘침

- 조건: 실제 Windows 러너에서 20px 글꼴, 작업 영역 `(0,0,900,1000)`의 설정/안내 방문.
- 영향: 체력바 설정 콘텐츠가 가용 폭을 초과하며, 가로 스크롤 없이 모든 조작에 접근해야
  하는 기존 요구사항을 위반한다. 실제 게임 판독 실패나 실행 중 크래시가 확인된 것은 아니다.
- 증거: `test_navigation_all_widths.py::test_all_pages_and_controls_large_font[area0]`는
  `('stat_bars','horizontal_range',13,776,789)`로 실패했다. 실제 viewport 폭은 776,
  콘텐츠 최소 폭은 789였다. 안내 완료/건너뛰기 흐름 두 건도 체력바에서 같은 검사에 실패했고,
  진단은 콘텐츠/최소 폭 790, 가로 범위 14를 기록했다.
- 관련 소스: `src/mabinogi_addon/ui/stat_bars_tab.py`의 그룹 내부 레이아웃,
  `placement_row`/`alert_row` 및 `_resize_display_preview()`의 고정 폭 계산을 우선 확인한다.
  기존 바깥 여백 외에 새 QGroupBox 내부 여백/프레임과 세로 스크롤바를 포함한 실제 viewport
  폭으로 수축 가능한지 추적해야 한다. 현재 로그만으로 최소 폭을 강제한 단일 위젯까지
  확정하지 않았으므로 특정 줄 하나의 계산이 유일한 원인이라고 단정하지 않는다.
- 직접 확인한 실패:
  - `tests/test_navigation_all_widths.py::test_all_pages_and_controls_large_font[area0]`
  - `tests/test_tour_layout.py::test_seeded_navigation_and_tour[complete-True-area0]`
  - `tests/test_tour_layout.py::test_seeded_navigation_and_tour[skip-True-area0]`
- Windows CI 실행으로 확인된 제품 회귀다. Linux에서 이전 통과한 폭 검사를 Windows
  통과로 대신하지 않는다. 사용자 글꼴/조작을 과실로 취급하지 않는다.
- 개발 검증: 실제 Windows 글꼴 폭과 그룹 내부 여백/스크롤바 조건을 보존한 채 원인을 고친다.
  글자 축소, 필요한 버튼 숨김, 가로 넘침 assertion 삭제로 해결하지 않는다. 기본/20px,
  짧은 작업 영역/좌측 모니터, 큰 배율 예시, 진단 펼침/접힘, 설정 불변성을 회귀한다.

## P2 / Confirmed Bug: 새 UI 구조와 맞지 않는 기존 검사가 릴리즈를 차단

### 숨겨진 투아림 개별 컨트롤을 기본 화면에서 확인하는 검사 2건

- `tests/test_tuarim_settings_width.py:41`은 `w.tuarim_tab.region_btn`을 기본 화면에서
  보이는 버튼으로 간주한다. 새 화면에서는 개별 영역 조정이 기본 접힘이고, 해당 컨트롤은
  그 안으로 이동했다. 개별 자동찾기 버튼은 공통 자동찾기 도입으로 숨겨졌다.
- 등록 전/후 모두 `region_btn`의 visibleRegion이 null이어서 실패한다. Windows 로그에서
  숨겨진 버튼 rect의 기본값 640x480을 실제 표시 버튼의 크기로 오해하면 안 된다.
- 명세상 기본 공통 명령과 펼친 개별 보정 명령은 모두 접근 가능해야 하지만, 접힌 명령을
  항상 표시할 의무는 없다. 실제 컨트롤 트리와 명세를 따라 검사 대상을 조정해야 한다.
- `scripts/qa_tuarim_settings_width.py`의 기존 보조 검사도 숨겨진 개별 auto_find_btn의
  좌표만 확인하므로 이번 공통 버튼 접근성을 보증하지 못한다. 공통 화면에서 실제 표시된
  버튼인지 확인하고, 개별 조정은 펼친 뒤 수동 지정/보기/해제를 검사한다.

### 보스/체력바 버튼 행을 옛 정보·명령 행으로 간주하는 검사 2건

- `tests/test_wrapping_controls.py:38`은 QFormLayout의 LabelRole 위젯이 등록 정보이고
  FieldRole이 명령이라고 가정해 두 위젯의 세로 분리를 강제한다.
- 새 구현은 등록 정보를 이미 위의 독립 줄로 옮겼다. 해당 두 위젯은 자동찾기/직접 지정/
  보기 명령 묶음과 해제 명령 묶음이다. 20px/지정 최소 폭에서 한 줄에 들어오면 같은 y가
  정상일 수 있지만 검사는 예전 구조를 기준으로 실패한다.
- Windows: 보스 `52 >= 52+28`, 체력바 `145 >= 145+28` 실패.
  Linux 직접 실행에서도 각각 `70 >= 70+37`, `172 >= 172+37` 실패했다.
- 명세의 정보/명령 분리와 실제 부족한 폭에서의 안전한 줄바꿈, 모든 조작의 가시성,
  설정/글꼴 불변성을 새 구조 기준으로 유지한다. 단순 skip 또는 assertion 삭제는 아니다.

### 기존 검사 그대로 직접 재현

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest tests/test_wrapping_controls.py tests/test_tuarim_settings_width.py::test_all_controls_accessible_with_non_ascii_deep_windows_path -q --tb=short --show-capture=no
```

- Linux 결과: **4 failed (2.12초)**, 종료 코드 1. 제품/기존 테스트를 수정하지 않았다.
- 이 네 건은 Windows 전용 제약이 아니라 기존 UI 검사의 구조 갱신 누락이다.
  실제 레이아웃 회귀 3건과 분리해 처리해야 한다.

## QA 누락 및 다음 단계

- 직전 후속 QA는 null/잡담 수정에 맞춘 193개 및 추가 독립 6개를 실행했고, 이전 설정
  그룹화 QA는 461개를 실행했다. 기존 wrapping_controls와 투아림 전체 컨트롤 가시성
  검사, Windows 글꼴의 최종 폭 문제를 놓쳤다. 앞선 로컬 통과를 릴리즈 전체 검사 통과로
  보고한 것은 아니지만, UI 재부모화/그룹 변경에 영향받는 회귀 선택이 충분하지 않았다.
- 이후 같은 화면 변경에서는 이번 실패 네 파일의 관련 조건을 빠뜨리지 않고 포함한다.
  단, 매번 전체 Windows 수동 실행을 요구하거나 무료 한도 정책을 되돌리는 뜻은 아니다.
- 개발 세션에서 제품 폭 회귀와 검사 구조를 함께 수정한 뒤 독립 QA를 진행한다.
  같은 SHA의 Re-run만으로 해결될 실패로 보지 않으며 유료 재실행을 시작하지 않았다.
- 실패한 v0.4.89 태그는 삭제/이동하지 않는다. 새 수정본 후속 QA 뒤 원격 최신 태그와
  노트를 다시 확인해 다음 미사용 버전의 릴리즈 명령을 준비한다. 이번에는 명령을 주지 않는다.
- 실제 Windows job 결과 외에 사용자 PC의 화면 클릭/게임/혼합 DPI는 미검증이다.
  원시 CI 전체 로그/사용자 로그/설정은 커밋하지 않고 이 분석 문서만 공유한다.
