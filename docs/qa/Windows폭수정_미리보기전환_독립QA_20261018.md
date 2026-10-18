# Windows 폭 수정 후 / 미리보기 상태 전환 독립 QA

- 일자: 2026-10-18 (Asia/Seoul).
- 대상 소스: `586775ee3169cf8141615d59bb142e1d3bd2b640`.
- 요구사항: 그룹 내부 실제 가용 폭에 맞추되 출력 배율을 줄이지 않고, 넘치는 출력은
  미리보기 내부 스크롤로 전부 볼 수 있어야 한다. 표시 항목/배율/화면 전환 뒤에도 유지한다.
- 결론: 이전 Windows 실패 관련 로컬 검사와 주변 회귀는 통과했지만, 아래 미리보기 전환
  결함을 추가로 재현했다. 새 소스의 실제 Windows 검사 성공을 확인한 것은 아니다.
- 제품/기존 테스트/설정/출력 자산은 수정하지 않았다. QA 보고서/재현/생성 렌더만 공유한다.

## P2 / Confirmed Bug: 상태 전환 뒤 미리보기 내용 폭과 스크롤 범위가 오래된 값에 머묾

- 조건: 기본 12px 글꼴의 실제 MainWindow에서 체력바 페이지를 연다.
  배율 300→50→150을 바꾸며 50에서는 생명력만, 나머지에서는 세 항목 모두 표시한다.
  진단 펼침/접힘 및 메모→체력바 탭 복귀를 수행한 뒤 다음 300% 상태에서 재현된다.
  각 개별 조작 사이에도 Qt 이벤트를 처리한 조건에서 실패하므로 빠른 합성 입력만의 문제가 아니다.
- 영향: 300% 바가 3개 들어가야 하는 미리보기 내용이 오래된 좁은 크기에 남아 각 바가
  잘린다. 스크롤을 끝까지 옮겨도 원래 크기의 전체 출력을 확인할 수 없다.
  페이지 전체의 가로 넘침은 0이다. 실제 게임 오버레이 판독/경고나 프로세스 크래시가
  확인된 것은 아니며, 이 제보의 범위는 설정 화면 출력 예시다.
- 실패 상태: 내용 `sizeHint().width()`=1440, 실제 내용 폭=741, viewport 폭=728,
  내부 가로 범위=13. 필요한 내부 범위는 1440-728=712다.
- 실제 렌더: [실패 화면](assets/stat_preview_transition_20261018/failed-12.png).
  세 바가 각각 원래 출력 크기로 스크롤되는 대신 좁은 자식 영역에서 잘려 보인다.
- 원인/위치: `src/mabinogi_addon/ui/stat_bars_tab.py:74`의 새 `_DisplayPreview`,
  `:86`의 `fit_content()`, `:97`의 resizeEvent 및 `:754`/`:762`의 항목/배율 변경 경로.
  변경 콜백에서 동기적으로 맞춘 크기가 자식 레이아웃 확정 뒤 달라질 수 있는데,
  viewport 자체가 다시 resize되지 않는 경우 내용 크기/스크롤 범위가 다시 맞춰지지 않는다.
- 원인 대조: 실패 상태/렌더를 먼저 기록한 뒤 테스트에서만 기존
  `tab._resize_display_preview()`를 한 번 호출했다. 실제 내용 폭=1440, 가로 범위=712로
  복구됐다. 이 진단용 호출은 제품 수정이나 실제 앱의 자동 복구로 집계하지 않는다.
  재현은 복구 전 관측값을 assertion하므로 수동 재계산으로 실패를 숨기지 않는다.

