# 전투 보조 조작·안내 정돈 개발 검증

- 날짜: 2026-10-19 (Asia/Seoul).
- 기준: `ed4f3c4`의 확정 명세와 승인 목업 10장.
- 판독/알림 알고리즘, 임계값, 사용 조건, 권한, 기존 설정 키/데이터는 변경하지 않는다.

## 반영 범위

- 버프: 기존 두 열과 일반 편집을 보존하고, 기준 버프/일반 버프/선택 없음의 오른쪽 화면을
  분리했다. 기준 버프 역할·포함 조건과 표시/알림 대상이 아님을 설명한다. 고정 항목의
  삭제/순서 제한은 그대로다. 목록 전환만으로 설정을 저장하지 않는다.
- 디버프: 기본 자동찾기와 기존 한 번의 공동 승인을 그대로 사용한다. 기본 직접 지정/
  보기/해제 대상은 디버프임을 설명하며 아이콘 줄과 보스 바를 함께 포함하도록 안내한다.
  공유 보스 등록 상태는 기본 화면에 별도로 보이고 개별 수동 조정/보기/해제는 접힌다.
  로그인·진단 모드의 기존 접근 조건과 공유 영역 변경/해제의 영향 확인은 유지한다.
- 위치 잠금: 버프/디버프/보스 경고/목록/자원/메모의 단일 토글은 공통 민트색과 기존
  상태 문구를 사용한다. 전체 명령은 일반 버튼이다. 삭제/해제는 활성 상태에만 붉은
  글자를 쓰며 비활성 명령을 활성 경고처럼 칠하지 않는다.
- 체력바: 미리보기 각 바 아래에 개별 잠금을 추가했다. 다른 바의 잠금, 표시/알림,
  전체 일시중단을 바꾸지 않는다. 전체 명령은 숨긴 바를 포함한 세 바 모두에 적용한다.
  기존 저장/오버레이 잠금 경로를 사용하고 실제 잠금과 버튼 상태를 동기화한다.
- 추가 사용자 요청으로 체력바의 앱 내부 예시만 가용 폭에 맞춰 축소한다. 실제 게임
  오버레이와 저장한 배율은 바꾸지 않는다. 표시 항목/배율/탭 변경 후에도 내용 전체가
  viewport 안에 들어오며 가로 스크롤 범위가 0인 것을 검사한다.
- 도르카·투아림: 기본 등록 상태는 네 상태를 구별하고 좌표는 기존 개별 조정/보조 정보로
  제공한다. 세 독립 체크와 공통 등록/부분 성공/해제 범위는 그대로다. 두 표시를 꺼도
  표시 미리보기를 숨기지 않으며 일반 투아림 알림의 권한도 바꾸지 않는다.
- 커스텀: 위쪽 콤보 선택/불러오기/관리와 현재 편집 목록을 분리했다. 관리 구간은 접히며
  삭제 대상과 시작 시 불러오기를 담는다. 현재 이름을 제목마다 중복하지 않는다.
  선택과 적용·자동 저장·시작 대상은 독립이고 저장 실패/재시도/설정 교체 경로는 유지한다.
  빈 목록/선택 없음에 맞춰 명령을 즉시 갱신한다. 삭제 확인에는 실제 대상 이름을 표시하고
  다수 항목은 요약해 확인창이 무제한으로 커지지 않게 한다.
- 단축바: 첫 칸 지정 조건과 빈칸 우클릭 안내만 정리했다. 개별 그룹 목록/잠금 UI는
  추가하지 않는다. 메모는 표시 영역의 위치/너비·내용에 따른 높이와 자동 저장을 안내한다.
- 공통 제목은 고정된 밝은 회색 대신 기본 팔레트 글자색을 사용해 두 테마에서 읽을 수 있다.

## 검증과 상태 전환

`tests/test_interaction_polish.py`는 기준/일반/선택 없음 반복과 저장 불변성,
체력바 개별/전체 잠금 및 로그인 게이트, 빈 목록/선택 변경의 명령 상태,
두 자원 표시 OFF에서도 미리보기와 독립 알림이 유지되는 조건을 검사한다.

8개 실제 페이지를 기본/20px와 밝은/어두운 명시적 Qt 팔레트 조합으로 렌더하고
가로 범위=0, 보이는 버튼의 접근성, 화면 방문으로 설정/타이머가 늘지 않는지 검사한다.
Linux offscreen의 명시적 팔레트 검증이며 Windows 테마 엔진 검증으로 확대하지 않는다.
초기 팔레트 주입에서 일부 자식이 밝은 팔레트를 유지해 테스트 주입을 바로잡았고,
새 명세의 접힌 공유 보스 조정을 기존 검사도 펼친 뒤 확인하도록 갱신했다.

