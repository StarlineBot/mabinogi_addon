# 크레센도 기본 판독 이미지 수정

- 날짜: 2026-10-16
- 근거: `docs/qa/디버프_원본크롭_및_판독이미지_교체검토.md` 9절,
  `scripts/qa_crescendo_native_mismatch.py`.
- 개발 세션에서 원본 QA 재현을 직접 실행하여 **6 failed, 4 passed**를 확인했다.
  크레센도 새 숫자 5, 전체 보스 ROI, 다른 장면 U04 숫자 2가 off/auto 양쪽에서
  미적용 표시로 남았다. 불협화음 2/5 대조군은 정상이다.

## 원인과 수정

기본 28px 그림을 엔진에서 16px로 축소한 크레센도는 실제 아이콘과 다르다.
새 슬롯과의 점수는 0.325639, 다른 장면 U04는 0.269290으로 시작 임계 0.68 미만이다.
전체 ROI에서는 오히려 불협화음 슬롯의 0.596447이 최고점이었다.

- 크레센도 기본 판독 PNG만 QA의 `music_native_20261016/crescendo.png`로 교체했다.
  원본 `(1079,1214,16,16)` 크롭의 파일 바이트와 픽셀을 그대로 보존한다.
- 이전 기본 PNG는 `assets/debuff/image/크레센도.png`로 옮겨 오버레이와 목록의
  표시 그림을 유지한다. 판독 이미지 슬롯에서는 실제 새 판독용 그림을 보여준다.
- 번들 판독 아이콘에만 번들 표시 그림을 연결한다. 같은 이름의 사용자 아이콘은
  기존대로 판독·표시에 사용한다. 사용자 파일/설정/등록 순서를 변경하지 않는다.
- 다른 기본 아이콘, 엔진 임계값, 확인 시간, 보스 판단 방식은 변경하지 않았다.
- QA 원본 보고서, 비교 이미지, 수치, 재현 스크립트는 수정하지 않았다.

## 검증

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_crescendo_native.py tests/test_debuff_identity.py tests/test_debuff_live_detection.py tests/test_catalog.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_crescendo_native_mismatch.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -m 'not windows_integration'
```

- 수정 후 원본 QA 재현 10건 통과. 새 5/전체 ROI뿐 아니라 다른 장면 2도
  적용으로 확정한다. 불협화음만 있는 2/5 입력에서는 크레센도가 미적용으로 남는다.
- 일반 수집되는 `tests/test_crescendo_native.py`에서도 같은 QA 재현을 실행한다.
  manifest의 11장면에서 이름이 확정된 다른 디버프 88슬롯을 음성 표본으로 검사한다.
  이름 미확정 Uxx를 임의로 음성 표본으로 취급하지 않는다.
- 기존 배경 음성/프라가라흐 식별/영역 경계 회귀를 함께 검증한다.
- 새 판독 PNG 바이트·픽셀, 이전 표시 PNG Git blob, 한글 경로 사용자 override의
  우선순위와 파일 보존을 자동 확인한다.
- 새 원본 자기 자신과의 일치는 정확도 개선 증거로 세지 않는다. 모든 중첩 숫자,
  실제 Windows 게임/DPI/장시간 정확도는 미검증이다.
- Linux 격리 전체 회귀: **1,143 passed, 4 deselected, 3 warnings (229.66초)**.
  4건은 별도 Windows 통합 단계이며 경고 3건은 기존 QMouseEvent 사용 경고다.
- Windows 테스트·exe 빌드 결과는 푸시한 정확한 SHA로 별도 확인한다.
  이 세션의 기존 GitHub API Forbidden 제약이 계속되면 검증 대기로 남기며,
  Linux 통과를 Windows 통과나 후속 독립 QA 통과로 보고하지 않는다.
