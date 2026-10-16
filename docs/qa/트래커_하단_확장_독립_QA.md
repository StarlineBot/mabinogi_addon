# 트래커 하단 확장 독립 QA

검증일: 2026-10-16 (한국 시간).
기준 소스: `4aecda1bd40f618ae4d619b618d31ba6a9c7436a`.
커밋 이력은 조회하지 않고 요구사항과 현재 소스, 독립 실행 및 해당 SHA의 Windows 로그로 검증했다.
제품/기존 제품 테스트/기존 독립 재현은 수정하지 않았다. 원격 변경 12개 중 텍스트 10개를
로컬 Git blob과 대조했다. 기존 비교 PNG 2개는 실행에 필요하지 않아 새로 동기화하지 않았으며,
현재 제품 렌더를 직접 실행하여 실제 결과를 확인했다.

## 2026-10-16 폭 부족 세로 배치 수정 후속 QA

후속 기준: `a3adbd0560b33972ae67e63e4c33f37473ac84e2`.
직전 QA `ba48380` 대비 제품 배치/공유 세로 스크롤/테스트/명세·개발 기록/렌더·노트
10개 파일을 확인했다. 과거 실패 증거는 아래에 보존하며 최신 판단은 이 절을 따른다.

- 제품 수정: 버프·디버프에만 `TrackerColumns`를 적용해 실제 두 열 최소 폭이 부족할 때
  목록 아래에 같은 설정 위젯을 배치한다. 고정 창 폭 790과 글꼴/컨트롤 크기를 줄이지 않는다.
  들어가는 경우 기존 두 열 배치를 사용하고, 세로 배치에서는 전용 제작자 하단 공간을 쓴다.
- `_VScroll`은 해당 두 탭의 resize/LayoutRequest에서 폭 배치를 먼저 맞추고 기존
  heightForWidth 높이 제한을 적용한다. 다른 탭에 새 폭 전환을 적용하지 않는 가드도 확인했다.
- 명세 5절에 폭 부족 때만 세로 배치한다는 예외가 추가됐다. 개발 기록의 사용자 승인과
  갱신된 명세를 확인했으며, QA가 기본 오른쪽 설정 위치 요구를 임의로 폐기하지 않았다.
- 기존 18px/실제 가로 경계/visibleRegion 진단/강제 잘림 역검증은 유지됐다.
  큰 작업 영역 복원 시에도 폭이 부족하면 세로 배치를 유지하는 기대값 변경은 새 명세와 맞다.
- Linux 집중 검증 **232 passed (52.68초)**: 제품 배치/말풍선/시작 안내/CI 계획과 원래
  독립 입력·가로 경계 검사를 함께 실행했다. 518+404 최소 폭의 두 탭 반복 전환/복원,
  세로 스크롤로 설정 접근, 기본 행 높이와 목록/선택 복원을 포함한다.
- 150% Qt 배율 모사 **32 passed (16.17초)**: 제품 배치 21개와 원래 독립 입력/가로 경계
  11개다. 독립 스크립트는 수정하지 않았고 QA가 제품/제품 테스트를 고치지 않았다.
- 제품 렌더 명령 종료 0. buff/debuff-stacked-settings와 buff-normal 이미지를 직접 열어
  설정 컨트롤 접근과 기본 배치를 확인했다. 이는 Linux에서 폭 부족을 모사한 렌더이며
  실제 Windows 캡처를 보았다는 뜻은 아니다.

### 최신 최종 결과

- 전체 Linux 제품 회귀 **884 passed, 4 deselected, 3 warnings (167.39초)**.
  경고는 기존 toast의 QMouseEvent deprecation이며 별도 네이티브 4개는 여기에 합산하지 않는다.
  실제 캡처/오디오/외부 통신은 테스트 경계로 대체했고 로컬 IPC를 허용했다.
- [정확한 수정 SHA의 Windows 실행 38844583780](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38844583780),
  job `116792089304`: **1 failed, 882 passed, 1 skipped, 4 deselected, 3 warnings
  (272.08초)**. 이전 실제 잘림 3개 사례의 컨트롤 경계 검사는 모두 통과했다.
  `TRACKER-LAYOUT-WINDOWS-01`의 해당 Windows 18px 재현은 해결 확인했다.
