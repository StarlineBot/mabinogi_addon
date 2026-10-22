# Windows 검증과 동일 산출물 배포

이 문서는 실행 절차다. 최신 결과와 열린 문제는 [현재 상태](status.md) 한 곳에 갱신한다.
CI·배포 인프라는 현재 구성을 동결하며, 버전/관련 검사 목록 외 변경은 사용자 명시적 승인이 필요하다.

## 흐름과 실행 조건

소스 개발과 후속 독립 QA를 마친 뒤 사용자가 GitHub Actions의 **Windows validation**에서
main·버전·모드를 선택해 한 번 실행한다. PC에 gh가 없어도 웹의 Run workflow로 실행할 수 있다.

| 모드 | 동작 | 게시 승인 |
| --- | --- | --- |
| `verify-only` (기본) | 버전별 변경 기능 검사 → Windows 최소 창 기동/종료 → exe 빌드 → 증명/보관 | 없음 |
| `validate-and-publish` | 위 검증 전체 성공 후 자동 조건 확인 → 태그 생성 → 같은 exe 게시 | 해당 실행 소스/버전에 한정한 조건부 승인 |
| `publish-existing` | 현재 승인 소스의 중요 입력/버전과 맞는 기존 후보 고정 → 조건 확인 → 태그/게시 | 선택된 기존 후보만 승인; 검사/빌드 0회 |

일반 main/태그 푸시는 Windows 검사나 게시를 시작하지 않는다. 검증만 성공도 게시하지 않는다.
검증 run이 **완전히 completed/success로 끝난 뒤** `workflow_run`이 게시 workflow를 시작한다.
같은 run 안에서 완료 검사를 생략하지 않으며, 검증 workflow가 게시 workflow를 기다리지 않는다.
필수 단계 실패/skip/취소, 업로드 실패는 게시를 차단한다. 변경 기능 검사와 Windows 최소 기동/빌드의
각 필수 단계를 같은 run/SHA/attempt에서 확인한다. Linux 통과를 네이티브 전체 검사 통과로 부르지 않는다.

게시 workflow는 기본 브랜치의 신뢰한 코드만 실행한다. 실행 이벤트/API/승인 기록/후보를 대조하고,
원래 실행의 SHA·ID·실제 attempt를 사용한다. 후행 workflow 자신의 SHA나 attempt를 후보로 쓰지 않는다.
게시에는 검증한 후보가 필요하며 과거 검증만 실행을 소급해서 자동 게시 승인으로 취급하지 않는다.
내부 개선만으로 앱 번호를 올리지 않는다.

## 격리 회귀 실행 방식

### 배포 범위와 5분 목표

2026-10-22 사용자 재지시로 **전체 회귀를 매 배포의 필수 경로에서 제외**했다.
목표는 검증부터 게시까지 5분이며 실제 Actions/Windows 빌드 실측으로 확인한다.
5분 timeout으로 작업을 잘라 성공 처리하거나 배포 뒤로 필수 검사를 숨겨 옮기는 정책이 아니다.
정상 완료 목표와 실패 회수 상한은 별개다. 배포 CI 작업별 상한은 15분으로 두되,
5분을 초과하면 성공했어도 성능 목표 미달로 기록하고 단계별 지연 원인을 확인한다.
15분 이내 성공했다는 이유로 소요 시간을 정상으로 판정하지 않는다. GitHub의 작업별 제한은
전체 workflow 합산 15분 상한이 아니며, 검증/게시 전체 5분 목표를 대체하지 않는다.

- `packaging/release_checks.json`에 이번 버전과 관련 검사 파일만 명시한다. 개발자가 버전/노트와
  함께 관리하며 사용자가 매번 검사 범위를 입력하지 않는다. 현재 0.10.1은 백업/설정과
  최적화/네트워크/FPS/UI 관련 6개 파일, 155개 사례다. 원래 파일이나 assertion을 삭제하지 않았다.
- `scripts.run_release_checks`는 이 목록만 실행한다. 버전 불일치·빈 목록·중복·없는 파일·외부/네이티브
  경로는 실패한다. 잘못된 목록을 전체 수집이나 검사 생략으로 바꾸지 않는다.
- 전체 회귀는 로컬 개발 또는 별도 수동 `Development regression` (`regression.yml`)에서 필요할 때
  실행한다. 배포 workflow가 이를 기다리지 않고, 이 성공을 매번 먼저 제출할 필요도 없다.
- Windows 최소 창 기동/종료와 실제 exe 빌드·버전/해시·출처 검증 및 사용자 승인 조건은 유지한다.
  배포 후보의 `unit-results.xml`은 이제 변경 기능 결과이지 전체 회귀 결과가 아니다.
- 새로운 정책은 `release-features-windows-smoke-v2`로 식별한다. 기존 전체 회귀 프로필 후보를
  새 정책 후보로 소급 승격하지 않는다. 진행 중인 이전 SHA 실행의 검사 목록도 바꾸지 않는다.

Linux 러너에는 Qt 화면/DBus 라이브러리와 `libpulse0`을 명시적으로 설치한다.
오디오 장치는 테스트에서 대체하지만 `QtMultimedia`를 로딩할 때 필요한 `libpulse.so.0`까지
제거되는 것은 아니다. 회귀 시작 전에 `Check Qt runtime imports`가 QtCore/QtGui/QtWidgets/
QtNetwork/QtMultimedia를 실제로 import한다. 누락된 라이브러리는 이 필수 단계에서 실패하며,
skip이나 대체 성공으로 처리하지 않는다. 오디오 서버/실제 장치를 실행하는 검사가 아니다.

