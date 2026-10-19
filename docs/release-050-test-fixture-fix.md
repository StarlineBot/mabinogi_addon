# v0.5.0 Windows 전체 회귀 실패 수정

## 근거와 범위

- [Windows 실패 분석 QA](qa/Windows_v0.5.0_전체회귀_실패분석_20261019.md)를 기준으로 대표 재현 스크립트를 먼저 실행해 **3 failed in 2.73s**를 확인했다.
- 수정 대상은 메인 화면 잡담 fixture, 제작자 % 표시 positive pipeline, 테스트 메타데이터의 UTF-8 읽기다. 제품의 잡담 가드·공개 권한·판독기·설정 전환·수집 코드는 변경하지 않는다.
- 실패한 `v0.5.0` 태그는 삭제·이동·재사용하지 않는다. 다음 배포 번호와 공개 노트 조정은 수정 후 QA 및 원격 태그 확인 뒤 진행한다. 이 수정에서 태그·릴리즈는 실행하지 않는다.

## 변경

- `test_creator_dialogue.window`는 지원되는 `skipSetup=true` 저장 설정으로 메인 화면을 준비하고 실제 `_tabs` 진입을 확인한다. 기존 화면 가림 경계 대체는 그대로이며 `_eligible()`을 항상 참으로 바꾸지 않는다. 첫 사용 안내/투어 중 잡담 차단 검사도 유지한다.
- 이 fixture를 사용하는 투명 가림 스크립트와 그 fixture를 간접 사용하는 투명 가림·창 영역 검사를 추적했다. 별도 tracker/잡담 QA fixture는 이미 `skipSetup=true`로 준비하고 있어 바꾸지 않았다. 네트워크 수명·데스크톱 API 실패 검사는 이 fixture의 소비자가 아니다. 미로그인 신규 안내와 메인 화면 정책은 여전히 다르다.
- 저구간 표시의 공유 pipeline은 실제 제작자 ID를 사용하며, 최초 전환이 완료되고 체크가 OFF인 것을 확인한 다음 명시적으로 켠다. 도르카 기본 표시와 일반 투아림 알림은 여전히 OFF로 분리한다.
- 기존 16/19/100 판독·안정화·표시 assertion을 유지한다. 새 `test_release_050_regressions.py`는 일반 계정과 비로그인 각각에서 % 차단을 명시적으로 준비하고, 제작자 전환·사용 체크 후 같은 원본의 정확한 결과와 100% 보류를 검사한다.
- `test_halo_capture.py`의 JSON 읽기에 `encoding='utf-8'`을 추가한다. Unicode I/O 계약 검사 자체는 변경하지 않는다.
- 기존 QThread 누수 검사, Windows 조건부 검사, 캡처/오디오/네트워크 경계는 유지한다. 새 skip·assertion 완화는 없다.

## 역사적 QA probe 주의

첫 수정 후 원래 6개 파일·대표 재현·기존 probe를 함께 실행한 결과는 **157 passed, 3 failed, 1 skipped**였다.
세 실패는 기존 probe가 공유 pipeline의 초기 계정을 일반 계정이라고 가정한 세 시나리오다. positive fixture를 제작자 opt-in으로 고친 뒤에는 이 전제가 맞지 않는다.
과거 QA 자료는 수정하지 않았으며, 일반/비로그인 상태를 명시적으로 준비하는 새 일반 회귀 6개로 음성·양성 조건을 모두 검증한다. 이 세 역사적 probe 실패를 Windows 원래 36개 실패의 잔존으로 오인하거나 통과로 집계하지 않는다.

## 검증 제약

Linux Qt offscreen 및 기존 외부 경계 대체 환경이다. Windows 전체 회귀·네이티브·exe를 여기서 실행한 결과는 아니다.
일반 main 푸시의 Windows Actions는 실행하지 않는다. 실제 배포는 후속 독립 QA와 새 태그의 전체 필수 게이트를 통과해야 한다.

## 최종 실행 결과

- 원래 실패 6개 파일·새 일반/비로그인 반대 조건·대표 재현: **161 passed, 1 skipped in 89.37s**. skip은 기존 Windows 전용 검사이며 통과로 세지 않는다. 이 실행에는 초기 가정을 달리하는 역사적 probe를 포함하지 않는다.
- 첫 사용 안내·공개 정책·헤일로 수집·자원 통합·투아림 일반 알림/판독: **236 passed in 151.55s**. 전체 일반 회귀나 실제 Windows 성공을 의미하지 않는다.
- `git diff --check` 통과. 원래 assertion과 접근 차단은 유지했다.

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_creator_dialogue.py tests/test_dialogue_transparent_occlusion.py tests/test_dialogue_window_region.py tests/test_tuarim_low_range_display.py tests/test_tuarim_visible_nineteen.py tests/test_unicode_io_contract.py tests/test_release_050_regressions.py scripts/qa_release_050_gate_20261019.py -q --tb=short --show-capture=no
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_setup.py tests/test_feature_release_policy.py tests/test_halo_capture.py tests/test_resource_integration.py tests/test_tuarim.py -q --tb=short --show-capture=no
```
