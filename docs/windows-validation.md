# Windows 선택 검증과 릴리즈 게이트

## 현재 정책 (2026-10-18)

Actions 무료 한도에 맞춰 **일반 main 푸시의 Windows 자동 실행은 중단**한다.
`.github/workflows/windows.yml`은 `workflow_dispatch`로만 실행한다. 일반 개발은 로컬 관련
회귀를 수행하고 Windows 미실행 범위를 명시해 QA로 전달한다. 아래 과거 자동 실행 기록은
당시 결과이며 현재 트리거 정책이 아니다.

시작/종료·Qt 수명/스레드·네이티브 의존성·캡처/오디오/입력·패키징/업데이트 등 위험한
변경은 영향과 남은 한도를 고려해 선택적으로 사전 검증한다. 일반 푸시마다 수동 실행을
요청하거나 실행이 없는 SHA를 기다리지 않는다. 선택 실행은 다음을 수행한다.

1. frozen lockfile로 Python 3.12 의존성을 설치한다.
2. 외부 장치를 격리한 전체 회귀 테스트를 실행한다.
3. 별도 프로세스에서 실제 Windows 통합 검사를 실행한다.
4. `build_exe=true`일 때 릴리즈와 동일한 PyInstaller 명령으로 exe를 생성한다.
   기본 OFF다. 실행·의존성·패키징 위험에는 선택하며 `upload_exe=true`도 빌드를 수반한다.

선택 실행 예시(태그가 아닌 main의 대상 커밋을 확인한 뒤 실행):

```bash
gh workflow run windows.yml --ref main -f build_exe=true -f upload_exe=false
```

선택 실행을 시작한 경우에만 정확한 전체 SHA로 아래 결과 조회를 수행한다.
빌드를 선택하지 않은 검사에서는 `--require-build`를 생략한다.

```bash
uv run python scripts/windows_ci.py wait --sha FULL_PUSHED_SHA --require-build
```

이 명령은 해당 SHA의 `windows.yml` 실행만 조회하고 완료까지 기다린다.
실패·취소·시간 초과·필수 단계 누락/skip·API 접근 실패는 완료로 인정하지 않는다.
네트워크/권한/한도/러너 문제로 실행·조회하지 못하면 **Windows 미검증**으로 명시한다.
이는 로컬 QA 전달을 금지하지 않지만 Windows 통과나 배포 성공을 뜻하지 않는다.
Git 푸시 권한과 Actions API 조회 권한은 별개다.
클라우드에서 조회가 차단되면 환경 설정의 네트워크 허용 목록에 `api.github.com`이 필요하다.
인증값을 채팅에 올리지 않는다.

선택 검증은 태그·Release·자동 업데이트·Discord 공지를 만들지 않는다.
릴리즈 `v*` 태그에서는 `release.yml`의 **전체 격리 회귀 → 네이티브 검사 → exe 빌드**가
모두 필수다. 실패/취소/skip/한도 차단이면 게시하지 않는다. 게시/공개 업데이트/공지 단계는
세 단계의 성공을 명시적으로 요구한다. 선택적 업로드 quota 경고만 이 게이트와 별개다.

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
실제 HWND 생성/해제를 확인한다. 대사 네트워크는 일반 회귀에서 다운로드 시작뿐 아니라
Qt 네트워크 관리자 생성도 대체한다. 실제 관리자는 별도 통합 검사에서 루프백 HTTP 서버와
200회 생성/응답/진행 중 취소/반복 종료/해제를 검증한다. 외부 네트워크 차단은 유지한다.
실제 메인 창 내부의 Qt 네트워크 관리자 생성/해제도 캡처·오디오와 분리해 20회 반복한다.
이 Qt 수명 검사는 Linux에서도 명시적으로 실행할 수 있으나 Windows 통과 근거가 아니다.
Windows API를 사용하는 통합 검사는 Linux에서 OS 제약으로 skip된다.
게임·혼합 DPI·절전 복귀·실제 exe 실행/업데이트는 이 smoke 검사의 범위 밖이다.

선택 검증/태그 CI는 `-vv -ra`로 각 테스트 ID와 실행 순서를 남긴다. 네이티브 크래시로
최종 요약/XML 작성에 도달하지 못해도 마지막 실행 테스트를 확인할 수 있게 한다.
이전 Windows 접근 위반 조사와 검증 상태는 [네트워크 경계 보완](qt-network-boundary-fix.md)에 기록한다.

각 테스트의 기존 QThread 누수 assertion을 먼저 실행하고 그 뒤 새로 만든 창을
shutdown/close하며 자식 타이머를 정지하고 DeferredDelete를 처리한다.
공통 정리로 워커 누수를 숨기지 않는다. 종료 subprocess 테스트는 pytest를 import하지 않는
오디오 경계만 사용해 제품의 실제 종료 분기를 그대로 실행한다.
실패를 없애기 위한 assertion 완화나 Windows 테스트 skip 추가는 금지한다.

## 설정 레이아웃 변경의 로컬 회귀

