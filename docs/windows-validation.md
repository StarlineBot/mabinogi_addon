# Windows 개발 완료 게이트

## 자동 실행과 완료 조건

제품 소스, 테스트, 의존성, 패키징, CI 관련 변경을 main에 푸시하면
`.github/workflows/windows.yml`이 Windows에서 자동 실행된다. 문서만 바뀌면 실행하지 않는다.
개발자는 **푸시한 정확한 SHA**의 결과를 확인한 뒤 QA를 요청한다.
이전 커밋의 성공이나 Linux 테스트 통과로 대신하지 않는다.

1. frozen lockfile로 Python 3.12 의존성을 설치한다.
2. 외부 장치를 격리한 전체 회귀 테스트를 실행한다.
3. 별도 프로세스에서 실제 Windows 통합 검사를 실행한다.
4. 빌드 대상 변경이면 릴리즈와 동일한 PyInstaller 명령으로 exe를 생성하고 파일을 확인한다.

빌드 대상은 보수적으로 `src/`, `packaging/`, `.github/workflows/`, `test_support/`,
`tests/`, `scripts/`, `pytest.ini`, `pyproject.toml`, `uv.lock` 변경 전체다. 따라서 시작·종료·네이티브
의존성·패키징 변경을 포함한다. 비교 기준이 없는 수동 실행/첫 푸시도 빌드한다.
테스트만 변경한 푸시도 exe를 빌드한다. 이전 제품 변경에서 회귀가 실패해 빌드가 생략된 경우,
테스트 수정 후에도 빌드 검증 공백이 남지 않도록 한다. 문서만 바뀌면 자동 실행하지 않는다.

푸시 후 개발 세션에서 다음을 실행한다. SHA는 실제 전체 커밋 해시로 치환한다.
자동 Windows 검증 대상 변경에서는 `--require-build`를 생략하지 않는다.

```bash
uv run python scripts/windows_ci.py wait --sha FULL_PUSHED_SHA --require-build
```

이 명령은 해당 SHA의 `windows.yml` 실행만 조회하고 완료까지 기다린다.
실패·취소·시간 초과·필수 단계 누락/skip·API 접근 실패는 완료로 인정하지 않는다.
네트워크나 권한 때문에 조회하지 못하면 **Windows 검증 대기**로 보고하며 QA 준비 완료로
표현하지 않는다. Git 푸시 권한과 Actions API 조회 권한은 별개다.
클라우드에서 조회가 차단되면 환경 설정의 네트워크 허용 목록에 `api.github.com`이 필요하다.
인증값을 채팅에 올리지 않는다.

main 검증은 태그·Release·자동 업데이트·Discord 공지를 만들지 않는다.
독립 QA 통과 후 릴리즈는 기존 태그 절차로 별도 진행하며, 태그 CI도 같은 테스트와 빌드를 반복한다.

## 테스트 경계와 정리

```bash
uv run --frozen pytest -q -m 'not windows_integration'
uv run --frozen pytest -q -m windows_integration
```

첫 명령은 `QT_QPA_PLATFORM=offscreen`에서 실행한다.
`test_support/boundaries.py`와 공통 fixture가 실제 MSS/DXGI 캡처, 오디오 장치,
자동 시작 OS 등록을 격리하고 외부 DNS/소켓 연결·브라우저 실행을 차단한다.
예외를 제품 코드가 잡아도 외부 접근 시도 기록이 남아 해당 테스트가 실패한다.
테스트가 의도한 프레임·모니터·오디오 응답은 명시적으로 주입한다.
로컬 IPC/루프백 테스트 서버는 허용하며 사용자 설정은 테스트별 임시 경로로 분리한다.

네이티브 검사는 Windows의 `QT_QPA_PLATFORM=windows`에서 별도로 실행한다.
실제 네이티브 의존성 로딩, 8x8 화면 캡처, 음소거 오디오 객체 생성/해제,
실제 HWND 생성/해제를 확인한다. 외부 네트워크 차단은 유지한다.
Linux에서 이 세 검사는 OS 제약으로 skip되며 Windows 통과 근거가 아니다.
게임·혼합 DPI·절전 복귀·실제 exe 실행/업데이트는 이 smoke 검사의 범위 밖이다.

