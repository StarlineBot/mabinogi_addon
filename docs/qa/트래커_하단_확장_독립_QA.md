# 트래커 하단 확장 독립 QA

검증일: 2026-10-16 (한국 시간).
기준 소스: `4aecda1bd40f618ae4d619b618d31ba6a9c7436a`.
커밋 이력은 조회하지 않고 요구사항과 현재 소스, 독립 실행 및 해당 SHA의 Windows 로그로 검증했다.
제품/기존 제품 테스트/기존 독립 재현은 수정하지 않았다. 원격 변경 12개 중 텍스트 10개를
로컬 Git blob과 대조했다. 기존 비교 PNG 2개는 실행에 필요하지 않아 새로 동기화하지 않았으며,
현재 제품 렌더를 직접 실행하여 실제 결과를 확인했다.

## 결론

이번 변경은 버프·디버프 왼쪽 목록 공간 확장이다. 판독기나 알림 상태 머신 변경은 없다.
독립 UI 입력/상태 전환 검증에서 새 사용자 오동작·크래시를 재현하지 못했다.
다만 **Windows 자동 회귀가 신규 작은 화면 테스트에서 실패**하여 네이티브 검사와 exe
빌드는 미실행이다. 현재는 배포 통과가 아니며 릴리즈 명령을 제공하지 않는다.

## Confirmed Bug / P2 / TRACKER-LAYOUT-CI-01

**작은 화면 회귀가 실제 내용 높이 대신 고정 화면 높이로 배치 모드를 강제한다.**

- 요구사항: `docs/tracker-layout-spec.md` 5~6절은 현재 크기/DPI/글꼴/안내의 남는 높이를
  사용하도록 한다. 부족할 때 필수 조작을 화면 밖으로 보내지 않아야 하며, 730 높이에서
  글꼴과 무관하게 무조건 확장을 금지한다는 요구는 없다.
- 발생 조건: 새 `tests/test_tracker_layout.py:129` 테스트에서 작업 영역을 1100×730으로
  설정하고 `:137`에서 항상 `not d._floating_footer`를 기대한다.
- 영향: 정확한 제품 SHA의 Windows 회귀 실패. 네이티브 통합/배포 exe 검증이 건너뛰어진다.
  앱 크래시나 실제 설정 컨트롤 겹침이 확인됐다는 뜻은 아니다.
- 기술적 원인: 테스트는 작업 영역 높이만으로 전환 필요 조건이 성립했다고 가정한다.
  제품 `src/mabinogi_addon/ui/creator_dialogue.py:193`은 현재 뷰포트와 실제 필요 높이를
  비교한다. 글꼴/스타일에 따라 같은 작업 영역에서도 안전한 배치 모드는 달라진다.
- 실제 Windows 재현: [자동 실행 38837676444](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38837676444),
  job `116770337285`. 위 assertion에서 `_floating_footer=True`로 실패했다.
  결과 **1 failed, 868 passed, 1 skipped, 4 deselected, 3 warnings (245.44초)**.
  Native Windows integration / Verify exe build 모두 skipped. summary 성공은 게이트 성공이 아니다.
- 독립 반증 입력: 같은 실제 창/작업 영역에 9/13/18px 글꼴 스타일을 공급했다.
  9px에서는 창 높이 698, floating=True, viewport=590, 세로 스크롤 최대=0이며 오른쪽
  설정 박스와 얼굴 컨테이너가 겹치지 않았다. 13px은 floating=False, viewport=526,
  세로 스크롤 최대=52; 18px은 floating=False, viewport=521, 최대=153이었다.
  세 경우 모두 얼굴은 창 안에 있고 확장 또는 전용 하단 배치를 통해 접근 가능했다.
- 검증 제한: Windows 실패 로그에는 실제 필요 높이/뷰포트 값이 없다. 해당 러너에서
  글꼴 차이만이 원인인지, 배치 이벤트 순서까지 영향을 줬는지는 단정하지 않는다.
  Linux 반증은 고정 730 기대값이 보편적인 사양이 아님을 확인한 것이지 Windows 실측 대체가 아니다.
- 개발 확인 기준: 실패 시 필요 높이/뷰포트/프레임/글꼴 및 실제 겹침을 함께 기록한다.
  실제로 공간이 부족한 조건을 구성해 전용 하단 복귀와 큰 화면 복원을 검증하고, 들어가는
  조건에서는 컨트롤 비겹침/스크롤/얼굴 접근성을 검증한다. 실제 겹침이 있다면 구현을 고친다.
  테스트 삭제/skip, 무조건 통과 assertion, 실제 공간을 무시한 강제 배치로 숨기지 않는다.
  수정 push 후 자동 Windows 회귀/네이티브/exe까지 확인한다. 같은 실패본 수동 실행은 불필요하다.

## 기존 즉시 전환 재현과 실제 UI 상태의 구분

원래 `scripts/qa_creator_dialogue.py`의 `test_click_and_tab_stress_keeps_bounded_timer_and_no_extra_top_level`
하나는 이번 소스에서 실패했다. 원본 Git blob `cc28d1a9e5ad9c14338e91496c43b0c2a7ac8020`을
유지했고 실패를 skip하거나 assertion을 바꾸지 않았다.

