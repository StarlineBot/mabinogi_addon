# Windows 큰 글꼴 줄바꿈 수정 독립 QA

- 날짜: 2026-10-18 (Asia/Seoul).
- 검증 제품 SHA: `cc745c690ef675068ae0b989c44d0200ec8b4f9d`.
- 기준: `app-interaction-consistency-review.md` UX-08/10/11/12와
  `INTERACTION-WINDOWS-WIDTH-QA-01`, `CUSTOM-AUTOSAVE-REPLACE-QA-01`.
- 직전 QA `709f914`와 현재 트리만 비교했다. 커밋 이력/메시지는 조회하지 않았다.
- QA는 제품 구현/기존 테스트/원래 실패 재현을 변경하지 않았다.

## 판정

이전 Windows 큰 글꼴 9건의 실패는 원래 assertion을 유지한 정확한 수정 SHA의
Windows 회귀에서 해소됐다. 로컬 독립 반복 검사에서도 추가 폭/조작 결함을 발견하지 않았다.
최초 수정 SHA의 exe 단계는 이미지 데이터 추가 푸시로 취소됐지만, 후속 제품 `8192a70`의
Windows 회귀·네이티브·exe 빌드 성공으로 최종 확인했다.
별도로 추가 제보된 펠롬 실패 증거는 `펠롬_이름판독실패_독립QA_20261018.md`,
그 수정 검증은 `펠롬_수정후_독립QA_20261018.md`에 분리한다.

## 구현과 영향 범위

- `ui/widgets.py`의 새 `wrapping_row`는 Qt QFormLayout.WrapLongRows로 두 조작 그룹을
  묶는다. 실제 최소 폭이 부족할 때 둘째 그룹을 다음 줄로 내린다.
- 보스와 체력바의 영역 행, 체력바 배율/잠금 행과 알림 세 항목에만 연결한다.
  기존 공유 위젯의 동작과 버프/디버프 편집 열, 판독기/추적/알림 엔진은 변경하지 않았다.
- 고정 창 확대, 폰트 축소, 스크롤바 숨김으로 기존 assertion을 우회하지 않는다.
  기존 컨트롤을 레이아웃으로 이동할 뿐 재생성하거나 신호를 중복 연결하지 않는다.
- 새 타이머/스레드/캡처/파일 polling은 없다. 설정 교체 쓰기 중지 수정은 그대로 유지된다.

## 직접 실행

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen INTERACTION_RENDER_DIR=/tmp/qa_width_fix_20261018 python -m pytest tests/test_wrapping_controls.py tests/test_navigation_all_widths.py tests/test_tour_layout.py scripts/qa_custom_autosave_import_reset.py tests/test_boss_tab.py tests/test_stat_bars_stability.py tests/test_stat_visibility.py tests/test_stat_shake.py tests/test_resource_integration.py -q --tb=short
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest docs/qa/assets/wrapping_20261018/probe.py tests/test_release_notes.py tests/test_release_notes_trigger.py -q --tb=short
```

- 관련 회귀: **134 passed (37.52초)**. 원래 폭/투어 assertion, 설정 교체 독립 10조건,
  보스/체력바 출력·안정성·흔들림, 도르카·투아림 독립 조합을 포함한다.
- 새 개발 폭 검사 2조건은 위 묶음에도 들어 있으며 단독 실행 **2 passed (1.59초)**다.
  20px/버튼 최소 174px/넓은 알림 입력에서 실제 줄바꿈과 모든 입력의 접근, 원래 글꼴 복귀를 확인한다.
- 별도 독립 반복 검사와 노트 관련 실행: **14 passed (4.84초)**.
  독립 2조건은 보스/체력바 각각 20회 글꼴·최소 폭을 왕복하며 모든 보이는 버튼/입력/콤보의
  기하 겹침 없음, 영역 명령 접근, 동일 컨트롤/타이머/최상위 창 유지와 설정 파일 바이트 불변을 검사한다.
- 반복 회차를 별도 테스트 수로 더하거나 위 실행을 고유 총계로 합산하지 않는다.
- 실제 생성한 `boss-windows-width.png`, `stat_bars-windows-width.png`를 직접 확인했다.
  버튼 그룹의 줄바꿈과 세로 스크롤 접근을 확인했으며 Linux에서 최소 폭을 주입한 렌더다.
  실제 Windows 혼합 DPI/실게임 화면으로 표현하지 않는다.

## Windows 실행 증거

[자동 Windows 실행 39043606712](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39043606712),
job `117427837440`, 제품 SHA `cc745c6`의 실제 단계별 결과:

- 격리 회귀: **1501 passed, 1 skipped, 9 deselected (644.64초)**.
  이전의 화면 폭/큰 글꼴 실패 9개도 기존 assertion으로 통과했다.
- 네이티브 Windows 통합: **9 passed, 1502 deselected (30.82초)**.
- exe 빌드: 실행 중 데이터 추가 푸시 `cd1c563`으로 **cancelled**.
  테스트 실패나 확인된 exe 빌드 결함이 아니며, 성공으로 대체하지도 않는다.
- 최종 후속 제품 `8192a70`의 [자동 실행 39046804737](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39046804737)은
  격리 회귀 **1528 passed, 1 skipped, 9 deselected**, 네이티브 **9 passed**,
  exe **success**다. 기존 폭 assertion을 포함한 실제 Windows 결과로 완료를 확인했다.
  사용자가 수동 실행할 필요는 없었다.

## 릴리즈 노트

원격 v0.4.83은 `ec4a903`에 이미 존재한다. 이번 변경을 같은 버전으로 다시 태그하지 않는다.
후속 개발에서 미출시 조작 정리/자동 저장/설정 교체/폭/계산 상태 설명과 펠롬 수정 설명을
v0.4.84로 분리했다. 이미 게시된 v0.4.83 및 과거 노트는 게시 당시 내용 그대로 보존됨을 확인했다.
QA에서는 제품 노트를 추가 수정하거나 태그를 생성하지 않았다.

## 한계

실게임/혼합 DPI/Windows 절전·RDP/장시간 리소스 계측과 exe 직접 실행은 이번에 수행하지 않았다.
작은 작업 영역을 모사한 Qt 기하 검사를 실제 작은 모니터 전체 통과로 표현하지 않는다.
기존 실패 assertion/입력을 유지한 Windows 실행을 Linux 통과나 과거 SHA 성공으로 대신하지 않는다.