- 네이티브/exe는 새 테스트 실패로 skipped다. 전체 Windows 게이트 통과나 빌드 완료는 아니다.
  원격 최신 태그 `v0.4.72`와 앱 내 노트 상단 `v0.4.73`은 확인했다. 태그는 생성하지 않았다.

### Confirmed Bug / P2 / TRACKER-LAYOUT-CI-03

**폭 때문에 세로 배치한 경우에 높이도 반드시 넘칠 것으로 가정한다.**

- 발생 조건: `tests/test_tracker_layout.py:260`의
  `test_overwide_columns_stack_and_restore_without_clipping[1]`이다. 디버프의 두 열 최소 폭을
  518+404로 늘려 세로 배치를 만든 뒤 `:283`에서 무조건 세로 스크롤 maximum > 0을 기대한다.
- 사용자 영향: Windows 검증 게이트 실패로 네이티브와 exe 빌드가 미실행된다. 이 실패는
  앱 크래시나 이전 가로 설정 잘림의 재발이 아니다.
- 원인: 폭 부족은 세로 배치의 조건이지만 높이 초과의 충분조건은 아니다. 해당 테스트는
  이 지점에서 실제 필요 높이 > viewport라는 선행 조건을 구성하거나 확인하지 않는다.
  내용이 모두 들어가면 스크롤 없이 접근 가능한 것이 정상일 수 있다.
- 실제 결과: Windows에서 세로 배치, 전용 하단 복귀, inner 폭=viewport 폭 검사는 통과한 뒤
  `maximum == 0`에서 `0 > 0` assertion이 실패했다. 같은 소스의 버프 `[0]`는 통과했다.
  로그에는 그 지점의 필요 높이와 모든 컨트롤의 세로 가시성 값이 없어, Windows의 0이
  정상적인 내용 수용인지 세로 높이 계산 오류까지 있는지 마지막 접근성 확인은 남아 있다.
- 재현: 위 자동 실행 로그를 확인했고 Windows에서 아래 명령으로 해당 테스트를 실행한다.

```bash
uv run pytest tests/test_tracker_layout.py -q -k overwide_columns_stack_and_restore_without_clipping
```

- 독립 보강: `scripts/qa_tracker_stack_visibility.py`는 같은 폭 부족을 두 탭에 공급하고,
  각 실제 설정 컨트롤까지 스크롤해 뷰포트 안에 완전히 들어가는지 확인한다. 80줄 안내를
  추가한 경우는 실제 높이 초과와 스크롤을 먼저 확인하고, 안내 복원과 폭 제약 해제 후
  원래 배치 복원도 검사한다. **2 passed (2.11초)**이며 제품/기존 테스트는 수정하지 않았다.
- Linux 측정: 9px 모사에서 버프 필요 높이/viewport는 879/692, 디버프 710/692였다.
  긴 안내에서는 각각 1759/692, 1590/692로 스크롤이 필요했고 각 컨트롤에 접근 가능했다.
  이 환경은 정상 안내에서도 스크롤이 생겼으므로 Windows의 maximum=0을 직접 재현했다고
  주장하지 않는다. Windows에서는 모든 폼이 보이는지 또는 필요 높이가 잘못 잡혔는지 확인해야 한다.
  같은 독립 검사의 150% Qt 배율 실행도 **2 passed (2.24초)**였다.
- 수정 확인 기준: 같은 테스트에서 가로 부족/필요 높이/viewport/컨트롤 세로 경계를 기록한다.
  내용이 들어가면 스크롤 0과 모든 컨트롤 가시성을 확인하고, 넘치면 스크롤 이동으로 각
  필수 조작에 접근 가능한지 확인한다. 높이 초과 분기는 긴 안내나 작은 viewport로 조건을
  명시적으로 구성해 반드시 실행한다. 단순 assertion 삭제/skip으로 통과시키지 않는다.
  복원/선택/행 높이/가로 경계/타이머 검사도 유지한다.

레이아웃 회귀에서 '작은 화면이면 반드시 특정 모드', '가로 범위가 남으면 반드시 컨트롤
잘림', '세로 배치이면 반드시 세로 넘침'을 같은 사실로 취급하지 않는다. 각 조건을 실제
측정값과 접근성으로 검증해야 플랫폼/글꼴 차이를 반복적인 CI 실패로 만들지 않을 수 있다.

