# 디버프 자동 통합 독립 QA

> 최신 판정: 아래 최초 QA의 `DEBUFF-AUTO-QA-01`은 수정본 `bbdb4bd`에서 해결을 독립
> 확인했다. 후속 검증의 실행 결과와 배포 판단은 문서 마지막 절을 따른다.

- 검증일: 2026-10-16
- 제품 소스: `e60f67cb54a95dd33ff12a5f485f7cba81d3848f`
- 제품 트리: `bd01338f838678b0179c75cd9ce6d78dc8a4470a`
- 기준: `docs/debuff-auto-spec.md`, `docs/기획서.md`, 현재 소스와 독립 실행 결과.
- 이전 QA 트리와 현재 트리의 파일 내용을 비교했다. 커밋 이력이나 메시지는 조회하지 않았다.
- 이번 개발은 베타 표기 제거가 아니라 디버프 1~3차 보스 확인의 자동 통합이다.
- 제품 소스와 기존 제품 테스트는 수정하지 않았다. 이 보고서와 독립 QA 코드만 추가한다.

## 판정

핵심 자동 추적과 Windows 테스트·exe 빌드는 통과했다. 다만 기존 3차 설정을 보존한
자동 모드에서 준비 화면이 선택 사항인 HP 영역을 필수로 오인하는 **Confirmed Bug 1건**을
실행 재현했다. 전체 무문제 판정은 하지 않으며, 개발 세션의 수정 및 후속 QA 대상으로 전달한다.
크래시나 아이콘 감시 중단으로 확인된 문제는 아니다. 이번 결과에서는 릴리즈 명령을 제공하지 않는다.

## Confirmed Bug: DEBUFF-AUTO-QA-01

### 심각도와 발생 조건

- 심각도: P2, 설정 호환·준비 상태 불일치.
- `general.debuffGateMode="percent"`인 기존 설정이 남아 있다.
- `debuffAutoGate` 키가 없거나 `True`여서 실제 실행 모드는 `auto`이다.
- 디버프 기능이 켜져 있고 정상적인 디버프 영역이 등록되어 있다.
- 별도 `bossPattern.box`는 없다. 새 자동 모드에서는 지원되는 정상 상태다.
- 로그인 여부와 무관하게 재현된다.

### 기대와 실제 사용자 영향

기대: 디버프를 등록 완료로 표시하고, 선택적인 HP 영역 없이 아이콘 감시를 사용할 수 있어야 한다.

실제: 준비 화면이 `영역 미등록 · 보스 체력바 표시 필요`로 표시하고 해당 기능을 설정 필요 그룹으로
분류한다. 디버프의 자동찾기 후보 조회에도 불필요한 `boss`가 추가된다. 실제 엔진은 이미 자동
모드이므로 안내와 실행 상태가 다르다. 사용자가 설정을 잘못한 사례가 아니라 정상 기존 설정의
호환 처리 누락이다. 설정 덮어쓰기, 게임 방해나 크래시까지 발생한다고 확인한 것은 아니다.

### 기술적 원인과 위치

- `src/mabinogi_addon/config.py:789`: 런타임 모드는 `debuffAutoGate is not False`이면 `auto`이다.
- `src/mabinogi_addon/setup_state.py:94`: 준비 상태는 새 플래그를 보지 않고 기존
  `debuffGateMode == "percent"`만으로 보스 HP 영역을 필수 항목에 넣는다.
- `src/mabinogi_addon/setup_state.py:130`: 이 결과가 자동찾기 후보에도 전달된다.
- `src/mabinogi_addon/ui/setup_page.py:177`: 같은 결과로 실제 준비 화면의 문구와 그룹을 정한다.

