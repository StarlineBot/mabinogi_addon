# 투아림 긴 경로·큰 글꼴 설정 폭 수정

## 근거와 재현

- 근거: `docs/qa/큰글꼴_투어겹침_수정후_독립QA_20261017.md`.
- 원래 투어 겹침은 독립 QA의 동일 12조건과 렌더에서 해결 확인됐다.
  Windows에서는 별도 투아림 가로 폭 검사에서 먼저 실패해 투어 assertion까지 도달하지 않았다.
- 독립 긴 경로 재현은 수정 전 **1 failed, 5 passed (2.70초)**였다.
  미등록/20px 글꼴/긴 Windows 형식 경로에서 viewport 776px, 내용 최소 폭 798px,
  자동찾기 버튼 오른쪽 786px을 확인했다. 원본 QA/기대값/이미지를 바꾸지 않았다.
- Windows 당시 실제 경로/글꼴/치수가 로그에 없으므로 이 Linux 긴 경로 원인과
  Windows 6개 실패의 원인이 완전히 같다고 단정하지 않는다.

## 수정 범위

- 수집 경로 안내만 가로 최소 폭을 강제하지 않도록 한다. 다른 기능/공통 안내 라벨은 바꾸지 않는다.
- Qt `QTextLayout.WrapAtWordBoundaryOrAnywhere`로 공백 없는 경로도 줄바꿈한다.
  실제 표시와 높이 계산은 같은 레이아웃을 사용한다. QLabel의 wordWrap만 쓰면 긴 경로
  일부 글자가 잘리는 후속 렌더도 있어 이 부분까지 확인했다.
- 경로 문자열을 축약하거나 구분자/보이지 않는 문자를 삽입하지 않는다.
  전체 원문은 라벨 텍스트와 툴팁에 보존하며 폴더 열기 대상도 그대로다.
- 글꼴·버튼 크기를 줄이지 않는다. 영역 등록/수집/저장/숫자 판독/알림 동작과 설정 형식은 유지한다.
- 단발 레이아웃/그리기에서만 처리하며 게임 판독 틱이나 별도 polling/timer를 추가하지 않는다.

## Windows 실패 진단

- 기존 투어 행렬의 가로 범위 0 assertion을 제거/완화/skip하지 않는다.
- 명시적으로 선택한 테스트 fixture는 가로 범위를 조회하는 시점의 실제 투아림 치수를 기록한다.
  진단은 테스트에만 적용하며 원래 scrollbar 객체/판정값을 그대로 반환한다.
- 실패 로그의 `TUARIM_WIDTH_DIAGNOSTICS`에는 viewport/내용 크기/최소 폭/가로 범위,
  실제 폰트 family·px, 표시 경로, 버튼/경로 안내의 사각형·최소 폭·폰트가 JSON으로 남는다.
- 긴 경로 회귀는 가로 범위와 별개로 실제 조작 버튼이 viewport 안인지 검사한다.
  가로 범위 > 0만으로 사용자에게 버튼 잘림이 있었다고 확대 해석하지 않는다.

## 검증

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_tuarim_settings_width.py scripts/qa_navigation_tour_layout.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_tuarim_settings_width.py tests/test_tour_layout.py tests/test_navigation.py tests/test_setup.py -q --tb=short
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -m 'not windows_integration'
```

원본 경로 6조건과 투어 12조건을 유지한다. 경로 회귀 6건도 일반 수집에 편입한다.
추가 한글/공백/깊은 경로의 등록/미등록 2건은 각 조작까지 실제 스크롤한 뒤 전체 버튼이
보이는지, 경로 원문/툴팁/heightForWidth 및 각 텍스트 줄 폭/전체 높이를 검증한다.
큰 글꼴 실제 제품 렌더의 `/tmp/tuarim-width-fixed/large-font-tuarim.png`에서 버튼 경계와
경로 줄바꿈도 확인했다.
최종 줄바꿈 구현 후 관련 회귀 **187 passed (59.18초)**.
원본 경로 6조건/투어 12조건도 변경 없이 이 실행에 포함했다.
개별 실행 건수를 고유 총계로 중복 합산하지 않는다.
전체 격리 회귀 **1,355 passed, 5 deselected, 3 warnings (351.77초)**.
5건은 별도 Windows 네이티브 검사이며 경고는 기존 QMouseEvent 사용 경고다.
기존 누수 검사를 유지하고 실패 skip이나 assertion 완화는 추가하지 않았다.

Linux Qt/논리 작업 영역 모사는 실제 Windows 혼합 DPI/장치 변경이 아니다.
Windows 전체 회귀/네이티브 통합/exe 빌드는 정확한 수정 SHA로 다시 확인해야 한다.
API 조회가 차단되면 미확인으로 보고하며 이전 제품 SHA의 성공으로 대신하지 않는다.
미배포 v0.4.82 노트에 추가하며 태그/릴리즈는 실행하지 않는다.