각 테스트의 기존 QThread 누수 assertion을 먼저 실행하고 그 뒤 새로 만든 창을
shutdown/close하며 자식 타이머를 정지하고 DeferredDelete를 처리한다.
공통 정리로 워커 누수를 숨기지 않는다. 종료 subprocess 테스트는 pytest를 import하지 않는
오디오 경계만 사용해 제품의 실제 종료 분기를 그대로 실행한다.
실패를 없애기 위한 assertion 완화나 Windows 테스트 skip 추가는 금지한다.

## 업로드와 검증 결과 분리

exe 생성은 다운로드 업로드와 독립적인 필수 검증이다. Actions 아티팩트는 기본 비활성화다.
수동 실행에서 `upload_exe`를 선택한 경우에만 1일 보관하며 SHA/시도별 이름을 사용한다.
업로드 단계만 `continue-on-error`로 두고 summary에 테스트·통합·빌드·업로드 결과를 각각 남긴다.
quota/전송 오류는 경고이며 테스트나 빌드 실패를 성공으로 바꾸지 않는다.
태그 릴리즈의 Release 자산은 이 선택 업로드와 별도 경로다.

기존 아티팩트는 임의로 삭제하지 않는다. 기존 quota를 비우려면 저장소 소유자가 필요 여부를
확인해 정리하며 GitHub 사용량 재계산까지 지연될 수 있다. 재계산을 기다리기 위해
회귀 테스트나 exe 빌드까지 다시 실행할 필요는 없다.

## 이번 개발 검증 기록

- 기준 소스: `08b4143dac915c2d5aed0d6a918bef73366d3acd`에 이 자동화 변경을 적용했다.
- Linux 전체 격리 회귀: **716 passed, 3 deselected** (140.16초).
  deselected 3개는 별도 Windows 통합 검사이며 일반 회귀 실패를 skip한 것이 아니다.
- 오디오 경계의 시스템 beep 대체까지 반영 후 관련 테스트 **57 passed**, 보스/상태바 **14 passed**.
- 푸시 직전 원격 `db1b853f9cddbb997742315de7340b4fa3a36ed4`의 독립 QA를 반영했다.
  `SETUP-V2-QA-01`을 원본 독립 테스트로 **1 failed** 재현한 뒤 `SetupPage.refresh()`에서
  저장된 skipSetup을 신호 없이 반영하도록 수정했다. 독립 QA 전체 **10 passed**,
  설정·종료·CI 경계 회귀 **115 passed**. 양방향 ON/OFF·새 화면 생성·refresh의 무저장을 검사했다.
  독립 QA 보고서/원본 assertion은 수정하지 않았다. 전체 716개 결과는 이 P2 수정 전 결과다.
- `uv lock --check --offline` 성공. Windows 통합만 Linux에서 실행한 결과 **3 skipped**.
- 엄격한 경계로 드러난 테스트의 실제 캡처 시도는 명시적 모니터/프레임 소스로 대체했다.
  투아림 테스트는 사용 체크가 임계값을 초기화한 뒤 테스트 임계값을 설정하도록 순서를 수정했다.
  기존 기대값, 누수 assertion과 종료 subprocess의 실제 제품 종료 분기는 유지했다.
- 초기 클라우드의 Actions API 조회는 `Forbidden`이었다. 따라서 이 시점의 Windows 테스트·exe 빌드의
  실제 원격 성공은 아직 확인하지 못했으며 QA 요청 조건을 충족했다고 판단하지 않는다.

### 기능 QA와 함께 진행한 후속 검증

- `ceb429c`에는 Windows 자동화와 SETUP-V2-QA-01 수정이 함께 포함되어 있다.
  해당 소스 전체 격리 회귀 재확인은 **718 passed, 3 deselected in 135.97s**다.
  독립 V2 QA 재확인은 **10 passed in 5.02s**다.
