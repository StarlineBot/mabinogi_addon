# 프라가라흐 숨김 및 재구성 수정 후 독립 QA

- 검토일: 2026-10-16 (Asia/Seoul)
- 제품 기준: `b945b1fb38c5bd210dfb4cddae865770d2405bad`
- 비교 기준: `8de4334`의 소스 tree와 원래 독립 재현. 커밋 이력/메시지는 조회하지 않았다.
- 결과: **정상 카탈로그의 실제 앱 경로에서 DEBUFF-IDENTITY-QA-02 해결 확인.**
  이번 변경에서 새 Confirmed Bug/Highly Likely Bug를 발견하지 않았다.
- 완료 판단: 확인한 범위에서 베타 배포 차단 문제가 없다. 실게임 정확도 전반이나
  모든 사용자 이미지/장치 환경의 무결함을 보장하는 의미는 아니다.
- 1~3차 통합은 구현되지 않았다. 별도 제안 문서를 이번 수정 범위에 포함하지 않는다.

## 1. 실제 수정 경로

- `tracker/debuff_engine.py:102`의 선택 인자 `reference_templates`로 비교 전용 자료를 받는다.
  `_identity_variants`에는 두 종류가 있지만 전체 검색용 `_templates`/`_gray_variants`,
  표시 순서와 추적 상태에는 실제 추적 항목만 들어갈 수 있다.
- `ui/main_window.py:1402`는 표시 대상의 상대 ID를 구하고, 현재 카탈로그를 통해
  숨긴 상대 파일도 읽어 `:1409`에서 비교 자료로 전달한다. 사용자 이미지가 있으면
  같은 카탈로그 경로를 사용하며 기본 이미지로 몰래 대체하지 않는다.
- `tracker/debuff_engine.py:194`의 `can_track()`과
  `ui/main_window.py:1441`의 설정 변경 경로는 기존 엔진이 처음부터 검색하지 않던 항목을
  다시 켰을 때 엔진을 재구성한다. 이미 검색 가능한 순서 변경은 재시작하지 않는다.
- 앱 소스에서 `DebuffEngine`을 생성하는 호출자는 위 실제 시작 경로 하나임을 검색 확인했다.
  진단 스크립트의 `best_scores()`는 원시 점수이므로 확정 적용 상태와 구분한다.
- 이미지 파일, 저장된 영역, 1~3차 게이트, 시간/재표시 임계와 오버레이 UI는 변경하지 않았다.

## 2. 과거 실패 재현을 어떻게 판단했는가

기존 `scripts/qa_debuff_identity_gate_followup.py -k hiding_peer`를 수정하지 않고 실행했다.
결과는 **4 failed, 50 deselected, 0.44초**였다. 이를 통과로 숨기지 않았다.

이 코드의 `:135`는 이전 시작 코드처럼 표시 대상 템플릿만 골라 `DebuffEngine`을 직접
만들고, 새 `reference_templates`를 전달하지 않는다. 엔진 자체가 파일 시스템의 전역
카탈로그를 읽는 API로 바뀐 것은 아니므로, 이 직접 호출은 여전히 상대를 구분하지 못한다.
그러나 현재 앱은 그 생성 방식을 사용하지 않는다. 과거 구성만으로 현재 앱의 재시작
버그가 남았다고 판단하지 않고, **기대 동작은 유지한 채 실제 생성 경로를 실행**했다.

기존 재현/과거 보고서/제품 테스트의 assertion은 약화하거나 삭제하지 않았다.
기존 기록에는 후속 결과 링크만 추가했다. 새 독립 검사는 실제
`MainWindow._start_debuff_tracking()`, `_debuff_order()`,
`_on_debuff_tracking_changed()`와 실제 카탈로그 파일 로더/엔진을 호출한다.
대체한 경계는 캡처 소스와 컨트롤러이며, 실제 Windows 앱 재시작을 수행한 시험은 아니다.

## 3. 독립 검증 결과

### 실제 시작/숨김/재구성 경로: 24 passed

