# 도르카·투아림 통합 구현 및 검증

## 승인 범위

- 기준: `dorcha-tuarim-integration-spec.md`, `navigation-structure-spec.md`.
- 사용자 확인: 새 % 표시는 기본 OFF·Discord 로그인 베타. 설정한 사람은 기존 설정을 유지한다.
- 후속 도르카 재시작 QA는 [별도 수정/미해결 기록](dorcha-restart-context-fix.md)으로 구분한다.
  자체 가림 자동 복구 조건 1건은 미해결이며 통합 기능의 통과로 덮어쓰지 않는다.
- 실제 Qt 렌더의 상단 세 사용 체크 → 표시·배치 → 판독 영역 → 알림 기준 순서를 승인했다.
  도르카만/%만/둘 다/둘 다 판독 불가의 실제 오버레이 렌더도 함께 공유했다.
- 화면별 디자인을 일괄 정리하거나 커스텀 오버레이 동작을 변경하지 않는다.

## 설정 및 탐색

- `ResourceTab`이 기존 도르카·투아림 컨트롤을 한 화면에 재배치한다.
  숨겨진 기존 위젯은 판독/설정 컨트롤러로 유지하며 별도 설정 탭으로 노출하지 않는다.
- 실제 탭은 버프/디버프/보스 패턴 알림/체력바/도르카·투아림/커스텀/단축바/메모의 8개다.
- 기존 `tuarim` 내부 주소는 `dorcha`와 같은 scroll 객체를 가리키는 호환 별칭이다.
  별도 창/탭/타이머를 추가하는 것이 아니며, 알림 설정 요청은 기존 알림 기준 영역이 보이게 스크롤한다.
- 기존 첫 사용 안내의 투아림 체크와 자동설정은 기존 알림 사용 및 % 영역만 제어한다.
  도르카/% 표시를 자동으로 켜거나 다른 영역으로 덮어쓰지 않는다.
- 기존 `tuarim.enabled/box/thresholds/sounds`와 `dorcha.enabled/box/pos/scale/locked`를 유지한다.
  새 `dorcha.showTuarim`은 저장된 bool 값을 유지하며 항목이 없을 때만 False로 읽는다.
  생성/로그아웃/탭 이동만으로 설정을 저장하거나 초기값을 기록하지 않는다.
- 설정 저장은 기존 section 병합 API를 사용하므로 무관한 설정/알 수 없는 키를 유지한다.
  저장 실패는 성공으로 안내하지 않고 경고하며, 영역은 저장 성공 후에만 교체한다.

## 관측 및 알림

- 기존 투아림의 150ms 타이머가 알림 또는 허용된 % 표시를 위해 한 번만 캡처·판독한다.
  도르카는 그 관측 신호를 구독하며 %를 다시 캡처하거나 판독하지 않는다.
- 같은 원시 값이 두 번 연속 확인된 새 관측만 % 표시로 보낸다.
  새 값의 확인 대기, 캡처 실패/비활성/미등록/100% 보류는 None으로 전달한다.
  표시용 이전 안정값을 새 관측이나 재무장 근거로 다시 넣지 않는다.
- 영역 캡처 옆의 기존 안정값 라벨은 `최근 확정`으로 명명해 현재 유효 관측과 구분한다.
- 기존 TuarimTracker의 임계 발화/재무장/설정 변경 정책과 소리 설정은 유지한다.
  % 체크는 도르카 설정만 저장하므로 기존 알림 트래커를 초기화하지 않는다.
- 도르카 기존 200ms 판독, 게임 대상 검증, 재탐색 worker 및 backoff는 유지한다.
  한쪽 숫자 실패는 해당 요소만 지우며 정상인 다른 숫자나 알림을 중단하지 않는다.
- 알림 OFF + % ON이어도 관측을 계속하고, 표시 둘 다 OFF + 알림 ON이면 표시 없이 알림만 처리한다.
  셋 모두 OFF이면 새 실시간 캡처·판독을 하지 않는다. 명시적 수집/지정 도구는 별도다.
- 로그아웃/전체 오버레이 일시정지는 베타 표시만 숨기며 저장된 체크를 바꾸지 않는다.
  일반 투아림 알림에 로그인/오버레이 정지 조건을 추가하지 않는다.
- 영역 선택/자동찾기 중에는 자원 표시를 숨겨 선택 UI에 간섭하지 않는다.
  종료 시 두 타이머·재탐색 worker·선택/강조 창·캡처 객체를 정리한다.

## 표시와 배치

- 기존 DorchaOverlay 하나에서 왼쪽 `95%`/`--%`, 오른쪽 `N/15`/`--/15`를 그린다.
  15칸 보라색 바는 도르카 전용이며 %만 사용하면 바와 도르카 수치를 그리지 않는다.
- 모든 조합에서 같은 창 크기/좌표를 유지하고 기존 전체 배율/잠금/클릭 통과를 사용한다.
  %만 표시해도 배율·위치 고정을 조절할 수 있다.
- 값이 같거나 표시 요소가 같을 때 불필요한 update 요청을 추가하지 않는다.
- 기존 투아림 수집 도구는 펼침 버튼 아래에 그대로 제공한다. 로그인 접근 조건과
  긴 경로 줄바꿈을 유지하며 확장한 상태의 버튼 접근도 검사한다.
