# 제작자 말풍선 및 체력바 수정 독립 QA

검증일: 2026-10-16 (한국 시간).
기준: `b3b9d0e1c118b91b44fed75118332feef5279694`.
커밋 이력/메시지를 조회하지 않고 요구사항, 소스, 실제 실행, 해당 SHA의 CI 로그를 확인했다.
제품 구현과 기존 제품 테스트는 수정하지 않았다.

## 2026-10-16 후속 QA

후속 기준: `ee03de7e0c604d4d2f5bbf3c766e5a41f446c03e`.
아래 최초 발견 본문은 증거로 보존한다. 이번 후속에서는 제품 구현/제품 테스트와 원래
독립 재현 스크립트를 수정하지 않았다. 변경 파일 7개의 로컬 Git blob을 원격과 대조했다.

- `CREATOR-QA-01`: 해결 확인. feed 생성 전에 실제 말풍선을 준비하고 현재 글꼴의 표시
  가능성 검증을 전달한다. 내장/캐시/원격 입력이 같은 검증을 거치고, 사용 가능한 항목이
  없으면 목록/갱신 신호/정상 캐시를 유지한다. 혼합 목록은 유효 항목만 쓰고 저장 원문은
  다음 실행에서도 현재 글꼴로 재검증한다. 선택형 조합은 전체 전개 없이 유한 fallback을 쓴다.
- `CREATOR-QA-02`: 해결 확인. 첫 노출 검사 실패 및 교체 후 최종 검사 실패에서 말풍선과
  만료 타이머를 닫는다. 거절된 문장을 직전 표시/자동 횟수에 기록하거나 소리를 요청하지
  않는다. 다음 정상 요청은 새 만료 시각으로 표시한다.
- `CREATOR-CI-QA-01`: 대용량 입력과 assertion을 유지한 채 두 매개변수 집합에 짧은 ID가
  지정됐다. 원래 대용량 사례도 실제 실행에 포함되며 모듈 수집 59개의 ID 제한 회귀도 통과했다.
  Windows 실제 결과는 아래 최종 검증 결과를 따른다.
- 원래 독립 스크립트의 Git blob: 말풍선 `cc28d1a9e5ad9c14338e91496c43b0c2a7ac8020`,
  체력바 `95756d1b87fc9c7dcf1f178edadb032c65950959`. 재현 assertion을 완화하지 않았다.
- 집중 실행: **80 passed (13.64초)**. 원래 말풍선 6개와 체력바 15개 및 제품 말풍선 59개.
  최초 실패 두 건뿐 아니라 혼합 목록/캐시 재실행/세 글꼴/공백 목록/드문 선택형 조합과
  교체 거절 시 기록·소리·만료/다음 정상 요청 회귀를 함께 실행했다.
- offscreen 렌더 명령 종료 0. 2줄 말풍선 이미지의 줄바꿈·꼬리·얼굴 위치를 확인했다.
  실제 Windows 혼합 DPI/창 가림/게임 실행 검증으로 간주하지 않는다.

### 후속 최종 검증 결과

- 전체 Linux 격리 회귀: **860 passed, 4 deselected, 3 warnings (177.45초)**.
  경고는 기존 toast의 Qt mouse event API deprecation이다. 실제 장치/외부 통신은 경계로
  대체했고 로컬 IPC를 허용했다. Windows 통합 4개는 이 숫자에 합산하지 않는다.
- 정확한 SHA의 [Windows 자동 실행 38831193410](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38831193410),
  job `116750117265` 전체 success. 격리 회귀 **859 passed, 1 skipped, 4 deselected,
  3 warnings (231.49초)**, 실제 네이티브 통합 **4 passed, 860 deselected,
  1 warning (1.89초)**. 기존 플랫폼 조건 skip을 새 실패 숨김으로 추가하지 않았으며
  누수 assertion과 대용량 입력은 유지했다.
- exe 빌드 성공 및 `mabinogi-addon.exe` **123,602,495 bytes** 확인.
  CI 검증용 버전은 `0.0.0`이며 실제 태그 릴리즈를 게시한 것은 아니다.
  선택적 수동 아티팩트 업로드는 자동 push 실행에서 원래 skipped이며 테스트/빌드 실패가 아니다.
