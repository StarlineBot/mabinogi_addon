# 헤일로 시간 판독·보스 연동 개발 현황

- 수동 시작·중지 버튼 없이 기존 보스 이름 판독 결과 `lenen_miir_hoehan`에 연결한다.
- 일반 미이르와 다른 보스는 제외한다. 미식별과 1.5초 이상 오래된 식별에서는 경고를 보류한다.
- 원본 미리보기는 영상 비율을 유지하며 이미지 너비에 맞추고 오른쪽에 실제 판독 시간을 표시한다.
- 타이머는 감소하는 세 관측을 확인한 뒤 중간 시간에서도 동기화한다. 고정된 숫자는 동기화하지 않는다.
- 경고는 기존 패턴 경고 아래에 기본 배치하며 별도 이동·잠금과 위치 저장을 제공한다.
- 후속 QA에서 설정 밖 카운트다운 누락과 편집 샘플 숨김을 재현했다. 수정 후에는 독립 카운트다운 창을 제공하며 `countdownPos`에 위치를 저장하고 경고 위치와 별도로 잠근다. 저장 위치가 없으면 헤일로 경고 아래에 배치한다.
- 정상 판독 시 카운트다운을 갱신하며 게임/대상/시간 판독이 불확실하면 실시간 표시를 숨긴다. 업데이트가 끊긴 경우에도 1.5초 후 숨긴다. 위치 편집 샘플은 정상 대기 틱에서 유지하고, 권한 상실·영역 해제·종료에서는 두 창과 표시 타이머를 정리한다.
- 소리는 연결하지 않았으며 체크박스는 비활성 상태다. 원본 수집은 타이머 동기화 성공과 독립적이지만 같은 회한 보스 식별 조건을 사용한다. 미식별·다른 보스·오래된 식별에서는 자동 수집과 수동 스냅샷 저장을 보류한다.
- 판독 성공 시 직전 저장 시간과 같으면 배경 변화가 있어도 중복 저장하지 않는다. 시간이 바뀌면 저장하고 판독 불가 시 기존 밝은 숫자 모양 변화 기준으로 수집한다. 초당 1장·900장·100MiB 한도와 실행마다 OFF는 유지한다.
- 수집 메타데이터에는 실제 OCR 값 또는 null을 기록한다. 내부 시계 예측값으로 대체하지 않는다.

## 현재 검증과 한계

- `tests/test_halo_timer.py`, `tests/test_halo_clock.py`, `tests/test_halo_capture.py`: 수집 조건 보완 후 119개 통과(34.39초). 대상 보스·식별 신선도·동일 판독값의 배경 변화·변경된 시간·판독 실패 수집을 포함한다.
- QA 원본 75장 중 타이머 73장 정답, 1장 보류, 타이머 없는 1장 보류. 학습은 8장만 사용한다.
- 현재 자료는 13~14분대다. 한 자리 분·15:00·00:00·분 전환·다른 DPI에서의 실제 판독은 미검증이다.
- 전체 15회차 일정은 가상 시간 회귀 테스트로 확인했으며 실제 게임 전투에서 확인한 것은 아니다.
- Linux Qt offscreen 환경에서 실제 MainWindow 레이아웃을 확인했다. Windows 캡처·클릭 통과·잠금/절전·게임 재시작·혼합 DPI 검증과 exe 빌드는 실행하지 않았다.
- Actions·태그·릴리즈는 실행하지 않는다. 이 변경 이후 이전 커밋의 검증 산출물을 배포에 재사용하면 안 된다.

## 후속 QA 수정 검증

- 근거: `docs/qa/헤일로_시간판독과_경고_독립QA_20261019.md`의 P2 두 건.
- 수정 전 독립 재현: 2 failed / 4.45초. 카운트다운 창 누락과 잠금 해제 샘플 숨김을 각각 확인했다.
- 정식 회귀 위치: `tests/test_halo_presentation.py`. 두 원래 검증을 유지하며 카운트다운 편집, 연속 틱, 다른 보스 전환, 권한 상실, 영역 해제, 종료, 독립 위치 저장, 설정창 숨김 뒤 카운트다운 갱신·숨김을 추가했다.
- 기존 `scripts/qa_halo_presentation_20261019.py`는 같은 정식 검증을 가져오는 호환 진입점으로 바꿨다. 기본 테스트에서는 정식 위치 한 곳만 수집하며 중복 실행 결과를 고유 테스트 수로 합산하지 않는다.
- 실제 MainWindow 790×768 화면과 기존 12/20px 글꼴 헤일로 레이아웃 검증을 사용했다. 새 창은 기존 경고창의 비활성 표시·클릭 통과·드래그 구현을 재사용한다. Windows 네이티브 동작이 검증됐다는 의미는 아니다.
- 수정 후 정식 회귀: 헤일로 표시/판독/시계/수집·기존 경고창·보스 탭/패턴/이름 판독 171 passed / 87.56초. 생명주기·탭 탐색·공개 정책·Unicode 계약 47 passed / 118.04초. 별도 호환 진입점 3 passed / 7.43초는 정식 회귀와 중복이므로 합계에 포함하지 않는다.

```bash
env PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_halo_presentation.py tests/test_halo_clock.py tests/test_halo_timer.py tests/test_halo_capture.py tests/test_pattern_overlay.py tests/test_boss_tab.py tests/test_boss_pattern.py tests/test_boss_name_matcher.py -q --tb=short
env PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_lifecycle.py tests/test_navigation.py tests/test_feature_release_policy.py tests/test_unicode_io_contract.py -q --tb=short
```
