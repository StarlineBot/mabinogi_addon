# 보스 3차 탭 중첩 스크롤 회귀 보완

## 원인과 범위

- 대상 QA: [기본 공개·헤일로 수집 독립 QA](qa/기본공개_헤일로수집_독립QA_20261019.md).
- QA 원격 `28173a6`에서 기존 재현 스크립트를 실행해 밝음/어두움 20px 화면 검사와 보스 너비 모사 검사의 **3개 실패**를 재현했다.
- 제품 조작 장애가 아니라 단일 스크롤을 전제한 회귀 검사 문제다. 제품 코드·권한·설정·공개 노트·릴리즈 워크플로는 변경하지 않았다.

## 수정

- `test_support/scroll_visibility.py`는 컨트롤의 모든 조상 `QScrollArea`를 안쪽부터 이동한 뒤 모든 뷰포트에서 가로 스크롤 없음과 컨트롤 전체 사각형 포함을 검사한다.
- `test_interaction_polish.py`, `test_wrapping_controls.py`의 잘못된 단일 스크롤 가정을 수정하고, 이미 가장 가까운 스크롤을 찾던 `test_navigation_all_widths.py`도 모든 조상을 검사하도록 강화했다.
- 원래 글꼴 크기·Windows 버튼 최소 폭·줄 복원·타이머 수·설정 불변 assertion은 유지한다. skip이나 실패 assertion 삭제로 통과시키지 않는다.
- `test_scroll_visibility.py`는 안쪽/바깥쪽 모두 스크롤이 필요한 실제 Qt 계층을 만들고 정상 도달을 검증한다. 바깥 스크롤 이동을 막으면 assertion이 실패하는 것도 검사해 내부만 보는 거짓 통과를 방지한다.
- 기존 QA 보고서·실패 재현 스크립트·독립 probe는 수정하지 않았다.

## 실행

- 수정 전 `scripts/qa_boss_nested_scroll_20261019.py`: **3 failed in 5.79s**.
- 수정 후 재현 스크립트 및 세 화면 검사 파일: **21 passed in 26.81s**.
- 독립 QA probe와 새 조상 스크롤 검사: **10 passed in 8.17s**.
- 위 실행은 Linux Qt offscreen이며 캡처·오디오·네트워크는 기존 테스트 경계에서 대체한다. 기존 QThread 누수 검사를 유지한다.
- Windows 네이티브·exe·실게임·혼합 DPI·장시간 실행은 미검증이다. 일반 푸시의 Windows Actions·태그·릴리즈는 실행하지 않는다. 수정 후 독립 QA 통과를 대신 주장하지 않는다.

## 전체 관련 실행 중 확인한 대기 헬퍼

- QA의 두 파일 묶음을 합치고 새 스크롤 검사를 추가한 실행은 **561 passed, 2 failed in 417.47s**였다. 원래 중첩 스크롤 3개 실패는 없었고, 도르카 추적 2개가 공용 `drain()`의 5초 워커 종료 검사에서 실패했다.
- 이 헬퍼는 `QTest.qWait(10)`와 `processEvents()`를 반복했다. 같은 파일의 기존 재현 경로에는 Python 워커가 이 바인딩의 qWait에서 GIL을 얻지 못할 수 있다는 이유로 실제 `QEventLoop`를 사용하던 경로가 이미 있었다.
- 공용 `drain()`도 실제 Qt 이벤트 루프로 기다리도록 맞췄다. **5초 제한과 워커가 없어야 한다는 assertion은 유지했다.** 제품 워커·알림·수집 코드에는 손대지 않았다.
- qWait 호출을 실패로 대체한 상태에서도 실제 워커 완료와 판독값을 확인하는 회귀를 추가했다. 기존 실패 결과를 최종 통과 개수에 합산하지 않는다.
- 보완 후 추적·게임 문맥·시작 복구·새 스크롤 검사: **52 passed in 42.53s**. 이어서 새 워커 대기 회귀와 원래 중첩 스크롤 재현을 함께 검사해 **56 passed in 31.64s**를 확인했다(중복 결과다).
- 전체 563개 묶음을 보완 후 다시 전부 실행하지는 않았다. 제품 소스와 다른 검사 경로가 동일한 범위의 기존 561개 통과 결과는 재사용하고, 변경된 대기 헬퍼와 실패 두 건은 위 영향 범위 재실행으로 확인했다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dorcha_tracking.py tests/test_dorcha_roi_context.py tests/test_dorcha_startup_recovery.py tests/test_scroll_visibility.py scripts/qa_boss_nested_scroll_20261019.py -q --tb=short --show-capture=no
```