- 원격 최신 태그 `v0.4.71`, 미사용 다음 태그 `v0.4.72`, 앱 내 노트 상단 `v0.4.72` 확인.
  태그 생성과 실제 게시 성공을 의미하지 않는다.
- 기존 공개 노트 혼입 `NOTES-QA-01`은 이번 수정 대상이 아니며 여전히 남아 있다.
  `.github/workflows/release.yml:136`은 앱 내 한글 노트 대신 원시 커밋 제목으로 공개 노트를
  생성한다. 이번에 해결됐다고 하지 않으며 제한 베타의 기존 비차단 잔여 문제로 유지한다.
- 실제 게임 장시간 실행/혼합 DPI/잠금·절전·디스플레이 변화의 미검증 범위는 유지한다.
  짧은 반복 테스트와 CI 성공을 모든 라이브 조건의 안정성 보장으로 확대하지 않는다.
- 후속 결론: 앞서 발견한 세 항목은 해결 확인했고 이번 수정 범위에서 새 배포 차단 문제를
  발견하지 못했다. 제한된 베타 릴리즈 명령 제공 가능. QA 문서만 추가하는 최종 커밋에는
  동일 제품 소스의 위 검증을 재사용하며 태그 실행/게시 확인은 사용자 릴리즈와 구분한다.

---

## 최초 QA 결론

이전 체력바 확정 결함 2건은 원래 독립 재현을 수정하지 않은 상태로 해결을 확인했다.
새 제작자 얼굴/잡담 말풍선에서는 확정 결함 2건을 추가 재현했다.
Windows CI는 새 테스트의 매개변수 ID 때문에 실패하여 네이티브 검증과 exe 빌드가 실행되지 않았다.
이번 QA는 배포 통과가 아니며 릴리즈 명령을 제공하지 않는다.

체력바 흔들림 경고는 이번 구현이 아닌 기획 문서 단계다. 새 말풍선과 체력바 안정성 수정이
이번 제품 검증 범위이며, 연속 진단 순환 기록을 구현한 것으로 해석하지 않았다.

## Confirmed Bug / P2 / CREATOR-QA-01

**표시할 수 없는 새 대사 목록이 정상 목록과 캐시를 덮어쓴다.**

- 요구사항: `docs/creator-dialogue-spec.md:146`은 표시할 수 없는 대사 때문에 기존 정상
  목록을 잃지 않도록 요구한다. 대사는 최대 2줄이며 긴 문장을 무한 축소하지 않는다.
- 발생 조건: 정상 캐시가 있는 상태에서 JSON 형식과 60자 제한은 통과하지만 말풍선의
  2줄 제한을 넘는 문장만 담긴 HTTP 200 응답을 받는다.
- 사용자 영향: 새 목록의 모든 문장이 선택 단계에서 탈락하여 얼굴을 눌러도 말풍선이
  나오지 않는다. 정상 캐시까지 덮어써 다음 오프라인 실행에도 불량 목록을 읽는다.
  앱 전체 크래시나 게임 판독 중단은 확인한 현상이 아니다.
- 원인: `src/mabinogi_addon/ui/dialogue_feed.py:81`의 형식 파싱 이후 표시 가능 여부를
  확인하지 않고 메모리 목록을 교체하고 신호를 보내며 캐시까지 저장한다.
  `ui/creator_dialogue.py:258`에서는 표시 불가 문장을 제외할 뿐 정상 목록으로 복구하지 않는다.
- 재현: 정상 문장 `safe cached message`를 저장하고 표시 가능함을 확인한다. `W` 60자로
  만든 유효 JSON을 실제 feed의 시작/완료 경로에 공급한 뒤 실제 창에서 표시를 요청한다.
- 실행 결과: `displayed=False`, `cache_preserved=False`,
  `all_entries_renderable=[False]`. 독립 재현
  `scripts/qa_creator_dialogue.py::test_unrenderable_remote_list_preserves_usable_last_good_data` 실패.
- 검증 수준: 실제 Qt 글꼴/줄바꿈/위젯, 실제 캐시 파일 저장과 feed 신호를 실행했다.
  HTTP 응답만 통제 입력이며 실제 공개 서버에 불량 대사를 게시하지 않았다.