### 첫 오류와 러너 자원 진단

선택된 배포 검사 및 별도 개발 전체 회귀는 `--maxfail=3 --tb=short`로 실행한다.
실패가 발생한 후보는 오류 3건에서 중단한다(xdist의 진행 중 사례는 더 끝날 수 있다).
이 옵션만으로 첫 오류가 즉시 보이는 것은 아니므로 다음 실시간 진단을 함께 사용한다.

- `test_support.progress`가 xdist controller에서 첫 실패 보고 3건을 중복 없이 출력한다.
  setup/call/teardown·collection·pytest 내부 오류를 구분하고, `[ci-first-error]`에 테스트 위치와
  traceback을 남긴다. worker의 pytest 캡처에만 남기거나 세션 종료 요약을 기다리지 않는다.
- traceback은 처음/끝을 합쳐 약 32KiB로 제한하며 출력은 기존 유한 큐/짧은 flush를 사용한다.
  지역 변수·환경 변수·캡처 stdout/stderr를 추가 수집하지 않는다. 오류 원문은 Actions
  콘솔에만 내보내고, 가공된 공개 진단 아티팩트의 파일 목록/내용으로 추가하지 않는다.
  공개 저장소에서는 콘솔도 공개되므로 원문에 비밀값이 포함되지 않도록 주의한다.
- 같은 회귀 단계에서 `scripts.ci_resources`를 별도 Linux 프로세스 그룹으로 먼저 시작한다.
  즉시 및 약 30초 간격으로 UTC·`free -m`·`df -h /tmp .`·RSS 상위 15개 프로세스와
  cgroup v2 `memory.current`/`memory.max`/`memory.events`를 출력한다. 프로세스는 PID/PPID/RSS/
  CPU/경과 시간/실행 이름(`comm`)만 수집하고 명령 인자·환경/사용자 파일은 수집하지 않는다.
- 샘플 명령은 개별 3초 제한과 출력량 제한을 두며, 지원하지 않는 cgroup/명령은 unavailable로
  표시한다. 샘플러 실패로 테스트 결과를 성공 처리하지 않는다. EXIT/INT/TERM 시 소유 그룹을
  정리하고 원래 회귀 종료 코드를 유지한다. 후속 `always()` 단계에 정리를 의존하지 않는다.

`memory.events`의 기존 비영 값만으로 이번 OOM을 확정하지 않는다. 시간별 증가·실패 원문·실행
상태를 함께 해석한다. 러너 자체가 사라지거나 SIGKILL되면 마지막 로그의 전송/정리를 보장할 수
없다. 이 변경은 원인 수집 보완이며, 과거 정체나 연속 ERROR의 근본 원인 수정 완료를 뜻하지 않는다.

배포 기능 검사는 Ubuntu 24.04·Python 3.12·uv 잠금 의존성에서 pytest-xdist 2개 worker(`-n 2`)로
버전별 명시 목록만 실행한다. 외부 캡처·오디오·통신과 설정은 기존 경계 대체를 유지한다.
같은 실행/attempt 이름의 `unit-results.xml`을 1일 보관해 후속 Windows 작업이 가져온다.
Linux 소스 변경 여부 검사도 통과해야 보고서를 저장한다. 다른 실행의 성공 보고서를 대신 쓰지 않는다.

Windows 2022 작업은 그 성공에 의존한다. 실제 `windows` Qt로 `tests/test_startup_smoke.py`의
신규/기존 사용자 메인 창 생성·표시·렌더·종료와 QThread 누수를 확인하고 exe를 빌드한다.
이 최소 검사는 설정과 외부 장치를 격리하며 추적/폴링을 시작하지 않는다. **완성 exe 실행 검사가 아니다.**
실제 게임·모니터·오디오·권한에 의존하는 검사는 `windows-native.yml`로 분리해 그대로 보존한다.
완성 exe·실게임 동작은 사용자의 라이브 확인 범위이며, OS/API 관련 변경에는 선택 통합 검사를 함께 권고한다.

후보 manifest는 schema 2와 `release-features-windows-smoke-v2` 프로필을 명시한다.
`windows-results.xml`은 이 프로필에서 최소 창 기동 검사 결과이며 네이티브 전체 결과를 뜻하지 않는다.
게시 시 `regression`과 `validate` 두 작업의 실제 필수 단계 성공을 각각 확인한다.
이전 schema 1 후보를 새 검증 후보로 소급 승인하지 않으며 새 구조에서 후보를 만들어야 한다.
실제 실행별 소요 시간과 미검증 범위는 [현재 상태](status.md)를 확인한다.

### 감시와 출력 정체

`scripts.run_regressions`는 배포 기능 검사 사례·무진행 60초/전체 780초, 개발 전체 회귀 사례 180초/전체 900초,
선택 네이티브 600초, 최소 기동 60초/전체 90초의 상한을 둔다. 감시 자체의 콘솔 출력은 유한 큐/daemon 전달로 분리한다.
콘솔 소비가 멈춰도 감시 루프가 출력 완료를 기다리지 않으며 실패 이유를 파일에 먼저 기록하고
소유 검사 트리를 종료한다. 콘솔이 포화된 동안의 진행 문구는 일부 생략될 수 있지만, 필수 검사나
실패를 생략하지 않는다. 가공된 진단과 결과는 기존 아티팩트 수집 경로를 사용한다.