최신 결론: 기존 실제 가로 잘림은 해결 확인했지만 Windows 새 테스트 1건이 실패하여
릴리즈 보류다. 수동 재실행은 불필요하며 개발에서 조건 구성과 세로 가시성 검사를 수정한 뒤
자동 Windows 회귀/네이티브/exe를 확인한다. 이번 QA는 문서와 새 독립 보강 검사만 반영한다.

---

## 2026-10-16 실제 가로 경계 검사 후속 QA

최신 후속 기준: `8c5cb90671f1dc46de9eab81cd98c3f77dbb9eda`.
직전 QA 반영본 `ed5b5dd` 대비 변경은 테스트/CI 계획/개발 지침·문서 6개다.
제품 소스와 기존 독립 재현은 그대로이며 변경 파일 6개의 Git blob을 대조했다.
아래 과거 검증의 추정/미확인 상태는 당시 증거로 보존한다. 최신 판단은 이 절을 따른다.

### Confirmed Bug / P2 / TRACKER-LAYOUT-WINDOWS-01

**Windows 18px 글꼴·작은 작업 영역에서 버프/디버프 오른쪽 설정이 실제로 잘린다.**

이전에 Potential Risk였던 같은 항목을 실제 실행 좌표와 visibleRegion으로 확정했다.
이번에는 내부 가로 range가 양수라는 사실만으로 결론 내린 것이 아니다.

- 요구사항: `docs/tracker-layout-spec.md` TL-08 및 5절은 글꼴/작은 작업 영역 변화에서도
  필수 조작을 화면 밖으로 보내지 않도록 한다. 스크롤바를 단순히 숨기는 것은 해결이 아니다.
- 발생 조건: 실제 Windows CI의 Qt offscreen, 본창 폭 790, 작업 영역 1100×730,
  `QWidget {font-size:18px;}` 입력이다. 버프의 긴 안내뿐 아니라 일반 작은 화면 사례와
  디버프 사례에서도 실패한다. 기본 배포 글꼴의 모든 사용자에게 발생한다고 주장하지 않는다.
- 사용자 영향: 해당 조건에서 이름 입력칸 일부와 아이콘 관련 버튼/체크 항목 등이
  오른쪽으로 잘린다. 버튼 전체가 뷰포트 밖에 있는 경우는 마우스로 접근할 수 없다.
  실제 게임 판독 중단/크래시/사용자 설정 손상이 확인된 문제는 아니다.
- 기술적 원인: 내용의 최소 필요 폭이 실제 뷰포트보다 커져도 본창은 790 고정 폭이고,
  `_scrolled`는 가로 스크롤을 AlwaysOff로 숨긴다. `CreatorDialogue._can_expand`는
  높이만 검증하며, 전용 하단으로 복귀한 버프에서도 가로 초과 자체는 해소되지 않는다.
  따라서 부유 얼굴만 끄거나 가로 range assertion을 없애는 것으로 해결되지 않는다.
- 실제 재현: [Windows 실행 38841214020](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38841214020),
  job `116781491639`. 수정된 검사는 각 컨트롤의 뷰포트 상대 좌표와 실제 visibleRegion을
  기록한다. 검사 구현을 읽고 좌표계/범위 비교와 강제 잘림 역검증도 확인했다.
- 버프 긴 안내 사례: inner=946, viewport=776, range=170. 이름 QLineEdit은
  `(568,145,354,27)`인데 실제 보이는 폭은 **208**이다. 버튼 하나는
  `(818,211,104,26)`으로 뷰포트 오른쪽 밖이며 visibleRegion은 **(0,0,0,0)**이다.
  이 버튼은 y=211로 세로 가시 범위 안에 있어 단순 세로 스크롤 아래에 있는 상태와 다르다.
- 디버프 일반 작은 화면 사례: inner=1012, viewport=790, range=222. 입력칸은
  `(586,145,402,27)` 중 폭 **204**만 보인다. 버튼 `(818,211,104,26)` 역시 표시 영역 0.
  이때 floating=True였지만, 버프의 floating=False 실패도 있어 한 모드만의 문제는 아니다.
