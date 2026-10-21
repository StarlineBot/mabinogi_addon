# Windows 정체 대응·최적화 탭 후속 독립 QA

- 날짜: 2026-10-21 (한국 시간).
- 검증 소스: `277e2838aee2afe65acc4e73f052d0cca5426b45`.
- 대상: [통합 전달 요구](Windows검증장기정체_최적화탭통합_개발전달_20261021.md), [개발 검증 기록](Windows정체진단_최적화탭_개발검증_20261021.md).
- 결론: **아래 소스·Linux 독립 실행 범위에서 새로운 배포 차단 결함은 발견하지 못했다. 탭 이동·화면 그룹화와 정체 감시 동작을 확인했다. 이전 Windows 정체의 근본 원인 해결이나 이번 소스의 Windows 성공은 아직 확인하지 못했다.**
- 제품·기존 테스트·워크플로·릴리즈 노트는 QA에서 수정하지 않았다. 원격 실행 입력 **1,136 blob**의 로컬 SHA 대조 결과 누락·불일치 0건이다. 커밋 이력·메시지는 조회하지 않았다.

## 1. 최적화 탭과 화면

- 실제 MainWindow에서 제작자 상위 순서가 `전투 보조 → 파티 모집 → 편의기능 → 최적화 → 설정`인지 확인했다. 별도 대화상자가 아니라 본창에 포함된 `OptimizationPanel`이며 설정의 중복 실행 버튼은 제거됐다.
- 최적화는 환경 확인/CPU 배치/네트워크/적용·복구 4개, FPS는 대상·측정/오버레이/상태·수집 품질 3개 그룹이다. 실제 Qt 렌더와 공통 `FeatureHeader`의 제목 font·설명 role·1px divider 비교를 확인했다. 기존 고정 본창 790×800에서 페이지 폭이 viewport 790px에 맞고 버튼이 좌우를 벗어나지 않았다.
- Qt 배율 1/1.25/1.5/2의 별도 프로세스에서 같은 검사를 실행했다. 임시 PNG를 생성하고 100% 최적화/FPS와 200% 최적화 화면을 육안으로 확인했다. **Linux offscreen Qt 배율 검사이지 실제 Windows DPI·혼합 DPI 모니터 검증이 아니다.**
- 독립 추가 검사에서 제작자 허용→최적화/FPS 선택→접근 해제를 100회 반복했다. 동일 panel/Engine/Collector/timer 참조, QTimer 집합, 설정 내용을 보존했고 새 측정/시스템 적용/overlay 생성이 없었다. 접근 해제 후 설정 페이지로 돌아가며 제작자 재허용 시 설정 앞에 탭 하나만 삽입됐다.
- `main_window.py`의 설정 투어 대상은 고정 인덱스가 아닌 `_settings_scroll` 참조로 바뀌었다. 관련 양방향 투어·설정/자동설정 진입·기존 기능 탐색 검사를 직접 실행했다.
- 개발 문서의 **후속 사용자 정정**을 기준으로, 비제작자/로그아웃 상태에는 복구 기록이 있어도 알파 탭/버튼/자동 원복 팝업을 노출하지 않는 정책을 확인했다. 이전 QA의 비제작자 복구 화면 제안을 구현 누락으로 보고하지 않는다. CPU/FPS 자동 정리와 네트워크 미복구 기록 보존은 기존 회귀와 소스 경로를 확인했으며 실제 Windows 원복은 미검증이다.
- 파일별 프레임 기록/세션 요약/공유 ZIP 1단계가 새로 구현된 것은 아니다. 이번 확인은 기존 최적화/FPS 화면의 이동·그룹화다.

관련 위치: `src/mabinogi_addon/ui/optimization_panel.py`, `optimization_controller.py`의 `refresh_access/_wire_panel/prepare_close`, `main_window.py`의 탭 생성/`go_settings`, `settings_tab.py`.

## 2. 회귀 검사 정체 감시

- `.github/workflows/windows.yml`은 전체 격리 회귀 2-worker와 별도 네이티브 검사, exe 빌드·후보 보관·동일 파일 게시 조건을 유지한다. pytest 선택을 줄이거나 실패 skip/assertion 완화로 우회하지 않았다.
- `scripts/run_regressions.py`는 pytest 밖에서 소유 프로세스 트리를 감독한다. 개별 사례의 setup/call/teardown 합산/무진행 상한은 180초, 전체 격리 회귀 상한은 1,500초, 네이티브는 600초이며 timeout을 코드 124로 실패시킨다. **모든 검증·빌드가 3분 안에 끝난다는 뜻이 아니다.**
- `test_support/progress.py`는 worker/PID/상대 node/사례 해시/단계를 기록하고 C faulthandler stack을 남긴다. 실제 관련 실행에서도 30초 간격 활성 worker·node·단계 출력과 정상 코드 0 종료를 확인했다.
- setup/call/teardown 정체, GIL을 잡은 합성 네이티브 호출, 통과 표시 후 인터프리터 종료 정체, 실패 코드 보존, 소유 자손 정리/별도 sentinel 생존, 유한 양수 timeout, 경로 가공과 진단 크기 경계의 정식 검사를 직접 실행했다.
- **새 독립 재현**으로 worker 하나는 무기한 멈추고 다른 worker는 계속 테스트를 통과하도록 구성했다. 다른 worker의 최근 진행이 있어도 멈춘 `test_stuck`의 `call` 단계를 제한 시간에 감지해 124로 종료했다. 진행 worker의 통과 저널과 정체 worker의 call 저널을 모두 확인했다.
- 공개 진단은 가공된 public 파일만 1일 보관한다. 원시 dump/지역 변수는 업로드 대상이 아니며, 공개 크기·원시 stack/저널의 상한을 소스와 검사로 확인했다. `always()`도 러너 강제 종료 시 수집을 보장하지는 않는다.
- 잡담의 추가 변경은 shutdown 후 eventFilter가 후속 이벤트를 처리하지 않도록 하는 방어다. 투어 검사는 deferred delete 이후의 파괴된 Qt wrapper 접근을 피하는 정리 순서로 바뀌었다. 관련 잡담/가림/소리·투어 동작과 기존 QThread 누수 검사를 유지한 상태로 실행했다.