파일을 쓸 수 없고 pytest fd 캡처가 stderr를 가리는 복합 장애는 실행별 loopback UDP 오류 통지로
감독에 알린다. 임의 포트의 `127.0.0.1`에만 바인딩하며 외부 서버/인터넷은 사용하지 않는다.
실행별 토큰과 진단 루트가 일치하는 통지만 받아 중첩 검사·합성 Journal의 오류가 다른 실행을
중단하지 않도록 한다. 토큰/주소는 공개 진단에 기록하지 않는다. 소켓 생성 실패는 감시 없는
검사를 시작하지 않고 코드 3으로 실패한다. 기존 파일·stderr·시간 제한도 유지한다.

Python 감독 바깥에도 배포 기능 검사 14분·개발 전체 회귀 17분·선택 네이티브 12분·최소 기동 3분·빌드 13분의 Actions 제한을 둔다.
배포 request/기능 검사/Windows 빌드/게시 작업별 제한은 15분이다. 내부 검사/빌드 제한은
준비·정리 시간을 남기며 개별 테스트 무진행 감시는 더 짧게 유지한다. 별도 개발 전체 회귀는
20분·선택 네이티브는 15분이다. 러너 대기/취소 전파 시간까지
이 제한 안에 끝난다고 보장하지 않는다. 장기 정체를 정상 진행으로 안내하거나 같은 소스를 반복 실행하지 않는다.
이 상한은 실패 시 회수 제한이지 정상 소요 시간 목표가 아니다. 정상 검증/게시 목표는 5분이다.
러너 자체가 끊기거나 강제 종료되면 진단 업로드까지 보장하지는 못한다.
실제 Windows 결과와 과거 정체의 원인 미확정은 [직접 수정 기록](qa/CI감시출력정체_직접수정_20261022.md)을 따른다.

## 무료 한도와 보관

- 후보당 payload 200MiB 이하, 1일, 최대 2개. 업로드 전에 기존 후보 1개만 남기고 정리한다.
  삭제 대상은 `verified-windows-` 이름의 후보뿐이다. 다른 아티팩트는 삭제하지 않는다.
- 최대 약 400MiB + ZIP 오버헤드다. 다른 산출물/캐시는 별도여서 계정 전체 무료 사용량은
  보장하지 않는다. GitHub 저장 사용량 재계산에도 지연이 있을 수 있다.
- 작은 승인 기록 `release-request-*`도 1일 보관한다(후보 payload와 별도, 수 KiB).
- 중간 JUnit `regression-report-*`와 진단 자료도 1일 보관한다. 캐시는 추가하지 않는다.
  Windows에서 대규모 회귀를 매번 실행하지 않지만 Linux 사용 시간/작은 중간 산출물도 과금 대상일 수 있어
  무료 한도 미초과를 보장하지 않는다. 선택 네이티브 검사는 필요할 때만 실행한다.
- 두 워크플로는 같은 concurrency 그룹에서 직렬 실행한다. GitHub 대기 실행은 영구 큐가
  아니므로 여러 실행을 동시에 예약하지 않는다. 새 후보는 이전 후보를 퇴출시킬 수 있다.
- 저장/quota 실패는 테스트·빌드 결과와 구분하되 **승격 가능한 후보 없음**으로 게시를 차단한다.
  저장소의 더 짧은 보관 정책, 수동 삭제, 만료 역시 재검증이 필요하다.

## 사용자 실행

**예산 소진·과금이 보고된 동안은 아래 예시를 바로 실행하지 않는다.** `verify-only`도 실행
시간과 저장 비용이 발생할 수 있다. 로컬 검증·진단 수정을 먼저 마치고 Usage/예산·도달 시
사용 중지 여부·예상 비용을 확인한 뒤 사용자 별도 승인으로 다음 실행을 결정한다.
단가/실제 시간/지연 집계 없이 남은 예산으로 가능한 횟수를 보장하지 않는다.
실패 원인이 한도 차단으로 입증되지 않았다는 말은 과금 영향이 없다는 뜻이 아니다.

2026-10-22 사용자 통지 기준: 지출 $4.56, 예산 $5, 통지 시점 잔여 $0.44이며,
사용자 잡 집계는 Linux 46분·Windows 1,644분, Windows 2배 적용 기준 3,334분이다.
이는 사용자 제공 근거이며 이 세션에서 Billing/메일/집계 원자료를 독립 확인한 금액은 아니다.
현재 잔여액·집계 지연·적용 단가와 예산 중지 옵션을 확인하기 전에는 추가 실행 여유가 있다고
안내하지 않는다. 무료 포함분/예산의 다음 갱신일도 Billing 화면의 실제 값을 기준으로 확인한다.

사용하지 않은 버전을 정해 `src/mabinogi_addon/assets/release_notes.md` 첫 버전과 맞추고 main에
반영한다. 사용한 태그는 실패한 태그도 재사용하지 않는다. 아래 X.Y.Z는 실제 새 버전으로 바꾼다.
입력한 버전의 앞뒤 공백은 요청 생성 경계에서 제거한다. 그 뒤 엄격한 `X.Y.Z` 검사를 거친
동일한 값이 승인 영수증과 request job output을 통해 Windows `APP_VERSION`·PE 빌드·봉인에
전달된다. 버전 본문, 노트 일치, 기존 태그·후보·SHA·승인 검사를 완화하지 않는다.
소스 독립 QA를 마친 뒤 다음 중 **하나**를 실행한다. gh가 없으면 웹에서 같은 값을 선택한다.

