# Windows 검증과 동일 산출물 배포

## 흐름과 실행 조건

기존: 수동 검증은 0.0.0 exe, 태그 릴리즈는 전체 테스트와 태그 버전 exe를 다시 만들었다.
변경: 개발 완료 → 확정 버전 Windows 전체 회귀 → 네이티브 검사 → exe 빌드 → 증명/보관
→ 독립 QA → 사용자 승인 → 동일 파일 게시. 검증은 Release·업데이트 정보·공지를 만들지 않는다.
게시는 테스트/빌드를 재실행하지 않는다. 태그 푸시만으로 게시되지 않는다.

일반 main/태그 푸시에는 Windows 실행이 없다. 위험한 변경이나 배포 준비 때만 main의
`windows.yml`을 수동 실행한다. 배포 후보 검증은 전체 테스트·네이티브·빌드가 필수다.
한도/러너/API 차단은 **Windows 미검증**으로 남기며 Linux 통과로 대신하지 않는다.
정책 전환 시 이전 정의로 실행 중인 태그 게시가 있다면 소유자가 중단/종료를 확인한다.
이미 시작된 옛 Actions 실행을 이 파일 변경이 소급해서 바꾸지는 않는다.

## 무료 한도와 보관

- 후보당 payload 200MiB 이하, 1일, 최대 2개. 업로드 전에 기존 후보 1개만 남기고 정리한다.
  삭제 대상은 `verified-windows-` 이름의 후보뿐이다. 다른 아티팩트는 삭제하지 않는다.
- 최대 약 400MiB + ZIP 오버헤드다. 다른 산출물/캐시는 별도여서 계정 전체 무료 사용량은
  보장하지 않는다. GitHub 저장 사용량 재계산에도 지연이 있을 수 있다.
- 두 워크플로는 같은 concurrency 그룹에서 직렬 실행한다. GitHub 대기 실행은 영구 큐가
  아니므로 여러 실행을 동시에 예약하지 않는다. 새 후보는 이전 후보를 퇴출시킬 수 있다.
- 저장/quota 실패는 테스트·빌드 결과와 구분하되 **승격 가능한 후보 없음**으로 게시를 차단한다.
  저장소의 더 짧은 보관 정책, 수동 삭제, 만료 역시 재검증이 필요하다.

## 사용자 명령

사용하지 않은 버전을 정해 `assets/release_notes.md` 첫 버전과 맞추고 main에 반영한다.
이미 실패한 v0.5.0도 재사용하지 않는다. 대문자는 확인한 실제 값으로 대체한다.

검증 시작/조회(게시 승인 아님):

```bash
gh workflow run windows.yml --ref main -f version=X.Y.Z
uv run python scripts/windows_ci.py wait --sha FULL_VALIDATED_SHA --require-build
```

성공 실행의 SHA·run ID·attempt·버전·candidate.json 만료 시각을 기록한다. 같은 SHA라도
재실행한 attempt가 다르면 다른 후보이며 최신 시도의 성공만 사용한다.
후보 exe는 이미 실제 버전이므로 업데이트 확인/노트도 실제 버전 동작이다.
실행한다면 정식 exe와 같은 사용자 설정 폴더를 쓰므로 라이브 설정을 주의한다.

후속 독립 QA 후 **사용자가 최종 배포를 결정했을 때만** 다음을 실행한다.
태그 대상은 새 main이 아니라 검증된 전체 SHA다. 문서만 추가된 main은 허용한다.

```bash
git fetch origin --tags
git tag vX.Y.Z FULL_VALIDATED_SHA
git push origin vX.Y.Z
gh workflow run release.yml --ref main -f run_id=VALIDATION_RUN_ID -f attempt=ATTEMPT -f source_sha=FULL_VALIDATED_SHA -f version=X.Y.Z
```

명령 실패 시 이후 명령을 중단하고 원인을 확인한다. 태그만으로는 게시되지 않는다.
에이전트는 태그/게시를 대신 실행하지 않는다. 현행 최종 승인은 사용자 workflow_dispatch다.
저장소 관리자가 별도 required reviewer를 설정하지 않았다면 그런 승인 정책이 있다고 가정하지 않는다.

## 증명·동일성·차단

`candidate.json`: 소스 SHA, 중요 입력 Git tree fingerprint, 버전, run ID/attempt,
저장소/워크플로, 생성/만료 시각, PE 버전, 각 파일 SHA256/크기를 기록한다.
원본 exe·일반/네이티브 JUnit·해당 버전 한국어 notes.md·version.json을 함께 보관한다.

게시 전 GitHub API에서 정확한 workflow/run/attempt/job/필수 단계 성공과 해당 산출물
ID/이름/원본 SHA/만료를 확인한다. 실패·취소·skip·누락은 거부한다.
태그 SHA가 다르거나 원격 main의 중요 입력이 달라도 거부한다. fingerprint에는
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
이번 실행과 이관 근거는 [개발 검증](validation-promotion-development.md),
과거 결과는 [역사 기록](windows-validation-history.md)에 둔다. 과거 통과를 현재 통과로 쓰지 않는다.
