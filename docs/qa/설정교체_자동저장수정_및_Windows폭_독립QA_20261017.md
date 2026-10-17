# 설정 교체 자동 저장 수정 및 Windows 화면 폭 독립 QA

- 날짜: 2026-10-17 (Asia/Seoul).
- 검증 SHA: `cc511d36a62ce8e0f1e01770fe7438d175002cf7`.
- 요구사항: `app-interaction-consistency-review.md` UX-08/10/15와 원래 설정 교체 재현.
- 현재 트리와 직전 QA `17ce3ae`의 파일 비교만 사용했다. 커밋 이력/메시지는 조회하지 않았다.
- QA는 제품/기존 테스트/원래 재현을 수정하지 않았다.

## 결론

**설정 덮어쓰기 P1은 수정 확인했다. 릴리즈는 별도 Windows 화면 폭 실패 때문에 보류한다.**
Windows 격리 회귀가 9개 assertion 실패로 끝났고 네이티브 통합·exe 빌드는 실행되지 않았다.
크래시나 권한/API 오류로 실패한 것이 아니다. 이 9건을 별도의 9개 제품 버그로 세지 않는다.

## 수정 확인: CUSTOM-AUTOSAVE-REPLACE-QA-01

- `ui/main_window.py:1703`에서 가져오기/초기화 성공 신호를 받은 커스텀 인스턴스의 쓰기를 중지한다.
- `ui/custom_overlay_tab.py:629`는 타이머/dirty/활성 대상 연결을 정리하고 편집 및 미러를 중지한다.
  `:480`의 종료 flush도 중지된 세션에서는 파일을 쓰지 않는다.
- Save As 대화상자 뒤, 직접 재시도, 늦은 영역 선택, 프리셋·시작 대상·호환 캡처 저장에서도
  같은 중지 상태를 검사한다. 성공한 설정 교체만 이전 편집을 대체하며 취소/실패는 기존 편집을 유지한다.

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_custom_autosave_import_reset.py -q --tb=short
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_custom_autosave_import_reset.py tests/test_custom_config_replacement.py tests/test_custom_autosave.py tests/test_interaction_consistency.py tests/test_settings_preserve.py tests/test_config_bundle.py tests/test_main_shutdown.py -q --tb=short
```

- 원래 재현은 **10 passed (5.34초)**로 기대값/입력을 바꾸지 않고 모두 통과했다. JSON 다른 이름/동일 이름, ZIP 동일 이름,
  초기화와 예약 저장/저장 실패 후 종료를 포함한다.
- 관련 묶음: **69 passed (22.87초)**. 원래 10조건과 이를 일반 회귀에 편입한 10조건이
  중복되므로 고유 테스트 수로 합산하지 않는다. 대화상자 중 교체, 교체 실패/취소,
  반복 자동 저장과 정상 종료, 파일 바이트 보존·오류 복구 검사도 포함한다.
- 실제 Windows 로그에서도 `tests/test_custom_config_replacement.py`의 원래 10조건 및
  추가 8조건이 전부 **PASSED**다. Linux 통과만으로 Windows 수정 확인을 대신하지 않았다.

## Confirmed Bug: INTERACTION-WINDOWS-WIDTH-QA-01

- 심각도: **P2**. 전체 검증 기준 미충족으로 이번 릴리즈는 보류한다.
- 발생 조건: Windows CI의 Qt offscreen에서 기존 테스트가 모든 하위 위젯에 20px 글꼴을
  지정하고 긴 수집 경로/화면 전환을 사용하는 조건. 실제 Windows 혼합 DPI/실게임 화면을
  직접 실행한 결과는 아니며 특정 DPI 배율 전체의 실패로 확대하지 않는다.
- 사용자 영향: 고정 폭 화면보다 설정 내용의 최소 폭이 커져 가로 스크롤과 화면 밖 조작이 발생한다.
  정상적인 큰 글꼴 사용을 사용자 잘못으로 취급하거나 글꼴 축소로 검증을 대신하지 않는다.
- 측정값: viewport 너비 **776px**, 보스 내용 너비/최소 폭 **850px**로 **74px** 초과,
  체력바 내용 너비/최소 폭 **831px**로 **55px** 초과다.
- 보스의 지정 영역 보기 버튼은 x=664, width=174로 오른쪽 838px까지 간다.
  체력바의 지정 영역 보기/전체 잠금 해제 버튼은 x=645, width=174로 오른쪽 819px까지 간다.
  체력바 도움말 버튼도 x=793으로 viewport 밖에 있다. 진단 로그의 실제 위젯 기하다.
- 원인 범위: `ui/boss_tab.py:134`와 `ui/stat_bars_tab.py:126`의 영역 제목/상태/세 명령을
  한 QHBoxLayout에 배치한다. `ui/stat_bars_tab.py:270`의 알림 3종도 한 줄이다.
  큰 Windows 글꼴의 최소 폭을 보존하면서 고정 본창 폭 안으로 줄바꿈/재배치하는 처리가 없다.
  어떤 행이 최종 최소 폭을 단독 결정하는지까지 Windows에서 분해 계측하지는 않았다.
- 이 제품 행들은 이번 P1 수정에서 변경되지 않았다. 앞선 화면 재배치의 Windows 회귀가
  이제 확인된 것이며, 저장 중지 수정이 화면 폭 결함을 새로 만들었다고 단정하지 않는다.

### 실제 실패와 재현

[Windows 자동 실행 39035400025](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39035400025),
job `117404074023`의 체크아웃 SHA와 실제 로그를 확인했다.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
uv run --frozen pytest tests/test_navigation_all_widths.py tests/test_tour_layout.py -vv -ra --tb=short
```

- Windows 격리 전체 결과: **9 failed, 1490 passed, 1 skipped, 9 deselected (468.37초)**.
- `test_navigation_all_widths.py::test_all_pages_and_controls_large_font[area0/1/2]` 3건은
  같은 보스/체력바 horizontal_range로 실패한다.
- `test_tour_layout.py::test_seeded_navigation_and_tour[complete/skip-True-area0/1/2]`
  6건은 큰 글꼴 조건에서 같은 보스 화면의 가로 폭 assertion으로 실패한다.
- skipped 1건은 기존 Windows 이외 전용 DWM fallback 검사다. native 표식 9조건은 deselected 후
  별도 통합 단계에서 실행 예정이었으나 앞 단계 실패로 통합 전체가 **skipped**됐다.
- `Verify exe build`도 **skipped**다. 전체 run 녹색/네이티브/새 exe 빌드 성공으로 보고할 수 없다.
- 실패 기대값/테스트를 낮추거나 skip할 사안이 아니다. 같은 실제 조작을 사용할 수 있도록
  배치를 고친 뒤 정확한 새 SHA의 자동 회귀·네이티브·exe 빌드를 확인해야 한다.
  사용자에게 수동 Run workflow 반복을 요청할 필요는 없다.

## 환경 제한

Linux의 동일 큰 글꼴 검사 `tests/test_navigation_all_widths.py`는 **3 passed (2.10초)**다.
이 통과를 Windows 실패의 반증이나 Windows 성공으로 대체하지 않는다.
Windows 실패의 근거는 실제 CI 기하·assertion이며 실게임 크래시나 Windows 네이티브 화면 렌더까지
확인했다는 뜻이 아니다. 새 장시간 핸들/메모리/스레드 계측 및 혼합 DPI 검사는 이번에 수행하지 않았다.
보고서만 반영하고 제품을 임의 수정하지 않는다. 전체 릴리즈 명령은 제공하지 않는다.