검증만(기본, 게시 승인 아님):

```bash
gh workflow run windows.yml --ref main -f version=X.Y.Z -f mode=verify-only
```

검증 성공 시 배포까지 승인:

```bash
gh workflow run windows.yml --ref main -f version=X.Y.Z -f mode=validate-and-publish
```

이미 검증만으로 확인한 유효 후보 배포(재검사/재빌드 없음):

```bash
gh workflow run windows.yml --ref main -f version=X.Y.Z -f mode=publish-existing
```

기존 후보는 dispatch 시작 SHA의 중요 입력 fingerprint와 버전이 일치해야 한다. 일반 Markdown만
추가된 main은 허용한다. 후보 선택 시 정확한 run/최신 attempt/아티팩트 ID/manifest 해시를 고정한다.
여러 개가 일치하면 임의의 최신 성공을 고르지 않고 중단한다. 이때만 원래 검증 실행 ID 하나를
`candidate_run`으로 지정해 다시 실행한다. attempt/SHA 등 네 값을 복사할 필요는 없다.
후보 없음·만료·퇴출은 새 검증을 자동 실행하지 않는다. 버전/입력을 준비해 검증 모드를 직접 선택한다.

사용자는 Actions에서 **Windows validation**, 이어지는 **Publish approved Windows candidate**의
결과를 확인한다. 초록색 검증만으로 공개 게시까지 성공했다고 판단하지 않는다. 실패 뒤 사용한
태그를 다시 밀지 않는다. 실제 게시 모드 실행은 사용자 최종 결정이며 에이전트가 대신 실행하지 않는다.

## 증명·동일성·차단

`candidate.json`: 소스 SHA, 중요 입력 Git tree fingerprint, 버전, run ID/attempt,
저장소/워크플로, 생성/만료 시각, PE 버전, 각 파일 SHA256/크기와 원래 검증 모드/승인 출처를 기록한다.
별도 `release-request.json`은 실행 SHA/fingerprint·버전·모드·run/attempt를 묶으며, 기존 후보 배포는
선택한 후보 context와 manifest SHA256까지 고정한다. 두 자료 모두 같은 저장소 main/dispatch의
정확한 workflow/실행/회차에서 나온 보관 자료인지 검사한다. artifact의 Python/shell 코드는 실행하지 않는다.
원본 exe·Linux 회귀/Windows 최소 기동 JUnit·해당 버전 한국어 notes.md·version.json을 함께 보관한다.

게시 전 GitHub API에서 정확한 workflow/run/attempt/job/필수 단계 성공과 해당 산출물
ID/이름/원본 SHA/만료를 확인한다. 실패·취소·skip·누락은 거부한다.
태그 전에도 동일 게이트와 바이트 검사를 수행한다. 승인 확인 뒤 create-only API로 검증 SHA에
새 태그를 만들며 원격 ref를 다시 확인한다. 기존 태그는 같은 SHA라도 거부하므로 중복 이벤트가
이중 게시를 하지 않는다. 태그 SHA가 다르거나 원격 main의 중요 입력이 달라도 거부한다. fingerprint에는
`src/`, `packaging/`, 워크플로, 의존성/설정, `tests/`, `test_support/`, `scripts/`를 포함한다.
테스트가 읽는 `docs/qa/assets/`, `docs/examples/`, docs의 Python 코드도 포함한다.
일반 Markdown 문서는 제외한다. QA 코드·원본 이미지/샘플은 단순 문서가 아니다.

다운로드 후 파일 목록·해시·크기·버전·수명·JUnit 성공을 검사한다(테스트 재실행 아님).
비공개/공개 Release 초안에 **같은 exe 경로**를 올리고 다시 내려받아 해시를 비교한다.
두 초안 모두 일치해야 입력/만료를 다시 확인하고 공개한다. exe는 재빌드/변환하지 않는다.
공개 version.json의 해시/크기도 이 exe와 같다. 공개 작성자 대사는 최초 시드 이후 보존한다.

## 실패 복구

- 필수 회귀/최소 기동/빌드 실패: 원인 수정 후 전체 재검증. 실패를 제외하거나 assertion을 완화하지 않는다.
- 선택 네이티브 실패: OS/API 결함인지 러너의 장치 제약인지 조사해 구분한다. 관련 배포 차단 결함을
  선택 검사라는 이유로 무시하지 않으며, 미실행/환경 제약을 Windows 통과로 보고하지 않는다.
- 저장/quota/만료/누락: 새 후보 전체 검증. 태그를 이미 만들었다면 새 버전/노트를 준비한다.
  이미 사용한 태그는 실패한 태그도 이동·삭제·재사용하지 않는다.
- 태그 생성 권한/정책 오류: 게시 중단. 보호 우회나 강제 태그 생성은 하지 않는다. 실제 Actions 권한은
  최초 사용자 승인 배포에서 확인해야 하며 개발 중 태그 생성은 실행하지 않는다.
- SHA/버전/해시/태그/실행 불일치: 중단. 입력 값이나 manifest만 바꿔 우회하지 않는다.
- 초안 업로드/해시 확인 실패: 초안만 남을 수 있으며 공개 업데이트/공지는 실행하지 않는다.
- 다중 저장소 게시와 Git push는 원자적이지 않다. 중간 외부 실패로 일부 Release만 공개될 수 있다.
  기존 Release 존재 시 자동 재시도/덮어쓰기를 거부하고 소유자가 수동 복구 또는 새 버전을 결정한다.
