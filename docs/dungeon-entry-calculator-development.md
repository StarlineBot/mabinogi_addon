# 던전 입장 계산기 개발 검증

## 범위

승인된 실제 앱 기반 목업의 편의기능 탭을 구현했다. 기존 계산기와 전투 기능은 유지한다.
고정 보상 세 던전은 네트워크 없이 계산하며, 균열은 개당가 기준 비용만 계산한다.
1~11차 표시는 화면 범위이며 게임의 입장 상한을 의미하지 않는다.

## 조회와 수명

- 새로고침 시에만 한 요청을 실행한다. 중복 요청과 자동 주기 조회는 없다.
- 기존 경매장 목록 조회와 개당 최저가 계산을 사용한다. 실패와 매물 없음은 별도로 안내한다.
- 조회 시작 시 이전 가격을 제거한다. 가격 미상은 `—`이며 0으로 계산하지 않는다.
- 작업 스레드는 큐만 갱신한다. Qt 접근·설정 저장·토큰 포함 예외 출력은 없다.
- 응답은 현재 선택 던전의 렌더링으로 전달하여 다른 던전 표를 덮지 않는다.
- 결과 대기 중에만 100ms 타이머를 사용한다. 완료·앱 종료 시 중지한다.
- 앱 종료 시 취소 플래그로 추가 페이지 조회를 막는다. 진행 중 urllib 호출은 강제 종료하지 않으며 최대 10초의 네트워크 타임아웃을 따른다. 페이지 시작 시 30초 조회 예산을 검사한다.

## 검증

`tests/test_dungeon_cost.py`는 계산표, 손실, 12차 규칙, 편린 개수, 키 없음,
매물 없음, 실패·잘못된 가격, 늦은 응답, 종료, 가로 스크롤, 20회 연속 조회의
서로 다른 가격과 워커 종료를 검증한다. 네트워크는 대체한다.

실제 MainWindow를 외부 장치·네트워크 경계 대체 상태로 렌더링해 두 계산 화면을 확인했다.
최종 실행: `env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dungeon_cost.py tests/test_market.py tests/test_navigation.py tests/test_navigation_all_widths.py tests/test_bead_split.py -q --tb=short`
결과: **53 passed in 25.39s**. 별도로 초기 관련 회귀는 44 passed였다(중복 포함이며 합산하지 않는다).
Windows·실제 경매 API·한글 Windows 경로·혼합 DPI·장시간 게임 병행은 미검증이다.
일반 푸시의 Windows Actions와 태그·릴리즈는 실행하지 않는다.

## 독립 QA 후 업데이트 안내 보완

- QA 대상 `7ddcb6d`: 기능 관련 회귀 90개와 독립 검증 5개 통과가 보고됐다.
- 공개 노트에 계산기 안내가 빠져 최초 실행·0.4.90 이후 업데이트 안내에서 누락되는 P3를 확인했다.
- 수정 전 QA 재현 스크립트를 직접 실행해 동일한 2개 실패를 확인했다.
- 원격 최신 태그가 v0.4.90임을 확인하고 미공개 v0.4.91 노트에 기능 위치·계산 내용을 추가했다. 과거 공개 노트와 제품 동작은 변경하지 않았다.
- 일반 수집 회귀 `tests/test_dungeon_release_note.py`에 두 진입 조건을 추가했다.
- 수정 후 노트 관련 일반 회귀와 QA 재현 스크립트 실행: **16 passed in 4.28s**. 명령은 `env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dungeon_release_note.py tests/test_release_notes.py tests/test_release_notes_trigger.py scripts/qa_dungeon_release_note_20261019.py -q --tb=short`이다.
- 이번 수정에서 기능 95개 검증은 재실행하지 않았다. 제품 동작이 동일하므로 기존 독립 QA 결과와 구분해 기록한다. Windows/API 미검증 범위는 그대로다.