- 원본은 탭을 프로그래밍으로 바꾼 직후 Qt 배치 이벤트를 처리하지 않고 대사를 요청한다.
  이번에는 부유 컨테이너에서 전체 폭 전용 하단으로 부모 레이아웃에 재삽입되므로 위치
  확정 전 상태가 생긴다. 첫 파티 탭 직후 footer는 `(714,800,790,64)`, 중앙은 790×864였다.
  화면 밖 얼굴 영역 판정 때문에 요청이 안전하게 거절된다.
- 새 독립 검증으로 120회 전환에서 이벤트 처리 전 거절 40회를 관찰했지만, 각 전환의
  실제 배치 이벤트를 처리한 뒤 요청은 120회 모두 성공했다. 대기열 누적이나 지속적인
  얼굴 접근 불가/잡담 불능을 재현하지 못했다.
- 이 실패를 제품 사용자 버그나 크래시로 단정하지 않는다. 원래 즉시 호출 가정과
  화면에서 조작 가능한 시점을 구분한 것이다. 원본 재현 실패를 전체 통과로 숨기지도 않는다.

## 요구사항과 독립 검증

- TL-01~04: 제품 회귀에서 버프/디버프 왼쪽 목록 +64px, 행 높이/오른쪽 설정 위치와 너비/
  얼굴 위치 유지, 디버프 off/band/percent 및 긴 안내를 확인했다. 제품 실제 렌더의
  buff-normal, debuff-percent, buff-small 이미지도 직접 열어 확인했다.
- TL-05~06: 새 독립 재현에서 두 탭의 아래쪽 목록 자식 hit-test, 실제 Qt 마우스 선택,
  위/아래 버튼 클릭 후 선택 항목과 순서 복원, 휠 이벤트에 따른 목록 스크롤을 실행했다.
  말풍선 닫는 클릭이 뒤에 배치한 버튼을 누르지 않는 것도 확인했다.
- TL-07~10: 비대상 탭의 전용 공간/설정 사진 정책 및 잡담 표시/토글 시 목록 높이 유지는
  제품 회귀와 원래 재현을 교차 확인했다. 독립 검증은 작업 영역/긴 안내/디버프 방식을
  24회 바꾸고 복원해 목록 높이와 선택 보존, 레이아웃 footer 항목 중복 없음, 타이머 3개 유지,
  배치가 안정된 뒤 불필요한 LayoutRequest 재발 없음을 검사했다.
- 이 반복 횟수로 장시간 리소스 누수나 실제 게임 FPS/입력 안정성까지 보장하지 않는다.

## 실행 결과

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest tests/test_tracker_layout.py tests/test_creator_dialogue.py tests/test_setup.py scripts/qa_creator_dialogue.py scripts/qa_tracker_stability.py -q --tb=short
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_tracker_layout.py -q --tb=short -s
PYTHONPATH=src QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 python -m pytest scripts/qa_tracker_layout.py tests/test_tracker_layout.py -q --tb=short
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest -q -m 'not windows_integration' --tb=short
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m scripts.render_creator_dialogue
```

- 집중 회귀: **1 failed, 210 passed (62.42초)**. 실패는 위 원본의 즉시 전환 가정이며,
  새 제품 배치/말풍선/시작 안내 회귀 190개와 나머지 독립 재현 20개는 통과했다.
- 새 독립 UI 검증: **8 passed (6.85초)**.
- 150% Qt 배율 모사: **18 passed (17.95초)**. 새 독립 8개와 제품 배치 10개다.
- 전체 Linux 제품 회귀: **870 passed, 4 deselected, 3 warnings (231.75초)**.
  경고는 기존 toast의 QMouseEvent deprecation. 실제 캡처/오디오/외부 통신은 명시적 경계로
  대체하고 로컬 IPC를 허용했다. Windows 네이티브 4개는 여기에 합산하지 않았다.
- 제품 렌더 종료 0. offscreen의 폰트 캐시/propagateSizeHints 경고는 있었다.
- 독립 스크립트 초안에서는 긴 안내를 넣은 뒤 원래 안내 대신 공백으로 복원하여 목록
  높이를 잘못 비교했다. 원래 안내를 복원하고 QLabel의 양쪽 배치 상태가 처리된 뒤
  반복 비교하도록 바로잡았다. 이 준비 과정의 실패를 제품 결함으로 보고하지 않는다.

사례 수는 실행 간 중복되므로 합산하지 않는다. 실제 Windows 혼합 DPI, 물리 클릭/휠 전달,
창 가림/게임 포커스, 잠금/절전/모니터 변경, 장시간 CPU·메모리·핸들/GDI는 새로 실측하지 않았다.
공개 노트 원시 제목 혼입 `NOTES-QA-01`은 기존 잔여 문제로, 이번 UI 변경이 해결한 것은 아니다.

## 전달 및 배포 판단

레이아웃 자체의 새 사용자 결함은 이번 입력에서 확인하지 못했지만 Windows 게이트는 실패다.
개발 세션에서 위 테스트의 조건 구성과 Windows 실제 치수를 먼저 확인·수정한 뒤 push하고
후속 QA한다. 사용자 설정 초기화나 동일 실패본의 반복 수동 실행으로 해결할 사안이 아니다.
이번 QA는 보고서와 새 독립 스크립트만 공유하며 제품/태그/릴리즈 노트는 바꾸지 않는다.