- 공지만 실패하면 게시 자체는 성공이며 경고를 남긴다. 공지 재시도 때문에 exe를 재빌드하지 않는다.

## 기능 묶음과 유지한 검사

배포 필수 일반 회귀는 Linux offscreen Qt의 `pytest -m 'not windows_integration'`이며,
Windows 최소 창 기동과 exe 빌드로 이어진다. 선택 통합은 별도 Windows workflow에서
windows Qt의 `pytest -m windows_integration` 전체를 직렬 실행한다. 일반 회귀는 실제 캡처/오디오/외부 통신을
대체하고 설정을 테스트별로 격리한다. QThread 누수 assertion을 먼저 실행한 뒤 창/타이머/워커를
정리한다. 반복 횟수와 부정 조건의 관찰 시간을 삭제하지 않는다.

개발용 선택/조사 명령:

```bash
uv run python -m pytest --collect-only -q --test-inventory=inventory.json
uv run python -m pytest --regression-group=resources --regression-group=configuration -m 'not windows_integration'
uv run python -m pytest -q -m 'not windows_integration' --durations=30 --junitxml=results.xml
uv run python -m scripts.test_audit inventory.json results.xml
```

resources, combat, dialogue, configuration, capture, navigation, delivery, calculator, windows, core로
각 사례를 한 묶음에 배정한다. 별도 개발 전체 회귀는 묶음을 선택하지 않으며 배포 필수 경로가 아니다.
동일 함수도 fixture/매개변수가 다르면 유지한다. QA 호환 진입점과 `tests/`를 CI에서 중복 실행하지 않는다.

유지한 선택 네이티브 검사 (`gh workflow run windows-native.yml --repo StarlineBot/mabinogi_addon --ref main`, 게시 없음):

- `tests/windows/test_native.py`: 실제 의존성/8x8 캡처, 음소거 오디오 생성/해제, HWND 해제,
  게임 대상 창 이동/종료 시 캐시 무효화.
- `tests/windows/test_capture_exclusion_native.py`: 일반/layered 창 픽셀, 가시성/포커스/기하 유지,
  예외 때 affinity 복원.
- `tests/windows/test_dialogue_visibility.py`: 실제 DWM 가림/해제/숨김.
- `tests/test_dialogue_transparent_occlusion.py`: 실제 완전 투명 layered 창의 가림 제외.
- `tests/test_dialogue_network_lifecycle.py`: 루프백 HTTP 응답/취소/해제 200회, 메인 창 20회.

실게임·혼합 DPI·절전·장시간 Windows 자원 계측·빌드 exe 실행은 별도다.
원버튼 구현/검증은 [개발 기록](one-button-release-development-20261020.md),
앞선 검증 이관 근거는 [개발 검증](validation-promotion-development.md),
과거 결과는 [역사 기록](windows-validation-history.md)에 둔다. 과거 통과를 현재 통과로 쓰지 않는다.


## Windows 오프스크린 글꼴

격리 회귀의 `QT_QPA_PLATFORM=offscreen`은 Windows 네이티브 Qt와 다른 글꼴 검색 경로를 쓴다.
Qt 기본 `lib/fonts`가 비어 있으면 `QFontDatabase: Cannot find font directory`와 빈 resolved font가
나오며, 숫자를 대체 glyph로 그려 10/37/90%가 같은 이미지가 되고 문구 폭 계산도 틀릴 수 있다.

`tests/conftest.py`는 QApplication 생성 전에 공통 `test_support.qt_runtime`을 호출한다.
Windows offscreen일 때만 `QT_QPA_FONTDIR`에 `%WINDIR%/Fonts`(또는 `%SystemRoot%/Fonts`)를
지정한다. 사용자가 지정한 글꼴 폴더와 네이티브 `windows` 플랫폼·Linux/macOS 설정은 보존한다.
시스템 글꼴 경로가 없으면 원인을 명시해 실패하며 검사를 skip하거나 수치를 완화하지 않는다.
독립 프레임 진단 스크립트도 자체 QApplication 생성 전에 같은 초기화를 한다.