- 실패 3개는 `test_small_buff_uses_reserved_footer_and_restores_without_drift[18]`,
  `test_small_area_layout_is_safe_for_measured_content[0-18]`, 같은 테스트 `[1-18]`이다.
  서로 다른 제품 버그 3개로 부풀리지 않고 같은 가로 적응 문제의 세 재현으로 취급한다.
- 검증 결과: **3 failed, 878 passed, 1 skipped, 4 deselected, 3 warnings (197.97초)**.
  네이티브 통합과 exe 빌드는 skipped. 테스트 임시 폴더의 PNG 저장 성공도 로그에 있으나
  해당 Windows 임시 파일을 여기서 열어 본 것은 아니다. 위 결론은 실제 위젯 경계 증거다.
- 관련 코드: `src/mabinogi_addon/ui/main_window.py:91`의 가로 스크롤 정책 및 `:226`의
  본창 고정 폭, `ui/creator_dialogue.py:193`의 높이 판정,
  `ui/buff_tab.py:493`, `ui/debuff_tab.py:560`의 오른쪽 폼 배치.
- 재현 명령: Windows에서 아래 명령으로 일반 작은 화면 두 탭과 긴 안내를 함께 실행한다.

```bash
uv run pytest tests/test_tracker_layout.py -q -k 'small_buff_uses_reserved_footer_and_restores_without_drift or small_area_layout_is_safe_for_measured_content'
```

수정 확인 기준은 18px 사례를 유지하면서 실제 컨트롤이 모두 가로로 들어가는 것이다.
기본 글꼴의 승인된 배치와 목록/얼굴 위치도 회귀 확인한다. 테스트의 경계 assertion을
삭제하거나 18px을 skip/축소해 통과시키지 않는다. 고정 폭·배치 요구와 충돌하는 변경이
필요하면 요구를 먼저 협의하며 QA가 제품을 임의 수정하지 않는다.

### 이번에 확인한 개선과 실행 범위

- 실제 오른쪽 버튼·입력·체크·콤보·수치 컨트롤 경계를 검사하도록 테스트가 강화됐다.
  숨은 스크롤바의 정책만 확인하지 않는다. 입력칸을 강제로 밖으로 옮기는 역검증이
  assertion 실패와 진단 PNG 생성을 확인한다. Windows 실패는 이 유효한 검사가 잡은 것이며
  단순 잘못된 테스트라고 다시 단정하지 않는다.
- CI 계획은 `tests/`, `scripts/`, `pytest.ini` 변경도 exe 빌드 대상으로 포함한다.
  관련 단위 테스트와 지침을 대조했다. 다음 수정 push에서 테스트가 통과하면 빌드까지
  자동 진행되므로, 이전 공백을 이유로 수동 실행을 다시 요청할 필요가 없다.
  이번 실행은 테스트가 실제로 실패했으므로 후속 빌드가 건너뛰어진 것이 맞다.
- Linux 집중 실행 **50 passed (15.46초)**:
  `tests/test_tracker_layout.py`, `tests/test_windows_ci.py`,
  `scripts/qa_tracker_layout.py`, `scripts/qa_tracker_horizontal_extent.py`.
- 150% Qt 배율 모사 **30 passed (14.31초)**: 위 집합 중 CI 계획 테스트만 제외했다.
  기존 독립 재현은 수정하지 않았다. Linux 통과로 Windows 실패를 덮지 않는다.
- 제품이 직전과 동일하여 기존 전체 Linux 제품/렌더 검증을 재사용했다. 이번 턴에 전체
  Linux 회귀를 새로 실행하거나 실제 Windows 게임/혼합 DPI/기본 배포 글꼴을 실측하지 않았다.

### 최신 배포 판단

제품 배치의 확정 결함과 정확한 SHA의 Windows 회귀 실패가 남아 있어 릴리즈 보류다.
QA는 이 문서만 갱신하고 제품/테스트/워크플로/릴리즈 노트/태그는 바꾸지 않는다.
개발 세션은 위 실제 잘림을 수정한 뒤 push하고 자동 Windows 회귀·네이티브·exe 결과를
확인해야 한다. 사용자 설정 초기화나 같은 실패본의 수동 재실행은 필요하지 않다.

---

## 2026-10-16 테스트 수정 후속 QA