### 재현과 검증 결과

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_debuff_auto_setup_prerequisite.py -q --tb=short
```

저장된 설정 파일을 임시 경로에 만들고 실제 로더로 `auto`를 확인한 뒤 `missing`/`pending`을
호출했다. 별도로 실제 `SetupPage`를 생성해 표시 문구를 검사했다.

- 실제 결과: **6 failed, 3 passed**.
- 플래그 없음/True × missing/pending 4건: 기대 `[]`, 실제 `["boss"]`.
- 로그인/비로그인 준비 화면 2건: 기대 `영역 등록됨`, 실제 `영역 미등록 · 보스 체력바 표시 필요`.
- 대조군 3건 통과: 명시적 진단 3차(`debuffAutoGate=False`)의 HP 필수 조건은 유지되며,
  기존 off/band 값을 보존한 자동 모드에는 같은 잘못된 의존성이 생기지 않는다.

미해결 재현은 일반 pytest 수집 대상인 `tests/` 밖에 두었다. 위 명시적 실행에서는 수정 전
6건 실패가 예상 결과이며, 테스트 실패를 숨기거나 기존 assertion을 완화하지 않았다.
기존 `tests/test_setup.py::test_manual_areas_and_shared_prerequisites`는 새 플래그가 없는 percent
설정에도 HP를 요구하는 예전 계약을 검사하므로, 기존 CI 통과만으로 이 호환 문제는 검증되지 않는다.

### 개발 세션 전달 사항

준비 상태와 자동찾기 의존성을 저장된 설정의 **유효 런타임 모드**에 맞춘다. 인자로 받은 `raw`를
판정하면서 별도 기본 경로의 설정을 읽어 서로 다른 상태를 섞지 않도록 한다. 명시적 진단 3차에서만
필요한 HP 의존성은 유지한다. 기존 선택값 삭제나 사용자 설정 초기화를 해결책으로 삼지 않는다.
플래그 없음/True/False와 실제 준비 화면의 로그인/비로그인 회귀를 포함해 수정 후 재검증한다.

## 통과한 검증

검증군은 일부 중복된다. 아래 수를 서로 다른 전체 테스트 개수로 합산하지 않는다.

| 범위 | 실제 실행 결과 |
| --- | --- |
| 자동 모드, 디버프 엔진·실화면 판독·동일 아이콘 구분·깜빡임·공개 노트 관련 회귀 | 146 passed |
| 준비 화면, 레이아웃, 종료, 버프 상태, 기존 디버프/버프 연장 재현, 프라가라흐 숨김 기준 비교 회귀 | 247 passed |
| 새 독립 자동 모드 검사 `docs/qa/assets/debuff_auto_20261016/probes.py` | 9 passed |
| `QT_SCALE_FACTOR=1.5` 레이아웃·자동 모드 회귀 | 45 passed |
| `PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python scripts/render_creator_dialogue.py` | 종료 코드 0, 자동/진단 화면 이미지 확인 |

새 독립 검사에서 확인한 사항:

- 보유 원본 스크린샷 2장에 HP 보조 영역 유무를 조합했을 때 자동 모드와 기존 아이콘 감시의
  프라가라흐 구분 결과가 같다. 해당 원본에 없는 두 프라가라흐를 잘못 적용된 것으로 판정하지 않는다.
- 실제 작업자 틱 16회 동안 주 캡처 처리는 계속되고 보조 캡처는 6회로 제한된다.
  연속 예외 3회는 한 번만 기록하고, 정상 복구 후 재발하면 새 실패로 한 번 기록한다.
  보조 캡처 실패 시 이전 보조 프레임을 비우고 주 아이콘 판독은 계속한다.
- 실제 설정 파일 IO, `DebuffTab`과 `MainWindow`의 시작 팩토리를 사용해 로그아웃 및
  보스 패턴 알림 OFF에서도 자동 엔진이 구성되는 것을 확인했다. 캡처·컨트롤러 경계는 대체했다.
- 톱니 열기와 최초 시작은 설정을 쓰지 않는다. 기존 percent 값과 숨김·영역·보스 알림 OFF를
  보존한다. 명시적 off/auto 왕복 5회는 11개 컨트롤러를 만들고 이전 컨트롤러를 각 1회 중지한다.
  사용자가 off를 직접 선택한 뒤에는 기존 진단 선택값도 off로 바뀌는 것이 정상이다.
- 자동 화면과 진단 펼침 화면의 렌더에서 확인한 범위의 잘림·겹침은 없다.

## Windows 결과

제품 SHA와 정확히 일치하는 자동 Windows 실행:
[38864203021](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38864203021),
job `116853166545`, 전체 `success`.

- 격리 회귀: **955 passed, 1 skipped, 4 deselected**.
- Windows 네이티브 통합: **4 passed, 956 deselected**.
- exe 빌드 성공: **123,611,924 bytes**.
- 선택적 exe 업로드 생략은 테스트·빌드 실패가 아니다. 새 수동 실행은 요청하지 않았다.
- 이 성공은 위 준비 상태 재현의 통과를 의미하지 않는다.

## 환경 제약과 후속 라이브 범위

Linux Qt offscreen 실행, 원본 PNG 판독, 제어된 시각·예외·캡처 경계로 검증했다.
Windows 게임 동시 실행, 실게임 연속 보스 전환, 혼합 DPI·모니터 연결 변화, 관리자 권한 차이,
포커스·전체화면, 절전 복귀와 수시간 CPU·메모리·핸들·스레드 변화는 직접 확인하지 않았다.
반복 컨트롤러 교체는 수명주기 호출 검증이며 실제 장시간 스레드 누수 측정을 대신하지 않는다.
새 독립 QA 코드와 보고서만 추가하는 공유 푸시로 제품 소스는 변경되지 않는다.

## 수정 후 독립 재검증 (2026-10-16)

### 대상과 판정

- 제품 소스: `bbdb4bdfa0f1c0abc4639f91ecbfc21d7d300be9`.
- 제품 트리: `4e186aca7f5d07df1e60296ceb2b1a2cd788b2a6`.
- 이전 QA 공유본 `6767b26`의 트리와 파일 내용을 비교했다. 커밋 이력은 읽지 않았다.
- 변경은 `setup_state.py`, `tests/test_setup.py`, 자동 통합 사양·수정 설명·공개 노트 5개 파일이다.
  디버프 엔진, 작업자, UI 구현과 캡처 소스는 이전 검증본과 동일하다.
- **DEBUFF-AUTO-QA-01 해결 확인. 검증 가능한 범위에서 새 버그나 배포 차단 문제를 찾지 못했다.**
- `setup_state.py:95`에서 literal False인 자동 플래그와 진단 percent를 함께 확인한다.
  전달된 설정만 사용하고 기본 설정 경로 재조회, 저장 또는 기존 선택값 삭제를 하지 않는다.
  최초 QA의 실패 기록은 당시 결과로 보존하며 현재 미해결 결함을 뜻하지 않는다.

### 실제 실행

원래 미해결 재현 코드를 변경하지 않고 다시 실행했다.

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_debuff_auto_setup_prerequisite.py -q --tb=short
```