이 문제의 표적 재검증:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
uv run pytest tests/test_manual_update_progress.py -q --tb=short
```

이 8개 검사의 통과는 배포 필수 변경 기능 검사·Windows 최소 기동·exe 빌드/후보 검증이나
선택 네이티브 검사의 통과를 대신하지 않는다.


## 블랙박스 로컬 네이티브 검증 (아직 미실행)

이 절은 준비 절차이며 캡처·Actions·배포 실행 승인이 아니다. 현재 소스는 Linux의 합성/모형 테스트만
실행했다. 다음 단계에는 Windows x64, Visual Studio C++ 도구, 최신 Windows SDK(프로세스 루프백 API 헤더),
CMake, Python/uv, 별도로 확인한 FFmpeg/ffprobe 바이너리가 필요하다. DLL/host 바이너리는 아직 만들지 않았다.

장치 접근 없이 먼저 로컬 빌드한다(저장소 루트, Developer PowerShell):

```powershell
cmake -S native/blackbox -B "$env:TEMP/mabinogi-blackbox-build" -A x64
cmake --build "$env:TEMP/mabinogi-blackbox-build" --config Release
$env:BLACKBOX_CODEC_HOST = "$env:TEMP/mabinogi-blackbox-build/Release/blackbox_codec_host.exe"
$env:QT_QPA_PLATFORM = 'offscreen'
uv run python -m pytest tests/test_blackbox_producer.py tests/test_blackbox_audio_codec.py tests/test_blackbox_window_probe.py tests/test_blackbox_ui_connection.py -q
```

빌드 로그·Windows/SDK 버전·DLL/host 경로와 SHA256을 남긴다. 이 합성 검사는 FFmpeg libx264/AAC를 사용하며
실제 장치에 접근하지 않는다. 하드웨어 인코더 성능이나 실게임 검증으로 보고하지 않는다.

알파 앱 연결은 로컬 설정 `blackbox.validationProfile`이 완전할 때만 켜진다.
필수 키는 `temp_parent`, `output_folder`, `library`, `max_bytes`, `min_free_bytes`, `max_entries`,
`max_buffer_bytes`, `max_segments`, `max_output_bytes`, `cursor`, `hotkey_modifiers`, `hotkey_vk`다.
`producer`에는 `segment_frames`, `queued_segments`, `max_frame_bytes`, `max_raw_bytes`,
`max_segment_bytes`, `frame_tolerance_us`가 필요하다. `codec`에는 `ffmpeg`, `ffprobe`, `host`,
`encoder`, `bitrate`, `fps`, `timeout`, `tolerance_us`가 필요하고 오디오 사용 시 `audio_bitrate`도 필요하다.
폴더와 바이너리는 실제 절대 경로를 지정한다. `audio`는 `process` 또는 명시적 영상 전용 검증인
`disabled-for-validation`이다. `process`일 때 `audio_settings`의 `audio_rate`, `audio_channels`,
`max_audio_bytes`, `activation_timeout_ms`, `audio_buffer_bytes`를 모두 지정한다.
수치는 검증자가 실험 조건으로 명시하고 기록한다. 제품 기본값 승인이 아니다.

실제 캡처는 별도 승인된 Windows 검증 세션에서만 진행한다. 먼저 합성 시험 창/시험 프로세스 소리로
대상 식별·포커스 전환·프로세스 종료/재사용·A/V 타임스탬프·Job 종료를 확인한다. 그 다음 사용자가
허용한 게임창만 대상으로 단축키 수신, Alt+Tab, 최소화/잠금/절전, DPI/창 크기/화면 모드 변경,
게임 재실행, 저장 중 녹화 지속·접근 해제·앱 종료와 CPU/GPU/메모리/디스크를 측정한다.
오디오는 게임 프로세스 트리만 대상이다. 다른 앱·마이크·전체 화면 fallback은 금지하며 지원 실패는
그대로 실패로 남긴다. 영상 전용 결과와 게임 오디오 포함 결과를 분리한다.

현재 남은 제품 결정은 실측에 근거한 용량·비트레이트·구간 오차·기본 단축키와 변경 UI,
커서/오버레이·작은 창 처리, 기본 폴더명 및 무음 진행 안내다. 바이너리 동봉을 선택할 때는
FFmpeg 빌드 옵션에 따른 재배포 라이선스/크기/업데이트 책임을 확인해야 한다.
복구 dialog도 사용자 승인됐다. 기존 최상위 탭과 복구 화면 배치를 다시 묻지 않는다.


### 개발자용 자기 합성창 WGC 검사

아래는 개발자 검증 명령이며 사용자에게 소스/개발 도구 설치를 요구하는 배포 절차가 아니다.
사용자는 기존 앱 업데이트로 확인하기를 기대한다. 별도 exe/소스 업로드는 요청되지 않았다.
`BLACKBOX_CODEC_HOST`가 없거나 파일이 잘못되면 Windows 합성 테스트는 skip하지 않고 실패한다.

`probe_blackbox_window`는 자기 Qt 합성창의 HWND와 현재 PID만 만든다. 임의 HWND/게임창 입력을 받지 않고
오디오 API도 열지 않는다. 실제 WGC를 사용하므로 별도 허용된 Windows 검증에서만 아래 명령을 실행한다.
이 개발 세션에서는 실행하지 않았다. 창을 닫거나 포커스를 바꾸면 실패하며 다른 창으로 전환하지 않는다.

```powershell
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
uv run python -m scripts.probe_blackbox_window --run-owned-window-capture `
  --library "$env:TEMP/mabinogi-blackbox-build/Release/mabinogi_blackbox.dll" `
  --host "$env:BLACKBOX_CODEC_HOST" `
  --ffmpeg (Get-Command ffmpeg.exe).Source --ffprobe (Get-Command ffprobe.exe).Source `
  --output "$env:TEMP/blackbox-window-$([guid]::NewGuid().ToString('N'))"