- 수정 확인 기준: 표시 불가 목록에서 마지막 사용 가능한 목록과 캐시를 보존한다.
  정상/불량 문장 혼합, 캐시에 이미 불량 목록이 있는 재실행, 글꼴 차이도 함께 확인한다.

## Confirmed Bug / P3 / CREATOR-QA-02

**교체 직전 노출 재확인에 실패해도 이미 보이는 말풍선의 문장은 바뀐다.**

- 요구사항: `docs/creator-dialogue-spec.md:70`의 표시 직전 노출 재확인 및 실제 표시 문장
  기준 반복 방지/3초 수명 관리.
- 발생 조건: 첫 대사가 표시된 상태에서 새 대사를 요청하고 첫 노출 검사는 통과하지만
  교체 준비 후 마지막 노출 검사는 실패한다. 빠른 가림/상태 변경을 입력으로 통제했다.
- 사용자 영향: 거절된 새 문장이 실제 위젯에 남고 기록된 직전 문장과 달라진다.
  새 문장은 이전 만료 시각을 사용하여 3초보다 짧게 남을 수 있다.
- 원인: `src/mabinogi_addon/ui/creator_dialogue.py:188`에서 `_position`이 보이는 QLabel의
  내용을 먼저 교체한다. 같은 파일 `:259`에서 마지막 검사 실패 후 복구/닫기 없이 반환한다.
- 재현: 실제 창에 `first message` 표시 -> 목록을 `second message`로 변경 -> 노출 판정
  콜백 결과를 `[True, False]`로 공급 -> 두 번째 요청 반환값과 위젯/세션 상태 비교.
- 실행 결과: 요청 `False`, 위젯 visible `True`, 표시 `second message`,
  `session.last_text='first message'`, deadline은 기존 `3.0`.
  `scripts/qa_creator_dialogue.py::test_replacement_recheck_failure_cannot_change_a_visible_bubble` 실패.
- 검증 수준: 실제 UI/선택/요청 경로 실행이며 Windows 실제 창 가림 타이밍 실측은 아니다.
- 수정 확인 기준: 표시 확정 전에는 기존 보이는 위젯을 변경하지 않거나, 요청 거절 시
  안전하게 복구/닫는다. 최초 표시뿐 아니라 기존 대사 교체에서도 재확인을 검증한다.

## Confirmed Bug / P2 / CREATOR-CI-QA-01

**대용량 테스트 입력이 pytest ID에 들어가 Windows 회귀 단계가 실패한다.**

- 발생 조건: 새 `tests/test_creator_dialogue.py:50` 및 `:161` 매개변수 테스트에 포함된
  `b'x' * (MAX_BYTES + 1)` 입력으로 pytest 자동 ID가 생성되는 Windows 실행.
- 영향: 회귀 작업 실패로 네이티브 통합 검사와 exe 빌드가 건너뛰어진다.
  배포 파이프라인 결함이며 앱 실행 파일이 크래시했다는 증거는 아니다.
- 원인: pytest가 setup/teardown에서 긴 테스트 node ID를 `PYTEST_CURRENT_TEST`
  환경변수에 넣고 Windows의 32,767자 제한에 걸린다. 파일 경로 길이 문제가 아니다.
- 실제 재현: 해당 SHA의 자동 Windows 실행
  <https://github.com/StarlineBot/mabinogi_addon/actions/runs/38828558605>, job `116741680115`.
  로그의 `_pytest/runner.py:215` -> `os.environ[var_name] = value` ->
  `ValueError: the environment variable is longer than 32767 characters` 확인.
- 결과: `847 passed, 1 skipped, 4 deselected, 3 warnings, 4 errors (213.80s)`.
  두 대용량 매개변수 사례에서 setup/teardown 각각 오류다. 네이티브/빌드는 skipped.
- 수정 확인 기준: 대용량/손상 입력과 assertion을 유지하면서 짧은 명시적 `ids`를 지정한다.
  테스트 삭제나 skip으로 숨기지 않는다. 수정 push 후 자동 Windows CI 결과를 확인한다.
  사용자에게 같은 실패본의 수동 실행을 요청할 이유는 없다.