- 노트/시작 표시 테스트를 단독 실행하자 **1 failed, 8 passed, 3 errors**가 발생했다.
  원인은 장치 경계의 `patch.dict(sys.modules, ...)`가 테스트 중 새로 import한 NumPy/OpenCV까지
  제거한 것이다. 큰 전체 집합에서는 미리 import되어 드러나지 않던 순서 의존 오류였다.
- 이제 가짜 dxcam 항목만 원래 상태로 복원한다. 깨끗한 subprocess에서 경계 내부에
  NumPy/OpenCV를 처음 import하고 경계 종료 뒤에도 동일 객체가 유지되는지 확인한다.
  기존 dxcam 항목의 유무도 각각 검증한다. 노트/시작 표시/장치 경계 **17 passed**로 재확인했다.
- 두 수정과 새 회귀 테스트를 포함한 최종 전체 격리 회귀는
  **720 passed, 3 deselected, 3 warnings in 135.06s**다. 경고는 기존 Qt 마우스 이벤트 API다.
- 기능 QA의 릴리즈 노트 지적도 반영했다. 배포된 v0.4.69 본문을 보존하고 새 설명은
  v0.4.70으로 분리했다. 앱 릴리즈나 태그 실행은 하지 않았다.
- 클라우드 설정 초안에는 api.github.com 허용과 최신 시작 지침을 저장했다.
  오래된 개별 파일 ignore 명령은 제거했다. 초안 저장은 실행 환경 적용이나 게시가 아니며,
  실제 적용과 API 조회 성공 전까지 Windows 검증은 대기 상태다.

### 첫 Windows 실제 실행 확인

- API 및 로그 접근이 정상화된 뒤 `325f6ab46881fe61ea5cc86b8bf149901321c9ab`의
  실행 `38709912827`을 확인했다. Windows 격리 회귀는
  **1 failed, 718 passed, 1 skipped, 3 deselected in 170.67s**였다.
- 실패는 새 오디오 경계 테스트의 경로 문자열 비교였다. Qt의 toLocalFile은 `/`를,
  Windows Path 문자열은 `\\`를 사용하므로 같은 파일이어도 문자열이 다르다.
  기대값/검증을 없애지 않고 원래 파일 경로에서 만든 정확한 QUrl과 실제 source QUrl을 비교한다.
- 회귀 실패 때문에 네이티브 통합과 exe 빌드는 실행되지 않았다. 이를 통과나 빌드 실패로
  해석하지 않고 수정본의 자동 실행 결과로 재검증한다.
- 회귀와 통합 명령에 `-ra`를 추가해 기존 플랫폼별 skip 사유도 실제 Windows 로그에 남긴다.
  새 skip을 추가하거나 기존 실패를 제외하지 않는다.

### 수정본 자동 검증 및 독립 QA 확인

- 최신 수정본 `7688dc1ece1cb2248d5d8a37e22f8b72bd4d115f`의 main 푸시 자동 실행
  [38710588941](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38710588941)은 **success**다.
- 격리 회귀 **719 passed, 1 skipped, 3 deselected in 166.33s**,
  네이티브 Windows 통합 **3 passed, 720 deselected in 1.44s**를 실제 로그에서 확인했다.
- 필요한 exe 빌드도 성공했고 `mabinogi-addon.exe`는 **123561999 bytes**다.
  선택 아티팩트 업로드는 기본 OFF라 건너뛰었으며, 전체 run은 실패가 아니다.
- 독립 QA의 원래 V2 재현 **10개 통과**와 배포 노트/빌드 옵션 보존도 확인했다.
  자세한 로컬 실행과 제약은 [자동설정 2차 독립 QA](qa/자동설정_2차_독립_QA.md)의 후속 판정을 따른다.
- 실게임/혼합 DPI/장시간 자원 계측과 실제 배포 exe 실행은 이 CI의 확인 범위 밖이다.
  이 기록은 문서만 갱신하므로 같은 제품 소스의 자동 검증을 다시 실행할 필요는 없다.
