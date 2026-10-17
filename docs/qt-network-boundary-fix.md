# Qt 네트워크 테스트 경계 보완

## 근거와 판정

- 2026-10-17, 제품 `1b7c8a4`의 독립 QA를 `ab08af8`에서 받았다.
- 원본: [통합 및 재시작 수정 QA](qa/도르카_투아림_통합_및_재시작수정_독립QA_20261017.md).
- Windows 실행 `39010841429`의 접근 위반 위치는 `DialogueFeed.__init__` 안의
  `QNetworkAccessManager(self)` 생성이다. 근본 원인은 아직 확정하지 않았다.
  앞선 테스트의 메모리 손상이나 Qt 네이티브 수명 문제를 배제한 상태가 아니다.
- 별도로 확인한 테스트 경계 결함: 일반 회귀에서 `DialogueFeed.start`만 막고 관리자 생성은
  실제로 수행했다. 생성 함수를 추적하는 새 회귀를 수정 전에 실행해 **1 failed (2.99초)**로 재현했다.

## 변경

- 일반 회귀의 대사 관리자 생성도 QObject 기반 대체로 분리했다. 대체의 `get`은 외부 시도
  기록과 assertion을 남긴다. 기존 대사 응답/시간 제한/크기 제한/취소/캐시 검사는 유지한다.
- `tests/test_dialogue_network_lifecycle.py`를 `windows_integration` 단계에 추가했다.
  실제 QNetworkAccessManager/QNetworkReply/QTcpServer와 제품 DialogueFeed로
  200회 응답/진행 중 취소를 번갈아 검사한다. 서버는 127.0.0.1만 사용하며 외부 주소에
  연결하지 않는다. 각 회차 타이머 정지, 응답 없음/성공 구분, 캐시 바이트, 반복 shutdown,
  DeferredDelete 이후 관리자·응답의 실제 네이티브 파괴를 확인한다.
  루프백 HTTP 검사이므로 외부 HTTPS/TLS 및 실제 대사 서버 가용성을 검증한 것은 아니다.
- 같은 별도 통합 단계에서 실제 MainWindow 생성/표시/종료/파괴도 20회 반복한다.
  이때 캡처·오디오·대사 다운로드는 격리하되, QA가 지목한 메인 창 내부의
  QNetworkAccessManager 생성은 실제 네이티브 경로로 실행하고 해제까지 확인한다.
  매 반복 번호를 캡처 밖 로그에 남겨 크래시 때도 마지막 생성 회차를 알 수 있게 한다.
- main/태그 회귀·통합 실행은 `-vv -ra`로 테스트 ID와 순서를 남긴다.
- 제품 코드, 의존성, 기존 QA 재현, 누수 assertion, 실패 기대값은 변경하지 않았다.
  새 skip이나 재시도 통과 정책을 추가하지 않았다.

## 검증 상태

- 경계/대사/탐색/CI 관련 회귀: **107 passed (89.24초)**.
- 실제 Qt 네트워크 200회, 실제 메인 창 20회 및 CI 계약 검사:
  **22 passed (16.99초)**. 두 반복 검사는 각각 1개 테스트 내부의 반복이며
  회차를 독립 테스트 수로 합산하지 않는다.
- 수정하지 않은 원본 재시작 QA와 새 통합 독립 probe 재실행:
  **1 failed, 17 passed (27.81초)**. 실패는 기존 자체 창 가림의 runtime-recovery다.
- 전체 격리 회귀: **1413 passed, 6 deselected, 3 warnings (1009.92초)**.
  `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -ra -m 'not windows_integration' --tb=short`.
  deselected는 수집 당시 별도 네이티브 검사이며 일반 회귀 실패를 제외한 것이 아니다.
  이 실행 도중 추가된 메인 창 통합 검사 1조건과 최종 CI 계약 assertion은 위 22개 실행에서
  별도로 확인했다. 일반 회귀 대상이나 제품 소스는 실행 중 변경하지 않았다.
  경고 3개는 기존 toast 테스트의 QMouseEvent 생성자 폐기 예고다.
- 푸시 직후 이 개발 세션의 Actions API 조회는 `Forbidden`으로 실패했다.
  이후 `4b37916`으로 받은 [후속 독립 QA](qa/Qt네트워크_테스트경계_수정_독립QA_20261017.md)에서
  정확한 제품 SHA `15c916dfe3959e88228c31cd28c166b5c6f1b1e6`의
  [자동 실행 39015421233](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39015421233)
  실제 로그와 단계 성공을 확인한 결과를 받았다.
- 후속 QA의 Windows 실행 결과: 격리 회귀 **1412 passed, 1 skipped, 7 deselected (520.91초)**,
  네이티브 통합 **7 passed (19.75초)**, exe 빌드 **success**다.
  Qt 네트워크 200회와 메인 창 20회가 실제 Windows 단계에서 실행됐다.
  skip은 기존 비Windows 전용 DWM fallback 검사이고 선택적 업로드만 생략됐다.
- 이번 문서 갱신 전 트리와 위 SHA 사이의 제품/테스트/검증 스크립트/의존성/워크플로
  차이가 없음을 파일 비교로 확인했다. 문서만 갱신하며 같은 제품 검증을 재사용한다.

Windows 검증 실패와 빌드 미검증 상태는 후속 QA에서 해소됐다. Linux 통과를 Windows 통과로
대신한 것이 아니며, 이 개발 세션에서 새로 Actions API 로그를 조회했다는 뜻도 아니다.
접근 위반은 해당 Windows 실행에서 재발하지 않았지만 네이티브 크래시의 근본 원인은 미확정이다.
남은 도르카 자체 가림 문제 때문에 전체 QA 통과나 릴리즈 가능으로 판정하지 않는다.

## 남은 도르카 문제

통합 기능과 옛 영역의 다른 숫자 오인 수정은 독립 QA에서 확인됐지만, 자체 창이 도르카
장식을 가린 입력에서 실행 중 재탐색이 실패하는 기존 경로는 여전히 남아 있다.
이번 네트워크 경계 변경은 캡처/검출 경로를 바꾸지 않으며 해당 문제를 해결했다고 주장하지 않는다.
실제 Windows 실캡처 및 당시 사용자 --/15 원인은 미확정이다.