### 독립 실행

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_stat_preview_transition_20261018.py -q --tb=short --show-capture=no
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest 'scripts/qa_stat_preview_transition_20261018.py::test_preview_repeated_scale_group_and_page_changes[True-12]' -q --tb=short --show-capture=no
```

- 최종 전체 재현: **1 failed, 3 passed (3.35초)**. 12/20px, 개별 조작마다 이벤트 처리 여부를
  나눴다. 실패는 개별 처리/12px 조건이며, 같은 조건만 단독 실행해도 실패했다.
- 실제 설정 컨트롤의 신호/페이지/미리보기/저장을 사용한다. 임시 설정과 게임/캡처/외부 소리
  격리는 기존 fixture 경계다. 글꼴/배율을 억지로 줄이거나 실패 기대값을 약화하지 않았다.
- 초기 QA 초안의 '150%에서는 항상 내부 스크롤이 없어야 함'은 잘못된 가정이었다.
  가용 폭보다 실제 내용이 넓으면 배율과 무관하게 내부 스크롤이 정상이므로 실측 차이로
  검사를 바로잡았다. 그 초기 실패를 제품 버그로 집계하지 않는다.
- 그 뒤 실제 내용 폭 741/필요 폭 1440의 별도 상태 전환 실패를 확인했다.
  최종 재현은 그룹 여백을 바꾸지 않고 실제 UI 상태 변경만으로 실행한다.
- 미해결 재현은 `scripts/qa_*.py`에 두어 일반 테스트 수집에는 추가하지 않는다.

## 이전 실패 관련 확인

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest tests/test_stat_preview_width.py tests/test_wrapping_controls.py tests/test_tuarim_settings_width.py tests/test_navigation_all_widths.py tests/test_tour_layout.py tests/test_settings_grouping.py tests/test_stat_bars.py tests/test_stat_bars_stability.py tests/test_stat_visibility.py tests/test_stat_shake.py tests/test_boss_tab.py tests/test_navigation.py tests/test_main_shutdown.py tests/test_release_notes.py -q --tb=short --show-capture=no --basetemp=/tmp/qa_width_586775e
```

- **158 passed (42.54초)**. 이전 실패 관련 파일/새 미리보기 검사 및 주변 회귀를 직접 실행했다.
- 검사 수정은 새 공통/개별 진입 구조에 맞췄고, 실제 버튼의 가시성/폭 부족 시 줄바꿈과
  충분한 폭에서의 복귀, 글꼴/설정 불변성과 페이지 가로 범위=0을 유지한다. skip 추가가 아니다.
- 기본/20px와 100/300%, 그룹 여백 변경·복원, 진단 접힘/펼침, 좁고 짧은 작업 영역/좌측
  모니터 및 안내 완료/건너뛰기 조건을 포함했다. 초기 20px/300% 체력바와 강제 줄바꿈 보스
  렌더를 직접 열어 확인했다. 정적 조건의 통과를 이후 상태 전환까지 확대하지 않는다.
- `git diff --check` 통과. 설정 레이아웃 변경의 회귀 파일 목록이
  `docs/windows-validation.md`에 추가된 것도 확인했다.

## 개발 전달 및 배포 판단

- 자식 내용/레이아웃이 확정되거나 표시 항목·배율이 바뀐 뒤, 실제 출력 크기와 스크롤
  범위를 다시 일치시킨다. 무한 resize/updateGeometry 순환, UI 대기 폴링/타이머 누적,
  페이지 최소 폭 재증가 또는 출력 배율 임의 축소가 생기지 않도록 회귀한다.
- 한 번의 300% 설정뿐 아니라 300→50→150→300, 세 항목→하나→세 항목, 다른 탭 복귀,
  진단 접힘/펼침과 기본/큰 글꼴의 조합을 유지한다. 예시 영역의 세로 잘림도 함께 확인한다.
- 실제 Windows 글꼴/DPI/네이티브/게임 전환/장시간 자원/exe는 미검증이다.
  새 소스의 Windows Actions를 실행하거나 이전 실패 run을 재시작하지 않았다.
- 확인 시 원격 최신 태그는 실패한 v0.4.89이고, 소스 노트는 v0.4.90이다.
  v0.4.89 이하 기존 노트는 원격 태그와 동일하다. 태그/노트는 수정하지 않았다.
- 현재 추가 결함을 개발 세션에 전달하며 릴리즈 명령은 보류한다. 실패 태그는 삭제/이동하지 않는다.