## 기존 체력바 결함 수정 확인

- `STAT-STABILITY-QA-01`: 실행 중 판독은 정확히 3개 띠가 확인돼야 매핑한다.
  HP만 가려진 기존 실제 PNG 재현에서 MP를 HP로 표시하지 않고 불확실 표시를 숨긴다.
  부분 검출을 반환하는 기본 진단 API와 엄격한 실행 경로를 구분한 것도 확인했다.
- `STAT-STABILITY-QA-02`: 캡처 실패/일시 정지 등 미관측 구간에서 연속 저값 확인 시간을
  비운다. 실제 회복과 구분하여 이미 발화한 알림을 미관측만으로 재무장하지 않는다.
- 원래 `scripts/qa_tracker_stability.py`를 수정하지 않고 **15 passed**.
  보스의 지속적인 소폭 상승 오독은 이전 문서의 조건부 위험이며 이번에 해결됐다고 하지 않는다.

## 실행 내역

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest -q -m 'not windows_integration' --tb=short
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest scripts/qa_creator_dialogue.py -q --tb=short
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m scripts.render_creator_dialogue
PYTHONPATH=src QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 python -m scripts.render_creator_dialogue
```

- 전체 Linux 제품 회귀: **850 passed, 4 deselected, 3 warnings (168.11초)**.
  경고는 기존 toast의 Qt mouse event API deprecation이며 네이티브 4개는 이 실행에 포함하지 않았다.
- 추가 독립 말풍선 검증: **2 failed, 4 passed (2.48초)**. 실패는 위 두 제품 결함이다.
  통과는 초기 설정 화면 제외/복귀 후 밀린 대사 미누적, 클릭/탭 120회 반복의 타이머 3개 유지와
  추가 최상위 창 미생성/종료 해제, 확률의 정확한 10분 경계/세션 초기화, 단일 문장 고갈 후
  100회 요청의 유한 종료다. 이 짧은 반복을 장시간 누수 검증으로 확대 해석하지 않는다.
- 관련 집중 실행은 114 passed + 로컬 미러에 기존 예제 파일이 빠져 1 failed였다.
  원격에 존재하는 `docs/examples/creator-dialogues/dialogues.json`을 그대로 동기화한 뒤
  원래 체력바 독립 15개와 내장/예제 동일성 1개가 **16 passed (0.67초)**.
  저장소 누락/제품 결함이 아니라 QA 환경 준비 문제로 분리했다. 전체 850 통과는 동기화 후 결과다.
- 100% 및 150% offscreen 렌더링 명령 종료 0. 얼굴/말풍선 위치와 2줄 문장 이미지 확인.
  실제 Windows 혼합 DPI/창 가림/게임 풀스크린 검증을 대체하지 않는다.
- 공개 대사 파일은 조회 시 404였다. 내장 목록 fallback은 동작하며, 공개 릴리즈 단계에
  파일이 없을 때만 초기 목록을 심는 코드와 기존 파일 보존 경로가 있다.
  실제 공개 파일 수신 성공이나 이번 릴리즈로 파일이 생성됐다고 주장하지 않는다.

숫자가 겹치는 실행을 합산해 고유 검증 사례 수로 사용하지 않는다. 실제 게임 장시간 실행,
Windows 잠금/절전/Explorer 재시작, 다중 모니터 물리 가림, FPS/핸들/GDI/오디오 장치 변화는
현재 Linux 환경에서 새로 실측하지 못했다. 해당 SHA의 Windows 네이티브/빌드도 위 오류로 미검증이다.

## 개발 세션 전달

체력바 기존 두 건은 해결 확인 완료. 말풍선 두 결함과 Windows 테스트 ID를 먼저 수정하고
push한 다음 원래 독립 재현과 자동 Windows 결과로 후속 QA한다. 사용자 설정 초기화,
대사 수동 재다운로드, 같은 실패본 반복 실행을 1차 해결책으로 안내하지 않는다.
이번 QA 반영 범위는 이 문서, 원래 안정성 문서의 후속 상태, 독립 재현 스크립트뿐이다.
