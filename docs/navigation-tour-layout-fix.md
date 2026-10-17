# 큰 글꼴 투어 설명 겹침 수정

- 근거: `docs/qa/전투보조_탐색구조_독립QA_20261017.md`의 P3 `NAV-TOUR-LAYOUT-QA-01`.
- 원본 재현 스크립트/기대값/QA 이미지는 변경하지 않았다.
- 수정 전 동일 행렬에서 **2 failed, 10 passed (15.43초)**를 직접 확인했다.
  900x1000 논리 작업 영역, 20px 글꼴의 6단계에서 강조 대상은 정착 후 아래로 이동했지만
  설명 카드가 초기 좌표에 남아 버튼 일부를 가렸다.

## 수정

- `TourOverlay`는 현재 강조 대상과 호스트까지의 부모 위젯에 이벤트 필터를 설치한다.
  스크롤은 대상 자체가 아니라 상위 내용 위젯을 이동하므로 부모도 감시한다.
- 이동/크기/레이아웃/표시 변경 이벤트를 받으면 소유한 단발 QTimer로 다음 이벤트 루프의
  재배치를 예약한다. 여러 이벤트는 예약 하나로 합친다. 후속 레이아웃 이동도 다시 처리한다.
- 재배치 시 최신 보이는 영역을 기준으로 카드 위치와 강조 그리기를 함께 갱신한다.
  타이머가 주기적으로 동작하거나 idle 상태를 polling하지 않는다.
- 단계 전환은 이전 예약을 정지하고 이전 대상의 필터를 해제한 뒤 현재 대상만 감시한다.
- 숨김/종료/완료의 `dismiss()`는 예약과 대상/부모/호스트 필터를 정리한다. 타이머는
  투어 QObject에 종속되어 투어 파괴 뒤 살아남는 정적 singleShot 콜백을 추가하지 않는다.
- 기존 2단 탭, 글꼴, 카드 치수와 단계별 이동/접근/복귀 정책은 바꾸지 않는다.

## 검증

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_navigation_tour_layout.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_tour_layout.py tests/test_navigation.py tests/test_setup.py tests/test_creator_dialogue.py -q --tb=short
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/render_navigation.py --large-tour --out /tmp/navigation-tour-fixed
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -m 'not windows_integration'
```

원본 행렬 12건은 `tests/test_tour_layout.py`에서도 변경 없이 일반 회귀에 편입한다.
기본/20px 글꼴, 세 작업 영역(음수 원점 포함), 앞뒤 이동과 완료/건너뛰기,
저장 설정과 전체 정지 상태 보존을 그대로 검사한다.
추가로 호스트를 옮기지 않은 스크롤, 이벤트 100건 병합 및 idle 무실행,
이전 대상 필터 해제, 숨김 직후 재열기/늦은 갱신 차단, 종료 중 예약 정지를 검사한다.

관련 회귀 **240 passed (73.76초)**. 이 수치는 원본 행렬 12건과 추가 예약/종료 검사 5건,
기존 탐색/안내/제작자 말풍선 회귀를 포함하며 개별 실행 수를 중복 합산하지 않는다.
큰 글꼴 제품 렌더의 `/tmp/navigation-tour-fixed/tour-6.png`에서도 강조 버튼과 카드가
겹치지 않는 것을 확인했다.
전체 격리 회귀 **1,347 passed, 5 deselected, 3 warnings (343.16초)**.
5건은 별도 Windows 네이티브 검사이며 경고는 기존 QMouseEvent 사용 경고다.
기존 QThread 누수 검사를 유지했고 실패 skip이나 assertion 완화는 추가하지 않았다.

Linux offscreen 및 논리 작업 영역 모사는 Windows
혼합 DPI/실장치 변경이나 실게임 장시간 자원 검증이 아니다.
새 수정 SHA의 Windows 테스트/필수 통합/exe 빌드는 푸시 후 별도로 확인하며 이전 SHA의
성공으로 대신하지 않는다. 태그/릴리즈는 실행하지 않는다.
