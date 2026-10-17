# 투아림 저대비 십의 자리 판독 보완

- 날짜: 2026-10-18 (Asia/Seoul).
- 근거: `docs/qa/투아림_저구간_상시표시_독립QA_20261018.md`.
- 펠롬 후속 QA는 제품 `8192a70`의 Windows 회귀/네이티브/exe 성공을 확인했다.
  이번 투아림 수정의 Windows 검증을 대신하지 않는다.

## 원인과 수정 범위

기존 13px 판독 경로는 십의 자리 이진화 잉크가 5픽셀 미만이면 모양 매칭을
검사하지 않고 일의 자리만 반환했다. 원본 16/12/14는 십의 자리 잉크가 3픽셀이나
NCC가 기존 0.6 기준 이상이다. 18은 일의 자리 최고점 정렬에서는 십의 자리가
불확실하고, 오른쪽 1px 정렬에서 1의 NCC 0.6175, 8의 NCC 0.8638이다.

- 기존 잉크 5픽셀 이상 경로와 작은 렌더/넓은 영역/100% 보류 경로를 유지한다.
- 잉크 1~4픽셀인 경우에만 기존 정렬 및 좌우 1px에서 두 자리를 함께 확인한다.
- 십의 자리 `1`은 기존 NCC 0.6 이상, 일의 자리는 같은 숫자이고 NCC 0.85 이상이어야 한다.
  호출자가 더 높은 threshold를 요구하면 그 값도 지킨다.
- 이 조건에서 불확실한 값은 None으로 보류한다. 한 자리 값을 무조건 10 이상으로
  보정하거나 희박한 배경을 90%대로 승격하지 않는다. 빈 십의 자리의 정상 한 자리
  판독은 그대로다. 공통 원판독값을 0으로 바꾸지 않는다.
- 영역/설정/체크/로그인 조건/알림 및 재무장 상태 머신은 변경하지 않았다.
  새 캡처, 타이머, 워커, 파일 읽기나 샘플을 추가하지 않았다.

## 재현 및 회귀

원래 QA 스크립트와 원본 PNG/ZIP, 기존 assertion은 변경하지 않았다.
일반 CI에서 같은 QA 조건을 수집하는 `tests/test_tuarim_low_range_display.py`를 추가했다.
희박한 잉크의 가짜 9/4, 낮은 십의 자리 확신, 같은 정렬의 낮은 일의 자리 확신은
보류하고 빈 십의 자리는 분류조차 하지 않는 대조군도 추가했다.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_tuarim_low_range_display.py tests/test_tuarim.py tests/test_resource_integration.py tests/test_resource_live_samples.py tests/test_tuarim_native_autofind.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_tuarim_low_range_display.py tests/test_autofind_diagnostics.py tests/test_release_notes.py tests/test_release_notes_trigger.py -q --tb=short
```

- 수정 전 원래 QA: **7 failed, 5 passed (5.91초)**.
- 수정 후 원래 QA 및 기존 판독/알림/통합/실원본/자동찾기: **115 passed (114.16초)**.
  2,926장 세션의 알림 횟수, 정상 90%대, 실제 초기화 후 재무장, 100% 보류를 포함한다.
- CI 재현 수집/부정 대조군/진단/노트: **89 passed (29.06초)**.
- 최종 코드의 CI 재현 수집/부정 대조군 및 판독/알림 재실행: **56 passed (12.03초)**.
- CI 재현/버튼 배경·픽셀 위상별 배율/공유 앵커: **108 passed (223.49초)**.
  `tests/test_tuarim_low_range_display.py tests/test_tuarim_button_background.py tests/test_resource_anchor.py`.
- 초기 추가 검사 명령에 존재하지 않는 `tests/test_tuarim_native_reading.py`를 넣어
  수집 전 종료했다. 실제 파일을 확인해 위 명령으로 재실행했다. 통과 수에 포함하지 않는다.
- 실행 그룹 사이 중복 조건을 고유 테스트 총수로 합산하지 않는다.

## 한계와 후속 확인

모든 10~19 원본/배율/배경의 정확도를 증명한 것은 아니다. 얇은 글자의 확인되지 않은
관측은 보류할 수 있다. 이번 변경은 전 구간 숫자 지원이나 100% 표시 지원이 아니다.
Windows 게임 캡처, 혼합 DPI 및 장시간 실사용은 이 Linux 격리 검사의 확인 범위 밖이다.
수정본을 main에 푸시한 뒤 정확한 SHA의 Windows 테스트/네이티브/exe 결과를 확인해야 한다.
API가 Forbidden이면 대기 상태로 보고하며, 이전 펠롬 SHA의 성공으로 대신하지 않는다.
릴리즈/태그는 진행하지 않는다.