```

대상 창은 빨강/파랑으로 바뀌는 320×240 합성창이다. 최대12프레임·프레임당4MiB·읽기10초 상한을 사용한다.
타임스탬프 증가/크기/중앙 패턴 변경, 무음 MP4 생성·완전 디코딩·원자적 확정을 확인하고 출력 폴더에
`result.json`을 남긴다. 10fps 출력은 작은 시험 조건이며 원본 프레임 타이밍 정확도/1080p60/게임 성공을
검증하지 않는다. 실패 partial은 자동 삭제하지 않는다. native API 자체의 OS 내부 정체를 Python
스레드 timeout으로 강제 종료할 수 있다는 보장은 없다.

### 이전 단계 기록: 업데이트 전달 변경안

이 절은 패키징 승인 전 조사 기록이다. 아래의 미구현·미승인 표기는 당시 상태이며, 현재 구현/승인/검증 범위는 뒤의 **승인 후 블랙박스 패키징·공식 소스 구성** 절을 따른다.

읽기 확인: `packaging/build_windows.py`는 PyInstaller onefile 빌드이며 현재 `--add-binary`/블랙박스
CMake 호출/FFmpeg 포함이 없다. `.github/workflows/windows.yml`은 기존 빌드 스크립트를 호출하지만
이 의존성을 준비하지 않는다. 동적 절대 경로 DLL과 subprocess exe는 Python import만으로 포함되지 않는다.
또한 현재 앱은 validationProfile에 명시된 개발 경로·수치를 요구해 exe에 파일만 넣어도 활성화되지 않는다.

기존 앱 업데이트 방식에 필요한 최소 범위는 다음과 같다. 현재 패키징/워크플로는 읽기만 했으며 변경하지 않았다.

1. 빌드 단계에서 동일 소스로 DLL/codec host를 만들고 MSVC 런타임 의존성까지 확인한다.
2. 배포용 FFmpeg/ffprobe의 정확한 버전·빌드 옵션·해시·의존 DLL·라이선스/대응 소스를 확정한다.
   승인된 바이너리와 고지를 exe 번들에 포함한다. 사용자 설치/PATH/개발 도구에 의존하지 않는다.
3. 앱에서 번들 상대 경로를 절대 경로로 해석하고, 승인된 제품 설정/Windows 동영상 폴더 경로를
   구성한다. validationProfile 수동 편집을 최종 사용자 필수 과정으로 만들지 않는다.
4. frozen exe에서 파일 존재·실제 helper 기동·종료·일반 사용자 접근 차단을 검증한 뒤 기존
   후보 검증/동일 산출물 게시 경로를 사용한다. 게이트/워크플로/의존성 배포 정책 변경은 별도 승인 대상이다.

권장 검토안은 GPL/nonfree 옵션 및 libx264를 제외한 하드웨어 인코더용 LGPL FFmpeg 빌드를
정확히 고정해 기존 exe 안에 동봉하는 것이다. 지원 GPU/기능과 해당 빌드의 실제 라이선스를 확인해야 하며,
미지원 시 소프트웨어 인코딩으로 자동 대체하지 않는다. libx264를 사용한 이번 합성 테스트용 바이너리를
제품에 그대로 넣는 선택은 하지 않았다. GPL 구성 선택 시 재배포 의무를 별도로 검토한다.
외부 프로세스로 실행한다는 이유만으로 재배포 라이선스 의무가 없어지는 것은 아니다.
대응 소스·빌드 옵션/패치·라이선스 고지 제공 범위를 정확한 배포물 기준으로 정한다.

근거: [FFmpeg 공식 라이선스 안내](https://ffmpeg.org/legal.html),
[PyInstaller binary 포함](https://pyinstaller.org/en/stable/spec-files.html#adding-binary-files),
[번들 런타임 경로](https://pyinstaller.org/en/stable/runtime-information.html).


## FPS 구간 요약 후속 실측 범위 (아직 실행하지 않음)

로컬 합성 CSV/Qt 검사는 실제 PresentMon 수집 성공을 뜻하지 않는다. FPS UI 확인 및 기존 릴리스
절차로 준비된 앱을 사용자가 업데이트한 뒤, 제작자 FPS 탭에서 측정/수집 모드를 사용한다.
사용자에게 Python/MSVC 설치나 별도 소스 패치 실행을 요구하는 전달 방식이 아니다.

- 동일 게임 장면에서 측정 전/측정/자동 요약 저장의 CPU·메모리·프레임타임 비용을 비교한다.
- 평균·완전한1초 최대·1% low·유효 표본/시간·긴 간격을 함께 확인한다. CPU 제한으로 최대/평균이
  낮아진 결과를 안정성 개선만으로 성공이라 해석하지 않는다.
- Alt+Tab/최소화/복귀, 게임 재실행/swapchain 변경, 측정 재시작, 최적화 적용/원복 때 구간이 분리되는지
  확인한다. 실제 포커스 관측 주기/전달 지연과 PresentMon 이벤트 손실은 모형 테스트의 미검증 범위다.
- 수집 중단·권한 해제·앱 종료에서 완료된 JSON을 보존하는지, 장시간 수집이 자원 한도에서 명확히
  멈추는지 확인한다. 화면/오디오 녹화는 이 FPS 검증에 포함하지 않는다.
- 문제가 있으면 선택한 구간의 요약 JSON과 재현 조작/앱 버전을 이 대화에 전달한다. 자동 업로드는 없다.
  에이전트는 요약의 정의·경계/설정 근거와 실제 조작을 비교해 조사한다.


### 승인 후 블랙박스 패키징·공식 소스 구성

패키징 수정과 알파 제품 초기값은 승인됐다. 원격 푸시/Actions/태그/게시 실행은 별도 미승인이다.
`windows.yml`의 기존 명령은 `packaging/build_windows.py` → `blackbox_bundle.prepare` →
`ffmpeg_source.build` → native CMake → manifest/정책 검사 → PyInstaller를 호출한다.
workflow/gate/후보 SHA·해시·사람의 최종 게시 절차는 바꾸지 않았다. 모형 main 진입 검사도 이 순서를 확인한다.

제품 정책은 `packaging/blackbox-product.json`이며 별도 사용자 JSON 입력이 필요 없다.
영상12Mbps/AAC192kbps, 임시8GiB/최소여유4GiB/버퍼2GiB, 원시큐512MiB와입력1920×1080,
오차50ms, Ctrl+Alt+F10, 커서제외/게임소리 실패시중단을 승인했다. 상세 정의는 블랙박스 명세9절을 따른다.
입력 초과/오디오 미지원/하드웨어 MFT 부재는 오류로 중단하며 전체화면·다른 소리·소프트웨어 인코딩으로 대체하지 않는다.

**BtbN 후보는 사용하지 않는다.** 그 후보는 LGPL v3·다수 외부 의존성을 포함해 대응소스 추적 범위가 컸다.
현재는 [공식 FFmpeg8.1.3 소스](https://github.com/FFmpeg/FFmpeg/tree/n8.1.3)를 최소 shared 구성으로 직접 빌드한다.
소스 tar SHA256 `09f990289327d3ebfedf4fc15cae3f884a65dab7a5aac7bbb5b01ff83900efd9`.
`--disable-autodetect --disable-gpl --disable-nonfree --disable-version3`이며 외부 codec library와
네트워크/장치 입력은 제외한다. `h264_mf`/AAC와 MP4, 원시 프레임·WAV·concat 및 필요한 필터만 포함한다.
하드웨어 `hw_encoding=1`을 강제하며 별도GPU SDK DLL/유료 코덱/시험용 libx264는 번들하지 않는다.
하드웨어 MF는 GPU/드라이버별 제공 여부가 다를 수 있으므로 Windows 실검증이 필요하다.

[LLVM-MinGW20261020](https://github.com/mstorsjo/llvm-mingw/releases/tag/20261020) Windows compiler zip SHA256은
`fd5462b7f5d93b2ff981fcd3f9c7e427e47f3203c64ea91c27bcc444eebd74cd`.
MinGW-w64 소스 commit `0d6dfbc348dfad714761c0a7151615767f96bcb5`, tar SHA256
`03f717ddb9005d6519e38434359af281d0819d5d468a42578e28bd0fd8e31d0c`도 고정했다.
프로젝트의 소스/컴파일러는 build machine에서만 내려받고 해시를 검사한다. MSYS2 bash/GNU make와
MSVC/CMake/Windows SDK는 개발자·Actions 빌드 환경 도구다. 사용자에게 설치를 요구하지 않는다.

확인한 라이선스는 FFmpeg LGPL-2.1-or-later, LLVM Apache-2.0 with LLVM exceptions,
MinGW-w64의 ZPL/개별 파일 고지다. 소스 수정은 없으며 구성에 GPL/nonfree/version3가 활성화되지 않았음을
실제 generated config에서 확인했다. FFmpeg/MinGW 완전 소스 tar, 실제 빌드 설정/recipe·재빌드 안내와
고지를 `corresponding-source.zip`으로 exe에 함께 넣고, 처음 기능을 연결할 때
`%LOCALAPPDATA%/StarlineMabinogiAddon/third_party/ffmpeg-<묶음해시>/`에 일반파일로 보존한다.
앱 전체 소스를 공개해야 한다는 결론은 내리지 않았다. [FFmpeg 공식 법적 안내](https://www.ffmpeg.org/legal.html)와
[소스 LICENSE](https://github.com/FFmpeg/FFmpeg/blob/n8.1.3/LICENSE.md)의 의무를 구분한다.
코덱 특허/지역별 권리·별도 계약 필요 여부까지 자동 검증됐다고 주장하지 않으며, source/notice hash는 법률 판단의 대체가 아니다.

Linux에서 LLVM-MinGW Linux 도구로 Windows PE 인코더/ffprobe/6DLL 크로스 빌드는 성공했다.
공식 Linux toolchain SHA256 `55064b60b991a1e1e8090b8c2f84e82b22cfe5903d12c159d65064cf5e8ae335`.
이것은 WGC/native DLL의 MSVC 빌드나 Windows에서의 인코더 실행 성공이 아니다.
원래 Docker 검토는 컨테이너 DNS 실패로 중단했고, 공식 해시고정 compiler를 로컬에서 사용했다. 접근 거부 우회는 하지 않았다.

다음 Windows 개발자 검증은 위 CMake 명령으로 WGC DLL/host 빌드, 자기 합성창 무음 probe(`--encoder h264_mf`),
프로세스 오디오 모형/합성 경계와 실제 지원 여부 확인이다. 실제 게임/오디오는 별도 허용 범위만 검증한다.
승인된 원격 검증 단계에서는 기존 `uv run --frozen --group build python packaging/build_windows.py --version <확정버전>`을
사용한다. 최소 FFmpeg 소스 빌드가 포함되므로 첫 Windows 실행에서 기존13분 빌드 상한/전체5분 목표와
실제 시간을 확인하며 임의로 제한을 늘리지 않는다. frozen exe의 번들 DLL/설정/저장 위치/제작자 접근과
기동을 확인한 후 기존 후보 절차로 인계한다. 지금은 원격 명령을 실행하지 않는다.
사용자는 최종 기존 앱 업데이트로 확인하며 수동 소스 패치나 개발도구 설치가 필요한 흐름이 아니다.