- % 표시가 꺼져 있고 지울 이전 %도 없으면 관측 슬롯을 바로 종료한다.
  기존 투아림 알림만 사용할 때 새 표시 경로로 로그인/표시 설정을 매 틱 다시 조회하지 않는다.

## 검증 명령

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_resource_integration.py tests/test_dorcha_overlay.py tests/test_navigation.py tests/test_tuarim_settings_width.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_setup.py tests/test_tour_layout.py tests/test_dorcha_tracking.py tests/test_dorcha_game_target.py tests/test_dorcha_roi_context.py tests/test_dorcha_autofind.py tests/test_region_selector_lifecycle.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -m 'not windows_integration'
```

- 신규 검사는 세 사용 체크의 8조합, 한쪽 실패/양쪽 실패/실제 0, 표시 전환과 탭 이동
  반복 후 알림 중복 방지 및 실제 0 재무장, 로그아웃/정지 시 일반 알림 유지,
  %만 사용하는 경우, 좌표/배율/잠금 보존, 캡처 실패/비활성/100%/종료/선택 중 오래된 값
  제거, 기존 설정 유무 3조건의 반복 생성과 파일 불변, 저장 권한 오류를 확인한다.
- 50/100/125/150/200/300% 배율의 실제 QImage 픽셀과 폰트 치수로 바/숫자 표시 여부,
  두 숫자의 가용 폭, 값/조합 변경 전후 위치·크기·잠금 불변을 검사한다.
- 실제 렌더: `/tmp/resource-integration-preview/settings.png`, `overlay-states.png`.
  렌더 데이터는 시안용이며 실게임 판독 성공 증거가 아니다.
- 원본 판독 샘플/독립 QA 스크립트/PNG/ZIP과 기존 스레드 누수 검사는 보존한다.
  기존 테스트의 9개 탭 기대는 승인된 8개 탭 및 이전 주소 호환으로 변경하고,
  수집 도구 접근 검사는 펼침 버튼을 연 뒤 원래 버튼 가시성 조건을 그대로 검사한다.
- Linux Qt/합성 관측 검사를 실제 Windows 게임·혼합 DPI·절전·알림 청취 검증으로 대신하지 않는다.
  main 푸시 후 정확한 SHA의 Windows 격리 회귀·네이티브 통합·exe 빌드를 별도로 확인한다.
  기존 b4c6eb1의 Windows 성공은 이번 통합의 검증으로 재사용하지 않는다.

## 실제 실행 결과

- 첫 사용 안내·투어·도르카 재탐색/대상/영역 선택: **253 passed (259.12초)**.
- 마지막 도움말 위치·표시 문구·진입 스크롤 반영 후 관련 통합/탐색/설정 폭:
  **52 passed (49.55초)**. 표시 OFF 관측 슬롯 최적화 후 통합/기존 도르카:
  **43 passed (32.18초)**. 두 실행은 중복하므로 합산하지 않는다.
- 50~300% 픽셀/폰트 기하와 기존 투아림/통합의 별도 실행은 **73 passed (47.50초)**다.
  기본/20px 실제 통합 렌더와 모든 표시 버튼 접근은 **2 passed (7.60초)**다.
- 표준 수집은 Windows 전용 5건을 제외한 1,409건이다. 로컬 전체 단일 실행은 assertion 실패
  없이 86% 이후까지 진행했지만 **900초 상한으로 exit 124**가 되어 완주 성공으로 보고하지 않는다.
  같은 수집 순서의 `test_time_sets.py`(0-based 시작 1202)부터 끝까지 별도 배치로 재실행한다.
  86% 표시로 확인되는 완료 범위와 겹치게 시작하며 skip/assertion 변경으로 건너뛰지 않는다.
- 후반 배치 207건은 처음 **203 passed, 4 failed (144.96초)**였다.
  실패 4건은 `tests/test_windows_ci.py`의 YAML 구성 검사이며 클라우드의 기존 가상환경에
  `yaml`이 없었다. 저장소의 pyproject/lock에는 이미 포함된 개발 의존성이었다.
  `uv sync --frozen --group dev`로 PyYAML 6.0.3을 추가했고, 제품 런타임 의존성 버전은 바뀌지 않았다.
  실패 4건을 포함한 해당 파일 전체는 재실행해 **20 passed (1.10초)**다.
  제품/기대값을 고쳐 환경 누락을 숨기지 않았고 중복 실행을 고유 통과 총계로 합산하지 않는다.
- 후반 재실행 범위: `test_time_sets`, `test_toast`, `test_top_edge_selector`, `test_tour_layout`,
  `test_tracker_layout`, `test_tuarim`, `test_tuarim_button_background`, `test_tuarim_native_autofind`,
  `test_tuarim_settings_width`, `test_unicode_io_contract`, `test_updater`, `test_updater_relaunch_env`,
  `test_warn_gone`, `test_window_watcher`, `test_windows_ci` (모두 `tests/`의 `.py` 파일).
- 현재 실행환경의 상태 조회에서는 제한된 네트워크 정책이 적용돼 있고 `api.github.com`이
  실제 적용된 허용 목록에 없었다. Git HTTPS 접근 성공을 Actions API 접근 성공으로 대신하지 않는다.
  이 제약이 해소되기 전에는 해당 수정 SHA의 Windows 확인 완료/QA 준비로 보고하지 않는다.