초기 관련 묶음은 79 passed/1 failed(기존 펼침 가정)이었고, 해당 기대를 새 화면 구조에
맞춘 뒤 수정 관련 묶음 63 passed, 탐색/폭/미리보기 묶음 41 passed를 확인했다.
미존재 테스트 파일을 지정한 초기 명령은 0개 실행이므로 검증에 집계하지 않는다.
최종 큰 관련 회귀 묶음은 **510 passed (291.15초)**였다. 이후 미등록 상태의 해제/보기
명령 활성 상태를 보완하고 관련 묶음 **83 passed (37.37초)**, 잠금 버튼의 선택 전후
여백/높이를 통일한 뒤 최종 스타일·상태·폭 묶음 **64 passed (55.48초)**를 확인했다.
세 실행은 중복 파일을 포함하므로 합산하지 않는다. 기존 누수/외부 경계 assertion은 유지했다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_interaction_polish.py tests/test_custom_autosave.py tests/test_custom_config_replacement.py tests/test_debuff_auto.py tests/test_interaction_consistency.py tests/test_region_registration.py tests/test_resource_integration.py tests/test_resource_common_settings.py tests/test_setup_common_resources.py tests/test_setup.py tests/test_tracker_layout.py tests/test_settings_grouping.py tests/test_navigation.py tests/test_navigation_all_widths.py tests/test_wrapping_controls.py tests/test_tuarim_settings_width.py tests/test_tour_layout.py tests/test_stat_preview_width.py tests/test_stat_preview_transition.py tests/test_stat_bars.py tests/test_stat_bars_stability.py tests/test_stat_visibility.py tests/test_stat_shake.py tests/test_boss_tab.py tests/test_skillbar_mirror.py tests/test_memo_lock_persist.py tests/test_main_shutdown.py tests/test_lifecycle.py tests/test_release_notes.py -q --tb=short
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_interaction_polish.py tests/test_region_registration.py tests/test_boss_tab.py tests/test_memo_lock_persist.py tests/test_resource_integration.py tests/test_release_notes.py -q --tb=short
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_interaction_polish.py tests/test_tracker_layout.py tests/test_navigation_all_widths.py tests/test_wrapping_controls.py tests/test_tuarim_settings_width.py tests/test_stat_preview_width.py tests/test_stat_preview_transition.py tests/test_release_notes.py -q --tb=short
```

샘플 판독값과 혼합 잠금 상태, 선택/편집 대상이 다른 프리셋 상태도 실제 위젯으로
렌더해 직접 확인했다. PNG는 테스트 임시 산출물이며 원본 게임 캡처가 아니다.
`compileall`과 `git diff --check`도 통과했다.

일반 편집 폼을 측정하는 기존 트래커 검사는 기준 버프 대신 일반 버프를 선택하도록
준비를 바꾸되 잘림/접근성 assertion은 유지한다. 전환 컨테이너를 패널 자체로 사용했을 때
작은 창의 얼굴 공간과 겹치는 회귀를 확인해, 기존 바깥 패널은 유지하고 안쪽만 전환하도록
수정했다. 큰 글꼴로 내용이 늘면 측정된 가용 공간에 따라 하단 전용 공간으로 복귀하는
기존 동작을 검사하며 무조건 떠 있는 하단을 강제하지 않는다.

추가 요청에 따라 미리보기의 기존 '가로 넘침을 내부 스크롤로 확인' 기대는 체력바에
한해 바뀌었다. 독립 QA 원본 스크립트는 그대로 보존하고 일반 회귀에서 동일 전환 순서,
설정 보존/내용 크기 동기화/타이머 정리 조건을 유지한 채 가로 범위 0과 실제 오버레이
배율 불변성을 검사한다. 바뀐 요구사항을 실패 skip으로 우회하지 않는다.

## 제한과 전달

게임/캡처/오디오/네트워크는 기존 테스트 경계에서 격리한다. 새 상시 캡처·타이머·
투어·팝업 안내는 추가하지 않는다. 실제 Windows DPI/네이티브/게임 전환·장시간 자원·
exe는 미검증이다. 일반 푸시 Windows Actions 중단 정책을 유지한다.
태그·릴리즈는 진행하지 않으며, 기능 푸시는 최종 검증 후 사용자 승인을 받는다.
