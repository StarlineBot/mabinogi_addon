# 도르카 선택창 닫기와 제작자 사진 배경 수정

- 날짜: 2026-10-16
- 근거: `docs/qa/도르카_사진호버_크레센도_후속QA_20261016.md`.
- 원본 QA 보고서·이미지·재현 스크립트는 변경하지 않았다.
- QA 재현을 직접 실행해 **5 failed, 3 passed (1.59초)**를 확인했다.

## DORCHA-QA-01 (P2)

도르카는 영역 선택 전 판독 타이머를 멈추고 선택/취소 신호에서 이전 실행 상태로
복구한다. 공용 RegionSelector가 일반 closeEvent를 취소로 전달하지 않아, 일반 닫기
후에는 OFF/ON이나 재진입 Escape로도 판독이 재개되지 않았다.

- 공용 선택창의 미완료 closeEvent를 취소 결과로 전달한다. Escape도 같은 경로를 쓴다.
- 정상 선택은 창을 닫기 전에 완료 상태를 기록해 취소를 중복 전달하지 않는다.
- 완료 이후 중복 닫기/키/마우스 이벤트는 결과를 다시 전달하지 않는다.
- 좌표 선택의 취소는 cancelled, 아이콘 크롭의 취소는 captured(False)로 전달한다.
  크롭 호출자는 captured만 구독하므로 취소 시에도 정상적으로 종료 결과를 받는다.
- 도르카의 기존 실행 상태 복구와 종료 가드는 유지한다. 설정/영역 저장은 취소 시
  실행하지 않으며, 종료 뒤 늦은 취소가 타이머를 재시작하지 않는다.

## CREATOR-HOVER-QA-01 (P3)

autoRaise는 기본 상태의 버튼 패널만 숨긴다. 원형 사진은 정상이어도 Qt 스타일이
hover 시 별도의 사각 배경/테두리를 그렸다. 기존 두 위치 모두 원 밖 496픽셀이 달라졌다.

- 제작자 사진 두 버튼에만 투명 배경/무테/여백 0 스타일을 지정한다.
- 전역 QToolButton 스타일은 변경하지 않는다. 기존 원형 PNG, 크기, 툴팁, 클릭 연결,
  포커스를 가져가지 않는 정책을 유지한다. 사진 파일이 없을 때의 폴백에도 적용한다.
- 수정 후 실제 버튼 렌더의 원 밖 변화는 0픽셀이다. Hover뿐 아니라 눌림/포커스도
  검사하고 클릭 신호 1회와 기존 툴팁을 확인한다.

## 검증

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_dorcha_selector_close_stall.py scripts/qa_creator_avatar_hover.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_region_selector_lifecycle.py tests/test_creator_dialogue.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -m 'not windows_integration'
```

- 수정 후 원본 QA 재현 8건 통과. 공용 선택창/도르카/기존 잡담과 합동 검사 90건 통과.
- 일반 수집에 추가한 선택창 생명주기 20건 통과 (0.86초).
  일반 닫기/Escape/정상 선택/작은 드래그를 좌표·고정 박스·크롭 모드에서 검증한다.
  정상 선택과 취소의 배타성, 중복 종료 억제, 크롭 저장 실패도 포함한다.
- 도르카의 기존 중지 상태와 종료 가드, 100회 반복 닫기의 타이머 재개/영역 보존을 검증한다.
- 원본 hover QA가 생성한 수정 후 두 사진 이미지를 직접 확인했다.
- Linux 격리 전체 회귀: **1,165 passed, 4 deselected, 3 warnings (230.99초)**.
  4건은 별도 Windows 통합 검사이며 경고는 기존 QMouseEvent 사용 경고다.
- 푸시한 정확한 SHA의 Windows 검증 결과는 별도 확인한다.
  기존 크레센도 수정의 Windows 성공과 이번 변경의 성공을 혼동하지 않는다.
- Linux Qt offscreen 검사이며 Windows Alt+F4 자체, 네이티브 스타일, 실제 게임/DPI/
  장시간 검증을 대신하지 않는다. Windows API 접근 차단 시 결과 확인 대기로 남긴다.
