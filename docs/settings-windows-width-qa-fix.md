# Windows 설정 폭 및 릴리즈 회귀 후속 수정

- 날짜: 2026-10-18 (Asia/Seoul).
- 기준 소스: `3971f44` 및 Windows v0.4.89 릴리즈 실패 분석.
- 기존 null 복구/잡담 후속 QA는 통과 판정이었다. 이 문서는 이후 Windows 릴리즈에서
  확인된 레이아웃 회귀와 검사 구조 갱신 누락의 수정만 다룬다.

## 재현 및 원인

- QA의 기존 검사 명령을 그대로 실행해 보스/체력바 버튼 행 2건과 투아림 개별 버튼
  가시성 2건, 총 **4 failed**를 확인했다.
- 체력바 출력 미리보기는 `self.width()-48`로 고정 폭을 설정했다. 페이지 전체 폭을
  기준으로 한 상수여서 그룹 내부 여백/프레임/실제 가용 폭을 반영하지 못했고,
  고정 폭 자체가 상위 페이지의 최소 폭을 늘려 수축을 방해했다.
- 새 회귀의 300%/그룹 여백 조건을 수정 전 소스로 실행해 페이지 가로 범위 228로
  실패하는 것을 확인했다. Windows의 13/14px 사례와 같은 크기의 재현이라고 주장하지 않는다.
- 새 회귀 작성 중 바의 존재하지 않는 `scale` 속성을 참조한 준비 오류도 수정했다.
  제품 실패의 증거는 그 다음 수정 전 제품 소스로 확인한 가로 범위 assertion이다.

## 수정

- 원본 크기의 출력 내용과 수축 가능한 미리보기 viewport를 분리했다. 미리보기는
  내용 크기를 선호 크기로 제공하되 고정 최소 폭을 강요하지 않는다. 실제 그룹 레이아웃이
  가용 폭을 정하고, 넘치는 출력만 내부 가로 스크롤을 사용한다. 글꼴/출력 배율을 줄이지 않는다.
- 보스/체력바 검사는 독립된 등록 정보 줄과 두 명령 묶음을 구분한다. 폭을 실제로
  부족하게 만드는 조건에서 해제 명령의 줄바꿈, 넓어졌을 때 복귀, 모든 조작 가시성,
  글꼴과 설정 불변성을 검사한다. 넘침 assertion을 제거하지 않았다.
- 투아림 검사는 기본 공통 명령을 먼저 검사하고, 개별 조정을 펼쳐 두 판독 영역의
  수동 지정/보기/해제 접근성을 확인한다. 의도적으로 숨긴 옛 개별 자동찾기는 표시 대상으로
  오인하지 않되, 실제 공통 자동찾기의 가시성을 검사한다. 기존 보조 QA 스크립트도 같은
  실제 화면 구조로 갱신했다. 한글 긴 경로의 줄바꿈 검사는 유지한다.
- 실패한 원격 v0.4.89는 보존한다. 변경 설명만 다음 미사용 버전 v0.4.90에 추가하며,
  태그 생성/이동, 릴리즈 및 Windows Actions를 실행하지 않는다.

## 검증

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stat_preview_width.py tests/test_wrapping_controls.py tests/test_tuarim_settings_width.py tests/test_navigation_all_widths.py tests/test_tour_layout.py -q --tb=short
```

- **34 passed (43.49초)**. 기본/20px, 100/300%, 그룹 여백 변경·복원,
  진단 접힘/펼침, 짧은 작업 영역/좌측 모니터, 안내 완료/건너뛰기 경로를 포함한다.
- 20px/300% 실제 Qt 렌더를 직접 확인했다. 출력은 원래 크기이고 내부 스크롤만 생기며
  주요 명령과 그룹은 화면 폭 안에 들어온다. Windows 화면 검증으로 집계하지 않는다.
- 추가 그룹 화면/체력바 판독·상태·흔들림/보스/탐색/종료/공개 노트 회귀는
  **124 passed (36.61초)**였다. 위 34개와 다른 테스트 파일이다.
- `compileall`, `git diff --check` 통과. v0.4.89 이하 공개 노트는 원격 실패 태그의
  내용과 동일함을 비교했다. 기존 실패 태그의 삭제/이동이나 노트 덮어쓰기는 하지 않았다.
- 같은 종류의 화면 변경에서 네 기존 실패 관련 파일과 새 미리보기 검사를 빠뜨리지 않도록
  `docs/windows-validation.md`에 로컬 회귀 선택 기준을 추가했다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_grouping.py tests/test_stat_bars.py tests/test_stat_bars_stability.py tests/test_stat_visibility.py tests/test_stat_shake.py tests/test_boss_tab.py tests/test_navigation.py tests/test_main_shutdown.py tests/test_release_notes.py -q --tb=short
```

## 제한

Linux Qt offscreen 결과다. 실제 Windows 글꼴/DPI/창 합성, 게임 전환, 장시간 리소스,
네이티브 및 exe 빌드는 미검증이다. 무료 한도 정책에 따라 수동 Windows 재실행은
시작하지 않았다. 기존 실패 run은 pytest 실패로, quota/아티팩트/빌드 실패가 아니다.
후속 QA와 다음 태그의 전체 회귀·네이티브·exe 성공 전에는 배포 성공을 선언하지 않는다.
