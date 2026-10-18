# 체력바 미리보기 상태 전환 QA 수정

- 날짜: 2026-10-18 (Asia/Seoul).
- 기준: `5defab0` 및 미리보기 전환 독립 QA.
- 범위: 설정 화면의 출력 예시 크기/스크롤 갱신. 게임 판독/실제 오버레이 크기/경고는 변경하지 않는다.

## 수정 전 재현

원래 QA 스크립트를 수정하지 않고 실행해 **1 failed, 3 passed (11.54초)**를 확인했다.
12px/조작별 이벤트 처리 조건에서 반복 2회째 300% 출력의 실제 내용 폭은 741,
필요 폭은 1440, 내부 스크롤 범위는 13이었다. 수동 재계산 뒤에는 1440/712로 복구됐다.
스크립트는 수동 복구 이전 관측값을 검사하므로 복구로 실패를 숨기지 않는다.

## 원인 및 변경

배율/표시 콜백의 동기 크기 계산 뒤 자식 레이아웃이 확정되면서 내용의 필요 크기가
달라졌다. viewport 자체가 다시 resize되지 않으면 재계산할 계기가 없었다.

- 내용 위젯의 LayoutRequest를 감지해 이벤트 처리 뒤 다시 맞춘다. 자식 레이아웃을
  활성화하고 실제 내용 크기를 sizeHint와 일치시킨 뒤 높이/스크롤을 갱신한다.
- 단일 부모 소유 single-shot QTimer(0ms)로 변경을 모은다. 유휴 반복 폴링은 없고,
  숨김 시 예약을 취소하며 다시 표시할 때 현재 내용으로 재계산한다.
- 높이와 선호 크기가 실제로 바뀔 때만 상위 geometry를 갱신해 반복 갱신을 제한한다.
- 내용은 원래 배율이며 페이지 최소 폭을 늘리는 고정 폭은 다시 도입하지 않는다.
  모든 변경은 메모리의 미리보기 geometry이며 별도의 설정 저장을 하지 않는다.

## 검증

독립 QA 재현을 일반 회귀 `tests/test_stat_preview_transition.py`에 그대로 편입했다.
같은 내용에 대한 기대값은 바꾸지 않았고, 별도 검사로 100회 LayoutRequest의 단일 실행,
유휴 중 추가 실행 없음, 탭 이동 시 예약 취소, 종료 시 예약 정리를 확인한다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_stat_preview_transition_20261018.py tests/test_stat_preview_transition.py tests/test_stat_preview_width.py -q --tb=short
```

초기 집중 검사는 **13 passed (14.03초)**였다(독립 재현과 회귀 편입은 중복 조건이다).
주변 회귀는 **162 passed**, 새 종료 순서 검사만 준비 오류로 실패했다(전체 실행은
1 failed, 162 passed / 112.24초). 창을 먼저 닫은 뒤 탭 숨김 검사에서 예약이 활성화될 것을
기대한 테스트 순서를 바로잡았다. 숨김/종료 취소 assertion은 그대로 유지했다.
제품 소스의 추가 변경 없이 최종 전환·정리 파일 **5 passed (7.17초)**를 확인했다.
두 실행에서 4개 전환 조건이 중복되며, 관련 163개 고유 조건을 확인한 결과다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stat_preview_transition.py tests/test_stat_preview_width.py tests/test_wrapping_controls.py tests/test_tuarim_settings_width.py tests/test_navigation_all_widths.py tests/test_tour_layout.py tests/test_settings_grouping.py tests/test_stat_bars.py tests/test_stat_bars_stability.py tests/test_stat_visibility.py tests/test_stat_shake.py tests/test_boss_tab.py tests/test_navigation.py tests/test_main_shutdown.py tests/test_release_notes.py -q --tb=short
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stat_preview_transition.py -q --tb=short
```

기본 글꼴에서 반복 전환한 실제 렌더를 열어 원래 크기 바와 내부 스크롤을 확인했다.
`compileall`과 `git diff --check`도 통과했다. 기존 QA 재현/이미지는 수정하지 않았으며
실패 기대값 완화, 새 skip, 누수 assertion 제거는 없다.

## 제한

Linux Qt offscreen 검사다. 실제 Windows 글꼴/혼합 DPI/게임 전환, 장시간 리소스,
네이티브 및 exe는 미검증이다. Windows Actions·태그·릴리즈는 실행하지 않는다.
실패한 v0.4.89 태그는 보존하고 아직 미사용인 v0.4.90 노트에 설명만 추가한다.
