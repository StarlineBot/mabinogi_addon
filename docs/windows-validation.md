# Windows 검증과 동일 산출물 배포

## 흐름과 실행 조건

소스 개발과 후속 독립 QA를 마친 뒤 사용자가 GitHub Actions의 **Windows validation**에서
main·버전·모드를 선택해 한 번 실행한다. PC에 gh가 없어도 웹의 Run workflow로 실행할 수 있다.

| 모드 | 동작 | 게시 승인 |
| --- | --- | --- |
| `verify-only` (기본) | 전체 격리 회귀 → 네이티브 → exe 빌드 → 증명/보관 | 없음 |
| `validate-and-publish` | 위 검증 전체 성공 후 자동 조건 확인 → 태그 생성 → 같은 exe 게시 | 해당 실행 소스/버전에 한정한 조건부 승인 |
| `publish-existing` | 현재 승인 소스의 중요 입력/버전과 맞는 기존 후보 고정 → 조건 확인 → 태그/게시 | 선택된 기존 후보만 승인; 검사/빌드 0회 |

일반 main/태그 푸시는 Windows 검사나 게시를 시작하지 않는다. 검증만 성공도 게시하지 않는다.
검증 run이 **완전히 completed/success로 끝난 뒤** `workflow_run`이 게시 workflow를 시작한다.
같은 run 안에서 완료 검사를 생략하지 않으며, 검증 workflow가 게시 workflow를 기다리지 않는다.
필수 단계 실패/skip/취소, 업로드 실패는 게시를 차단한다. Linux 통과로 Windows 통과를 대신하지 않는다.

게시 workflow는 기본 브랜치의 신뢰한 코드만 실행한다. 실행 이벤트/API/승인 기록/후보를 대조하고,
원래 실행의 SHA·ID·실제 attempt를 사용한다. 후행 workflow 자신의 SHA나 attempt를 후보로 쓰지 않는다.
첫 자동화 배포는 **새 workflow/scripts로 검증한 후보**가 필요하다. 기존 0.7.1은 이미 배포됐으며,
과거 검증만 실행을 소급해서 자동 게시 승인으로 취급하지 않는다. 내부 개선만으로 앱 번호를 올리지 않는다.

## 무료 한도와 보관

- 후보당 payload 200MiB 이하, 1일, 최대 2개. 업로드 전에 기존 후보 1개만 남기고 정리한다.
  삭제 대상은 `verified-windows-` 이름의 후보뿐이다. 다른 아티팩트는 삭제하지 않는다.
- 최대 약 400MiB + ZIP 오버헤드다. 다른 산출물/캐시는 별도여서 계정 전체 무료 사용량은
  보장하지 않는다. GitHub 저장 사용량 재계산에도 지연이 있을 수 있다.
- 작은 승인 기록 `release-request-*`도 1일 보관한다(후보 payload와 별도, 수 KiB).
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
원본 exe·일반/네이티브 JUnit·해당 버전 한국어 notes.md·version.json을 함께 보관한다.

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

- 테스트/네이티브/빌드 실패: 원인 수정 후 전체 재검증. 실패를 제외하거나 assertion을 완화하지 않는다.
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

전체 게이트는 offscreen Qt의 `pytest -m 'not windows_integration'`, 별도 프로세스에서
windows Qt의 `pytest -m windows_integration` 순서다. 일반 회귀는 실제 캡처/오디오/외부 통신을
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
각 사례를 한 묶음에 배정한다. 전체 Windows 게이트는 묶음을 선택하지 않는다.
동일 함수도 fixture/매개변수가 다르면 유지한다. QA 호환 진입점과 `tests/`를 CI에서 중복 실행하지 않는다.

유지한 네이티브 검사:

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