후속 기준: `61a28a97ee26a6b0bbf410c3e6a55314904b897d`.
이전 QA 반영본 `c549222` 대비 변경은 제품 배치 테스트와 개발 기록 2개뿐이다.
제품 전체/기존 독립 QA/릴리즈 노트는 같은 Git blob이며, 아래 최초 증거를 보존한다.

- `TRACKER-LAYOUT-CI-01`의 조건 구성 수정 확인. 9/13/18px 각각에서 실제 내용이
  뷰포트보다 크다는 선행 assertion 후 전용 하단 복귀/얼굴 분리/목록 높이 정확한 복원을
  4회 반복한다. 고정 730 높이만으로 모드를 단정하지 않는다.
- 추가 6개는 두 탭×세 글꼴에서 실제로 들어가는 경우와 부족한 경우의 안전성을 확인한다.
  확장 시 스크롤 불필요와 설정/얼굴 비겹침, 비확장 시 페이지/하단 분리를 검사한다.
  실패 진단에는 필요 높이/뷰포트/프레임/글꼴/하단 좌표가 포함됐다.
- 기존 반복·복원·행 높이·선택·클릭 통과·타이머/워커 검사와 대용량 입력을 삭제하거나
  skip하지 않았다. 새 사례는 실제 가로 스크롤 정책/비표시를 검사하고 기존 사례의
  가로 범위 0 assertion도 유지했다.
- 원래 `scripts/qa_tracker_layout.py` 8개와 수정된 제품 배치 18개를 실행하여
  **26 passed (22.76초)**, `QT_SCALE_FACTOR=1.5`에서 **26 passed (30.99초)**.
  QA 스크립트의 Git blob `dc78e182d79d4a605deee1156b46d2ccd139c53e`는 변경하지 않았다.
- 이전 소스와 제품이 동일하므로 기존 Linux 전체 **870 passed** 결과와 실제 제품 렌더/
  입력 검증을 재사용했다. 이번 턴에서 전체 Linux 회귀를 다시 실행했다고 주장하지 않는다.
  원래 즉시 탭 전환 재현의 이벤트 처리 전 실패와 처리 후 정상의 구분도 유지한다.

### 후속 Windows 및 배포 상태

- 정확한 수정 SHA의 [자동 실행 38839364387](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38839364387),
  job `116775647804`는 **failure**다. 격리 회귀 **1 failed, 876 passed, 1 skipped,
  4 deselected, 3 warnings (226.43초)**. 이전 모드 전환 assertion은 통과했지만 18px
  사례의 다른 가로 범위 assertion에서 실패했다. 네이티브/exe는 skipped다.
- 앞선 제품 변경 `4aecda1`은 회귀 실패로 exe 빌드를 실행하지 못했다. 이번 변경은 테스트
  전용이어서 `scripts/windows_ci.py:13`의 계획상 새 exe 빌드가 생략된다. 테스트 통과와
  빌드 검증 완료는 별개이며 v0.4.72의 다른 제품 소스 빌드로 대체할 수 없다.
- 새 실행 시작 도구가 없어 누락된 exe 확인용 `release` 수동 검증을 처음 요청했으나,
  위 새 회귀 실패를 확인한 직후 요청을 철회했다. 현재 실패본을 수동 재실행할 필요는 없다.
  먼저 실패의 실제 가로 치수를 확인하고 수정해야 한다.
- 이어 확인한 [수동 release 실행 38840035105](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38840035105)는
  같은 수정 SHA `61a28a9`, job `116777779766`에서 **1 failed, 876 passed, 1 skipped,
  4 deselected, 3 warnings (256.71초)**였다. 동일한 `[18]` 사례가 `170 == 0`에서 실패했다.
  네이티브/exe는 skipped이며 태그가 아닌 수동 실행으로 Release도 게시되지 않았다.
  자동/수동에서 같은 실패가 확인됐으므로 추가 실행 요청 없이 개발 수정으로 넘긴다.
- 이전 제품 빌드 미완료를 다음 테스트 전용 push의 빌드 계획이 이어받지 못하는 점은
  향후 CI 자동화 개선 검토 대상이다. QA가 워크플로나 제품을 임의 수정하지 않는다.
- 원격 최신 태그 `v0.4.72`, 앱 노트 상단 `v0.4.73` 확인. 새 태그는 만들지 않았다.
  Windows 검사와 누락된 exe 빌드 확인 전에는 릴리즈 명령을 제공하지 않는다.

