# Windows 검증과 동일 산출물 배포

## 흐름과 실행 조건

소스 개발과 후속 독립 QA를 마친 뒤 사용자가 GitHub Actions의 **Windows validation**에서
main·버전·모드를 선택해 한 번 실행한다. PC에 gh가 없어도 웹의 Run workflow로 실행할 수 있다.

| 모드 | 동작 | 게시 승인 |
| --- | --- | --- |
| `verify-only` (기본) | Linux 전체 격리 회귀 → Windows 최소 창 기동/종료 → exe 빌드 → 증명/보관 | 없음 |
| `validate-and-publish` | 위 검증 전체 성공 후 자동 조건 확인 → 태그 생성 → 같은 exe 게시 | 해당 실행 소스/버전에 한정한 조건부 승인 |
| `publish-existing` | 현재 승인 소스의 중요 입력/버전과 맞는 기존 후보 고정 → 조건 확인 → 태그/게시 | 선택된 기존 후보만 승인; 검사/빌드 0회 |

일반 main/태그 푸시는 Windows 검사나 게시를 시작하지 않는다. 검증만 성공도 게시하지 않는다.
검증 run이 **완전히 completed/success로 끝난 뒤** `workflow_run`이 게시 workflow를 시작한다.
같은 run 안에서 완료 검사를 생략하지 않으며, 검증 workflow가 게시 workflow를 기다리지 않는다.
필수 단계 실패/skip/취소, 업로드 실패는 게시를 차단한다. Linux 회귀와 Windows 최소 기동/빌드의
각 필수 단계를 같은 run/SHA/attempt에서 확인한다. Linux 통과를 네이티브 전체 검사 통과로 부르지 않는다.

게시 workflow는 기본 브랜치의 신뢰한 코드만 실행한다. 실행 이벤트/API/승인 기록/후보를 대조하고,
원래 실행의 SHA·ID·실제 attempt를 사용한다. 후행 workflow 자신의 SHA나 attempt를 후보로 쓰지 않는다.
첫 자동화 배포는 **새 workflow/scripts로 검증한 후보**가 필요하다. 기존 0.7.1은 이미 배포됐으며,
과거 검증만 실행을 소급해서 자동 게시 승인으로 취급하지 않는다. 내부 개선만으로 앱 번호를 올리지 않는다.

## 격리 회귀 실행 방식

일반 격리 회귀는 Ubuntu 24.04·Python 3.12·uv 잠금 의존성에서 pytest-xdist 2개 worker(`-n 2`)로
전체 대상을 실행한다. 외부 캡처·오디오·통신과 설정은 기존 경계 대체를 유지하며 기능 묶음 선택은 없다.
같은 실행/attempt 이름의 `unit-results.xml`을 1일 보관해 후속 Windows 작업이 가져온다.
Linux 소스 변경 여부 검사도 통과해야 보고서를 저장한다. 다른 실행의 성공 보고서를 대신 쓰지 않는다.

Windows 2022 작업은 그 성공에 의존한다. 실제 `windows` Qt로 `tests/test_startup_smoke.py`의
신규/기존 사용자 메인 창 생성·표시·렌더·종료와 QThread 누수를 확인하고 exe를 빌드한다.
이 최소 검사는 설정과 외부 장치를 격리하며 추적/폴링을 시작하지 않는다. **완성 exe 실행 검사가 아니다.**
실제 게임·모니터·오디오·권한에 의존하는 검사는 `windows-native.yml`로 분리해 그대로 보존한다.
완성 exe·실게임 동작은 사용자의 라이브 확인 범위이며, OS/API 관련 변경에는 선택 통합 검사를 함께 권고한다.

후보 manifest는 schema 2와 `linux-regression-windows-smoke-v1` 프로필을 명시한다.
`windows-results.xml`은 이 프로필에서 최소 창 기동 검사 결과이며 네이티브 전체 결과를 뜻하지 않는다.
게시 시 `regression`과 `validate` 두 작업의 실제 필수 단계 성공을 각각 확인한다.
이전 schema 1 후보를 새 검증 후보로 소급 승인하지 않으며 새 구조에서 후보를 만들어야 한다.
전체 검사/무료 한도의 소요 시간 개선은 실제 새 Actions 실행 전까지 미검증이다.

### 감시와 출력 정체

`scripts.run_regressions`는 사례 전체(setup/call/teardown)·무진행 180초, Linux 전체 회귀 900초,
선택 네이티브 600초, 최소 기동 60초/전체 90초의 상한을 둔다. 감시 자체의 콘솔 출력은 유한 큐/daemon 전달로 분리한다.
콘솔 소비가 멈춰도 감시 루프가 출력 완료를 기다리지 않으며 실패 이유를 파일에 먼저 기록하고
소유 검사 트리를 종료한다. 콘솔이 포화된 동안의 진행 문구는 일부 생략될 수 있지만, 필수 검사나
실패를 생략하지 않는다. 가공된 진단과 결과는 기존 아티팩트 수집 경로를 사용한다.

파일을 쓸 수 없고 pytest fd 캡처가 stderr를 가리는 복합 장애는 실행별 loopback UDP 오류 통지로
감독에 알린다. 임의 포트의 `127.0.0.1`에만 바인딩하며 외부 서버/인터넷은 사용하지 않는다.
실행별 토큰과 진단 루트가 일치하는 통지만 받아 중첩 검사·합성 Journal의 오류가 다른 실행을
중단하지 않도록 한다. 토큰/주소는 공개 진단에 기록하지 않는다. 소켓 생성 실패는 감시 없는
검사를 시작하지 않고 코드 3으로 실패한다. 기존 파일·stderr·시간 제한도 유지한다.

Python 감독 바깥에도 Linux 회귀 17분·선택 네이티브 12분·최소 기동 3분·빌드 20분의 Actions 제한을 둔다.
작업 전체 제한은 Linux 20분·Windows 빌드 30분·선택 네이티브 15분이다. 러너 대기/취소 전파 시간까지
이 제한 안에 끝난다고 보장하지 않는다. 장기 정체를 정상 진행으로 안내하거나 같은 소스를 반복 실행하지 않는다.
전체 job 45분 제한을 늘리지 않았으며 정상 검사가 이 시간만큼 반드시 걸린다는 뜻도 아니다.
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
각 사례를 한 묶음에 배정한다. Linux 전체 회귀 게이트는 묶음을 선택하지 않는다.
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

이 8개 검사의 통과는 배포 필수 Linux 전체 회귀·Windows 최소 기동·exe 빌드/후보 검증이나
선택 네이티브 검사의 통과를 대신하지 않는다.
