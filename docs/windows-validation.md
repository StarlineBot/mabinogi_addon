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
`pyproject.toml`, `uv.lock`, `scripts/windows_ci.py` 변경 전체다. 따라서 시작·종료·네이티브
의존성·패키징 변경을 포함한다. 비교 기준이 없는 수동 실행/첫 푸시도 빌드한다.
테스트만 변경한 푸시는 회귀·통합 검사를 실행하되 exe 빌드는 생략할 수 있다.

푸시 후 개발 세션에서 다음을 실행한다. SHA는 실제 전체 커밋 해시로 치환한다.
빌드 대상 변경이 없을 때만 `--require-build`를 빼도 된다.

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
- 현재 클라우드의 Actions API 조회는 `Forbidden`이다. 따라서 Windows 테스트·exe 빌드의
  실제 원격 성공은 아직 확인하지 못했으며 QA 요청 조건을 충족했다고 판단하지 않는다.