검증 코드: [`assets/debuff_hidden_reference_20261016/probes.py`](assets/debuff_hidden_reference_20261016/probes.py)

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen uv run pytest docs/qa/assets/debuff_hidden_reference_20261016/probes.py -q --tb=short
```

기본 28px 이미지와 원본 16px 후보 각각에서 다음을 검사했다.

- 마법/물리 양방향으로, 두 종류 표시에서 한쪽 숨김 후 반대 아이콘만 입력하면
  실제로 없는 추적 종류가 미적용 표시로 유지된다.
- 같은 숨김 설정으로 실제 시작 함수를 3회 다시 호출해도 판정이 동일하다.
- 다시 켜면 기존 컨트롤러의 stop이 호출되고, 새 항목이 실제 엔진의 추적 대상으로 들어간다.
- 1~3차 각각에 동일한 참조 전달이 적용되고, 별도 바 소스는 percent에만 연결된다.
  이 검사는 모드 연결 확인이며, 작은 패치에 실제 보스바가 있다고 가장하지 않았다.
- 처음부터 둘 다 숨긴 빈 엔진에서 한쪽을 켜는 경우, 표시 순서만 바꾸는 경우를 확인했다.
- 카탈로그의 숨김 상대를 사용자 override처럼 다른 파일로 바꾸면 그 파일이 비교 자료에
  반영된다. 동일한 사용자 이미지로 구분할 수 없는 경우 임의로 적용 확정하지 않는다.
- 비교 전용 상대는 별도 전체 검색이나 진단 반환 ID로 추가되지 않는다.

컨트롤러 대체 객체의 stop 호출을 확인한 것이며, 이를 실제 Windows 핸들/스레드 누수
부재의 증거로 확대하지 않는다. 실제 장시간 자원 사용은 이번 범위에서 새로 실측하지 않았다.

### 관련 회귀: 189 passed, 21.74초

버프/디버프 매칭, 상태/시간, 원본 라이브 판독, 깜빡임, 버프 시간 연장, 기존 보스 확인
벤치마크 및 신규 제품 식별 44개를 직접 실행했다. 과거 TypeError 재현과 후보 비교 횟수
상한도 기존 회귀에 포함되어 있다.

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen uv run pytest tests/test_icon_matcher.py tests/test_buff_detector.py tests/test_engine.py tests/test_buff_state.py tests/test_debuff_engine.py tests/test_debuff_fp_latch.py tests/test_debuff_momo_fp.py tests/test_debuff_live_detection.py tests/test_debuff_identity.py tests/test_debuff_bench.py scripts/qa_debuff_live_detection.py scripts/qa_debuff_flicker.py scripts/qa_buff_extension_alert.py -q --tb=short
```

### 기존 추가 정상 시나리오: 50 passed, 4 deselected, 30.12초

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen uv run pytest scripts/qa_debuff_identity_gate_followup.py -k 'not hiding_peer' -q --tb=short
```

실제 바/숫자로 게이트가 활성화된 1~3차, 위치 이동, 다른 아이콘 75슬롯,
종류/보스 반복 전환, 검은 바 및 별도 캡처 `None` 후 복구를 다시 확인했다.
제외한 4개는 앞 절에서 실패 결과와 생성 경로 차이를 명시한 과거 직접 호출이다.
새 24개 검사로 실제 앱 생성 경로를 대체 검증했으며, 단순 제외만으로 통과시킨 것이 아니다.

엔진·UI·요구사항·기존 재현·원본 이미지 등 관련 파일 18개의 Git blob SHA를
원격 제품 tree와 대조해 모두 일치함도 확인했다.

## 4. 정확한 수정 SHA의 Windows 확인

[자동 실행 38859831865](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38859831865),
작업 `116839361952`의 단계 및 로그를 확인했다. 다른 SHA의 성공을 재사용하지 않았다.

| 단계 | 결과 |
| --- | --- |
| 전체 실행 | success |
| 격리 회귀 | 928 passed, 1 skipped, 4 deselected, 3 warnings, 257.22초 |
| 실제 Windows 네이티브 통합 | 4 passed, 929 deselected, 1 warning, 1.92초 |
| exe 빌드 | success, 123,605,176 bytes |
| 수동 아티팩트 업로드 | skipped, 정상 push 실행 정책 |

## 5. 남은 범위와 릴리즈 판단

- 상대 이미지가 삭제/손상/미등록되어 읽히지 않는 경우와 종횡비가 다른 사용자 이미지까지
  정확한 식별을 보장하지 않는다. 정상 숨김 상대가 있는 이번 재현 경로와 구분한다.
- 실제 전투에서의 순간 가림/렌더링 변화/깜빡임, 다른 DPI/모니터 및 장시간 게임 부하는
  라이브에서 확인해야 한다. 오프라인 통과를 모든 디버프 오인식 해결로 확대하지 않는다.
- 새 자동 모드/1~3차 통합, 기본 크롭 일괄 교체, 설정 마이그레이션은 이번 릴리즈에 없다.
- 한정 베타 기준에서 현재 수정 범위의 배포 차단 문제를 발견하지 않았다.
  QA 자료만 별도 반영하고, 동일 제품 소스의 위 Windows 성공을 기준으로 릴리즈 명령을 제공한다.
- 원격 최신 정식 태그는 `v0.4.73`, 다음 `v0.4.74`는 미사용이며 제품 노트 최상단도
  `v0.4.74`임을 확인했다. 실제 태그 생성/푸시는 사용자가 수행한다.