### Confirmed Bug / P2 / TRACKER-LAYOUT-CI-02

**추가된 Windows 18px 사례에서 가로 범위 0 검증이 실패하여 게이트가 중단된다.**

- 발생 조건: `test_small_buff_uses_reserved_footer_and_restores_without_drift[18]`의
  18px 스타일, 80줄 상태 안내 및 1100×730 작업 영역 조합이다.
- 사용자 영향: 배포 검증이 중단되고 네이티브/exe 검증이 실행되지 않는다. 이것만으로
  실제 배포 앱의 기본 글꼴에서 컨트롤이 잘리거나 크래시한다고 확정하지 않는다.
- 확인된 기술 경로: `tests/test_tracker_layout.py:154`의 공간 부족 및 `:155`의
  전용 하단 복귀 검사는 통과한다. `:160`에서 가로 스크롤 maximum이 **170**으로 나와
  `== 0` assertion이 실패한다. 이전 730px 고정 모드 오류와 다른 실패다.
- 재현: 해당 SHA의 Windows에서 `pytest tests/test_tracker_layout.py -q -k
  small_buff_uses_reserved_footer_and_restores_without_drift` 실행. 실패본 자동 run의
  traceback과 단계별 skipped를 직접 확인했다. QA가 기존 테스트를 수정/skip하지 않았다.
- 독립 추가 확인: 실제 컨트롤의 가로 경계를 측정하는
  `scripts/qa_tracker_horizontal_extent.py`를 추가했다. 18px+같은 긴 안내+작은 영역에
  세 글꼴을 공급한 Linux 실행 **3 passed (3.00초)**. DejaVu Sans는
  inner/viewport=778/776, range=2; Noto Sans CJK KR은 776/776, range=0;
  Noto Serif CJK KR은 798/776, range=22였지만 오른쪽 버튼·입력·체크·콤보·수치 컨트롤은
  모두 가로로 들어갔다. 따라서 range 하나만으로 실제 컨트롤 잘림을 확정할 수 없다.
- 검증 제한: 위 Linux 결과가 Windows의 170px 상태도 안전하다는 뜻은 아니다.
  Windows 로그에는 실제 inner/viewport 및 컨트롤 경계가 없어, 불필요하게 강한
  assertion인지 실제 레이아웃 결함까지 있는지 아직 확정하지 못했다.
- 개발 확인 기준: 실패 지점에 inner/viewport/range/value와 각 필수 컨트롤의 가로 경계,
  visibleRegion/스크린샷을 남긴다. 입력이 잘리면 구현을 수정하고, 정상 입력이 모두
  들어가는데 내부 범위만 남는 경우에만 사용자에게 의미 있는 안전성 검사로 정한다.
  `AlwaysOff` 또는 스크롤바 비표시만 확인하고 통과시키지 않는다. 숨긴 바는 잘림을 고치지 않는다.

### Potential Risk / P2 / TRACKER-LAYOUT-WINDOWS-01

**가로 스크롤을 숨긴 고정 폭 창에서 Windows 큰 글꼴 입력이 잘릴 가능성.**

- 조건/영향: 위 Windows 조건의 가로 초과가 실제 폼까지 이어지면 오른쪽 설정 일부가
  잘려 접근하지 못할 수 있다. 기본 배포 글꼴에서도 발생하는지는 확인하지 못했다.
- 근거/위치: `ui/main_window.py:91`의 AlwaysOff 정책과 같은 파일 `:226`의 고정 폭 790,
  새 테스트 `tests/test_tracker_layout.py:160`의 170px 가로 초과.
- 재현/검증: 위 실패 조건에 실제 자식 컨트롤 좌표 검사를 추가한다. Linux 세 글꼴에서는
  가로 컨트롤 잘림이 없었다. 실제 Windows 경계/렌더 자료가 없어 확정 제품 버그로 분류하지 않는다.

후속 결론: 원래 고정 높이의 모드 가정은 바로잡았고 독립 UI 재현은 유지 통과한다.
하지만 Windows 전체 게이트는 여전히 실패한다. 두 번째 실패를 단순 skip/삭제하지 말고
실제 컨트롤 치수를 확인한 뒤 수정 push와 자동 Windows/누락된 빌드 후속 QA가 필요하다.

---

## 최초 QA 결론

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