## 3. 직접 실행 결과

| 범위 | 이번 QA 결과 |
|---|---|
| 새 외부 감독 경로로 watchdog/CI/탐색/최적화/네트워크/잡담·가림/투어/자동설정 관련 2-worker 검사 | **506 passed**, 116.34초, 감독 프로세스 종료 코드 0 |
| 설정 export/bundle/sync/atomic/공개 정책 | **59 passed**, 5.13초 |
| custom config replacement | **18 passed**, 13.21초 |
| 새 독립 100회 상태 전환·실제 화면·동시 worker 정체 | **3 passed**, 5.34초 |
| 실제 화면 검사만 별도 Qt 배율 1.25/1.5/2에서 반복 | 각각 **1 passed**, 1.35/1.55/1.40초 |

같은 화면 사례의 배율 반복을 고유 테스트로 합산하지 않는다. 개발 문서의 전체 2,509건 결과를 이번 QA의 전체 실행 결과로 대체 인용하지 않았다. QA가 전체 테스트를 다시 실행한 것은 아니다.

```bash
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m scripts.run_regressions --diagnostics /tmp/qa-tabs-watchdog-related --case-timeout 180 --session-timeout 600 -- -n 2 -q tests/test_regression_watchdog.py tests/test_windows_ci.py tests/test_navigation.py tests/test_optimization_ui.py tests/test_optimization.py tests/test_optimization_contract.py tests/test_optimization_network.py tests/test_creator_dialogue.py tests/test_dialogue_display_policy.py tests/test_tour_layout.py tests/test_setup.py -m 'not windows_integration' --durations=15 --tb=short
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q scripts/qa_watchdog_tabs_followup_20261021.py --tb=short
```

새 스크립트는 명시 실행하는 Linux 독립 QA 자료이며 정식 CI 수집에 중복 추가하지 않았다. 합성 2초 timeout은 독립 재현용 값이며 제품 CI의 180초 설정 변경이 아니다.

## 4. 미해결 원인과 Windows 경계

**원래 50분 이상 정체한 실행 `39601019874`의 근본 원인은 여전히 미확정**이다. 마지막 활성 테스트/stack을 확보하지 못했으므로 특정 Qt/test/러너 문제를 고쳤다고 판정하지 않는다. 이번에 확인한 것은 실패를 빠르게 식별·중단하고 자료를 남기는 새 경로다.

- 180초/전체 상한이 실제 Windows 정상 소요에 충분한지, 네이티브 Job 할당·중첩/자손 종료·Ctrl 취소, PowerShell 반환 코드와 아티팩트 회수·exe 빌드는 이 Linux 환경에서 실행하지 못했다.
- 앱의 실제 Windows DPI/포커스/게임 합성·CPU/TCP/RSS 적용과 원복·장시간 리소스도 미검증이다.
- 최신 조회에서 이번 수정본의 Actions 실행 기록은 없었다. 과거 취소 실행 뒤 publish job `39608892896`은 `skipped`이며 성공 배포가 아니다. 최신 공개 배포는 v0.10.0이다.
- 현재 확인 범위에서 새 `Confirmed Bug`/`Highly Likely Bug`는 발견하지 못했다. 위 환경 제약과 원인 미확정을 통과 주장으로 덮지 않는다.

## 5. 다음 후보 검증

`v0.10.1` 태그가 없는 것과 공개 노트 맨 위 v0.10.1을 확인했다. 소스 QA 범위에서 새 차단 결함은 없으므로 사용자 선택으로 아래 **한 번**을 실행할 수 있다. Windows 전체 검증·네이티브·빌드·후보 보관에 실패하면 게시하지 않는다. 이전 취소 실행을 재실행하거나 별도 verify-only를 먼저 반복하라는 안내가 아니다.

```powershell
gh workflow run windows.yml --repo StarlineBot/mabinogi_addon --ref main -f version=0.10.1 -f mode=validate-and-publish
```

실제 Windows 통과는 이 실행 결과로 별도 확인해야 한다. 에이전트는 workflow/태그/게시를 실행하지 않았다.