그룹/스크롤/위젯 재부모화와 공통 명령 변경에는 새 화면 검사뿐 아니라 기존 탐색·안내·
폭 검사를 포함한다. `tests/test_wrapping_controls.py`, `tests/test_tuarim_settings_width.py`,
`tests/test_navigation_all_widths.py`, `tests/test_tour_layout.py`와 체력바 미리보기 변경 시
`tests/test_stat_preview_width.py`, `tests/test_stat_preview_transition.py`를 함께 실행한다.
배율 300→50→150→300, 세 항목→하나→세 항목과 다른 탭 복귀도 포함한다.
기본/큰 글꼴, 좁고 짧은 작업 영역,
좌측 모니터, 진단 펼침, 큰 출력 배율과 설정 불변성을 확인한다.
접힌 개별 컨트롤은 펼친 뒤 검사하되 실제 기본 공통 명령의 가시성도 반드시 검사한다.
Linux 통과를 실제 Windows 글꼴/DPI 통과로 대신하지 않으며 일반 푸시 자동 실행 정책은 바꾸지 않는다.

## 업로드와 검증 결과 분리

릴리즈의 exe 생성은 다운로드 업로드와 독립적인 필수 검증이다. 사전 검증에서는
exe 생성도 선택 사항이며, Actions 아티팩트는 기본 비활성화다.
수동 실행에서 `upload_exe`를 선택한 경우에만 1일 보관하며 SHA/시도별 이름을 사용한다.
업로드 단계만 `continue-on-error`로 두고 summary에 테스트·통합·빌드·업로드 결과를 각각 남긴다.
quota/전송 오류는 경고이며 테스트나 빌드 실패를 성공으로 바꾸지 않는다.
태그 릴리즈의 Release 자산은 이 선택 업로드와 별도 경로다.

## 무료 한도 정책 변경 검증

- 2026-10-18: 일반 푸시 트리거 제거, 수동 build_exe 기본 OFF,
  upload_exe 선택 시 빌드 수행, 릴리즈 필수 게이트 및 모든 게시 조건을 로컬 YAML 검사로 검증했다.
- `tests/test_windows_ci.py`: 기존 정확한 SHA/필수 단계 누락·실패·취소 검사,
  업로드 quota 분리와 공개 데이터 보존 검사를 유지한다. 테스트 경계·정리·누수 assertion은
  변경하지 않았다. 이번 로컬 실행은 21개 통과했다.
- 최종 관련 검사: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
  tests/test_windows_ci.py tests/test_release_notes.py tests/test_release_notes_trigger.py -q --tb=short`
  결과 **33 passed (6.27초)**. `git diff --check`도 통과했다.
- 사용자에게 전달된 Actions 무료 한도 차단 때문에 이번 변경의 실제 Windows 회귀,
  네이티브 검사 및 PyInstaller exe 빌드는 실행하지 않았다. 워크플로 구조 검사는 실제
  GitHub 실행이나 Windows 통과의 증거가 아니다. 한도 소비를 위한 수동 실행도 하지 않았다.
- 앞선 제품 `5a452fd`의 실행 `39052932417`은 QA 기준 runner_id=0, steps=[]였다.
  이전 로컬 검사나 펠롬 제품의 성공을 해당 제품의 Windows 성공으로 대신하지 않는다.
- 한도 차단은 릴리즈 게이트를 우회하지 않는다. 복구 전에도 로컬 QA는 진행할 수 있지만
  태그 릴리즈의 필수 테스트/네이티브/빌드가 실행·성공하지 않으면 게시되지 않는다.
  이번 작업에서 태그 생성·푸시·릴리즈는 하지 않았다.

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

### Qt 네트워크 경계 수정 후 독립 QA

- `4b37916`의 [후속 QA](qa/Qt네트워크_테스트경계_수정_독립QA_20261017.md)에서
  `15c916dfe3959e88228c31cd28c166b5c6f1b1e6`의 정확한
  [Windows 자동 실행 39015421233](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39015421233)
  로그와 단계 성공을 확인한 결과를 받았다. 개발 세션의 직접 API 조회 성공과 구분한다.
- 격리 회귀 **1412 passed, 1 skipped, 7 deselected (520.91초)**,
  실제 네이티브 통합 **7 passed (19.75초)**, exe 빌드 **success**다.
  Qt 네트워크 200회와 메인 창 20회 검사도 실행됐다. 이전 접근 위반은 재발하지 않았다.
- skip은 기존 비Windows 전용 검사다. 선택적 업로드만 생략됐으며 빌드 누락이 아니다.
  이번 경계 수정의 새 결함은 발견되지 않았지만 크래시의 근본 원인 확정과는 구분한다.
- 제품·테스트·CI 파일이 위 검증 SHA와 같음을 확인했다. 문서만 갱신하므로 재실행하지 않는다.
  도르카 자체 창 가림 P2는 여전히 미해결이며 이번에는 릴리즈 명령을 제공하지 않는다.