- 수정 전 **6 failed, 3 passed**에서 수정 후 **9 passed**로 바뀌었다.
- 자동 플래그 없음/True 및 로그인/비로그인 실제 준비 화면에서 등록 완료로 표시한다.
- 명시적 진단 percent의 HP 필수 조건은 계속 검사하며 통과했다.

관련 회귀와 이전 독립 자동 통합 검사도 함께 실행했다.

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_debuff_auto_setup_prerequisite.py docs/qa/assets/debuff_auto_20261016/probes.py tests/test_setup.py tests/test_debuff_auto.py tests/test_release_notes.py tests/test_release_notes_trigger.py -q --tb=short
```

- **195 passed (30.48초)**. 원래 재현 9건은 이 집계에도 포함되어 중복 합산하지 않는다.
- 준비 단계/시작 안내/취소/재진입, 자동 엔진과 실제 시작 팩토리, 보조 캡처 실패 복구,
  프라가라흐 원본 판독, 공개 노트 회귀를 포함한다.
- 추가 독립 설정 검사: 자동 플래그 7종(없음/True/False/0/1/문자열/null), 과거 방식 4종
  (off/band/percent/잘못된 값), 디버프 영역 유무, HP 영역 유무의 **112조합 통과**.
  `missing`과 `pending`이 동일한 필수 항목을 반환하며, 전달한 설정을 변경하거나
  다른 경로에서 설정을 다시 읽지 않는 것을 확인했다. 실행 가능한 코드는
  `docs/qa/assets/debuff_auto_20261016/setup_probes.py`에 보관한다.
- 로컬 변경 파일 5개의 Git blob 해시가 원격 제품 트리와 일치하는 것을 확인했다.
- 기존 제품 테스트의 percent 사례는 명시적 진단 플래그를 추가해 원래 필수 영역 검사를
  유지했으며, 자동 전환 회귀를 추가했다. 실패를 skip하거나 assertion을 약화한 변경은 아니다.

### 정확한 수정 SHA의 Windows 검증

[Windows validation 38867035469](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38867035469),
job `116862129639`, 대상 SHA `bbdb4bdfa0f1c0abc4639f91ecbfc21d7d300be9`.
API의 단계별 결과와 실제 job 로그를 확인했다.

- 전체 실행: **success**.
- 격리 회귀: **976 passed, 1 skipped, 4 deselected**.
- Windows 네이티브: **4 passed, 977 deselected**.
- exe 빌드 성공: **123,611,029 bytes**.
- 선택적 exe 업로드는 정상 생략됐다. 다른 SHA의 성공으로 대신하지 않았고 수동 재실행을 요구하지 않았다.

### 배포 판단과 잔여 범위

제한된 베타 기준으로 릴리즈 명령 제공 가능하다. 원격 최신 태그는 `v0.4.74`,
다음 `v0.4.75`는 미사용이며 공개 노트 맨 위 버전도 `v0.4.75`다.
이번 후속 QA는 보고서와 독립 검사만 푸시하며 제품 소스·공개 노트를 추가 수정하지 않는다.
동일 제품의 위 Windows 검증을 재사용한다. 태그 생성과 릴리즈는 사용자가 직접 한다.

앞서 명시한 실게임·Windows 혼합 DPI·장시간 리소스 측정 제약은 유지된다.
전체 앱의 무결함이나 실제 Release 게시 성공을 보증하는 판정은 아니다.
