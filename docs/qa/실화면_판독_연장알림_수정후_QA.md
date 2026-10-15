# 실화면 판독 및 연장 알림 수정 후 독립 QA

검증일: 2026-10-15. 제품 소스: `e9923cfd30bb75031c89bf2c907b7cb87bff3e26`.
커밋 이력/메시지는 조회하지 않았다. 현재 트리와 이전 QA 트리의 파일 내용만 비교했다.
검증용 로컬 미러의 소스, 테스트, 자산, 테스트 지원 코드, 기존 QA 스크립트 등
825개 파일을 원격 Git blob과 대조했고 불일치/누락은 없었다.

## 결론

검증 가능한 변경 범위에서 새 배포 차단 결함을 발견하지 않았다. 원래 디버프 누락과
알림 경계 재현은 스크립트/원본 이미지를 바꾸지 않은 상태로 모두 통과했다.
Windows의 정확한 제품 SHA에 대한 회귀, 네이티브 통합과 exe 빌드도 성공했다.
아래 성능 및 라이브 미검증 범위를 남긴 상태로 제한된 베타 배포 기준을 충족한다.
QA에서는 제품 구현과 제품 테스트를 수정하지 않았다.

## 원래 실패와 수정 확인

- `DEBUFF-LIVE-QA-01`: 원본 2장과 자동 등록 영역, 1px 경계 변화에서 발생한 누락 6건이
  해소됐다. 템플릿만 16px로 준비하고 캡처 원본은 축소하지 않는 경로를 확인했다.
  원본 크기 회색 매칭은 위치 후보에만 쓰고 최대 4개 원본 컬러 패치로 최종 검증한다.
  전역/아이콘별 임계, 확인 시간, 재표시 유예와 게이팅은 유지됐다.
- `BUFF-EXTEND-QA-01`: 연장 후보의 첫/두 번째 알림 경계 2건이 해소됐다.
  후보가 바뀌거나 OCR이 없어도 보류 시각이 갱신되지 않는다. 정상 판독으로 돌아오면
  즉시 해제하고, 기한 만료 시 아직 필요한 알림은 소비하지 않고 발화한다.
- 일반 시간 추가와 기존 분 유실 방어, 연장 후 다음 임박에서 재알림이 유지됐다.
- 원래 보고된 연속 라이브 깜빡임과 다른 테스터가 들은 추가 소리의 실제 원인은
  당시 설정/연속 입력이 없어 확정하지 않았다. 재현 경로 해소와 구분한다.

## 시작 화면 누적 변경

이번 제품 소스에는 기존 한 화면 대신 단계별 안내를 기본으로 삼는 변경도 포함돼 있다.
기존 시청 기록과 완료된 설정이 있어도 로그인하고 명시적 `skipSetup`이 없으면
단계별 안내가 뜨며, 명시적 숨김/비로그인은 존중한다. 설정의 진입 버튼도 단계별 안내다.
기존 영역과 시청 기록을 삭제하지 않는 것, 노트 처리 후 안내를 활성화하는 것을 독립 확인했다.

과거 `scripts/qa_setup_v2.py` 전체 실행은 **9 passed, 1 failed, 2 warnings (4.71초)**였다.
실패한 `test_skip_checkbox_is_synchronized_when_returning_to_existing_setup`는 설정 버튼이
예전 한 화면을 열어야 한다는 옛 요구를 assertion으로 가지고 있다. 이는 사용자의
새로운 시작 화면 변경 요청과 반대이므로 제품 결함이나 전체 통과로 보고하지 않는다.
원래 스크립트를 삭제/수정/skip하지 않았다. 새 정책을 독립 스크립트의 3개 사례로 재검증하여
단계별 재진입, skip 체크, 로그인과 기존 영역 보존이 모두 통과했다.

## 실행 결과

```bash
QT_QPA_PLATFORM=offscreen uv run pytest scripts/qa_debuff_live_detection.py scripts/qa_debuff_flicker.py scripts/qa_buff_extension_alert.py -q
QT_QPA_PLATFORM=offscreen uv run pytest -p scripts.qa_setup_audio_boundary scripts/qa_live_tracker_followup.py -q
QT_QPA_PLATFORM=offscreen uv run pytest -m 'not windows_integration' -q
```

- 원본 독립 재현/기존 깜빡임: **32 passed (7.89초)**.
- 추가 독립 검증: **11 passed (3.96초)**. 불규칙/소수 단조 시계의 보류 상한 8건,
  완료된 설정과 시청 기록이 있는 사용자의 새 시작 정책 3건이다.
- Linux 전체 회귀: **779 passed, 1 failed, 3 deselected, 3 warnings (177.00초)**.
  실패는 `tests/test_discord_auth.py::test_login_end_to_end_returns_user`의 로컬 포트
  53123 바인드를 실행 샌드박스가 `Operation not permitted`로 막은 것이다.
- 같은 로그인 테스트를 로컬 네트워크 사용이 허용된 실행으로 변경 없이 다시 실행:
  **1 passed (1.02초)**. 실제 외부 인증 대신 테스트의 가짜 계정/토큰 콜백을 사용했다.
  전체 집합을 같은 권한으로 다시 실행한 것으로 합산하지 않는다.
- 기존 Qt 마우스 이벤트 경고 3건과 과거 QA의 mss API 경고 2건은 위 결과와 별도 표기했다.
  QThread 누수 검사와 assertion은 그대로 유지했다.

## Windows 확인

자동 main push 실행:
[Windows validation 38750992895](https://github.com/StarlineBot/mabinogi_addon/actions/runs/38750992895).
대상 SHA는 `e9923cfd30bb75031c89bf2c907b7cb87bff3e26`, job은 `116477030871`이다.

- Isolated regression: **779 passed, 1 skipped, 3 deselected, 3 warnings (188.53초)**.
- Native Windows integration: **3 passed, 780 deselected, 1 warning (1.53초)**.
- Verify exe build: 성공. `mabinogi-addon.exe` **123560805 bytes** 확인.
- Optional exe upload: 기본 OFF로 skipped. 테스트/통합/빌드가 skipped인 것은 아니다.
- validate job의 결론은 success이며 해당 SHA의 완료 단계를 직접 조회했다.

개발 세션의 Actions API `Forbidden`은 이 QA 세션에서는 발생하지 않았다.
사용자에게 수동 workflow나 재푸시를 요청하지 않았다.

## Potential Risk / P3: 성능 목표 잔여

`scripts.benchmark_debuff_matching --iterations 50`을 단일 OpenCV 스레드로 실행했다.
아래는 전체 회귀 종료 뒤 측정한 Linux 공유 실행 환경 수치이며 Windows 게임 부하 측정이 아니다.
50회/5회 워밍업 제외로 각 동일 입력에서 과거 기준선과 현재 틱을 비교했다.

| 사진 | 아이콘 수 | 과거 중앙값 ms | 현재 중앙값 ms | 현재 p95 ms |
|---|---:|---:|---:|---:|
| 213313 | 2 | 6.663 | 4.667 | 9.149 |
| 213313 | 8 | 27.355 | 13.478 | 22.457 |
| 213313 | 15 | 34.007 | 14.691 | 28.542 |
| 213734 | 2 | 10.751 | 4.047 | 9.299 |
| 213734 | 8 | 23.199 | 13.014 | 24.788 |
| 213734 | 15 | 54.968 | 25.822 | 37.655 |

동일 조건의 과거보다 중앙값은 줄었으나 8/15개 조건은 5ms 목표를 넘는다. 다수 아이콘을
추적할 때 게임 CPU 부하에 영향을 줄 가능성은 남는다. 기술적 경로는
`tracker/debuff_engine.py`의 `_best` 원본 매칭과 틱별 게이팅이다. 성능 최적화 전부터
목표 초과가 있었고 이번 자료로 Windows 자원 증가나 게임 방해를 확정하지 않는다.
재현은 위 벤치 명령으로 가능하며 실게임 CPU/FPS 및 긴 영역은 후속 라이브 측정 대상이다.

## 릴리즈 준비와 한계

원격 최신 태그 `v0.4.70`을 확인했다. 현재 추가 변경이 이미 배포된 v0.4.70 노트에
들어가 있어 새 항목 3개를 v0.4.71로 분리하고, v0.4.70 이하의 공개 노트를 태그의
원본 그대로 보존한다. 이는 노트 정리이며 실행 코드/제품 테스트 수정이 아니다.
위 Windows 결과는 동일 실행 코드에 재사용한다. 태그 생성과 실제 배포는 사용자 담당이다.
노트 분리 후 `tests/test_release_notes.py`도 **7 passed (0.31초)**였다.
v0.4.70 이하 내용이 실제 태그의 노트와 완전히 동일한지 문자열로 대조했다.

원본 2장 이외 UI 배율/아이콘 크기, 사용자 커스텀 템플릿, Windows 실제 소리 횟수,
장시간 메모리/핸들/게임 FPS는 미검증이다. 고정 16px 가정은 이번에도 남아 있다.
재현 통과/CI 성공을 모든 라이브 제보 해결이나 실제 배포 성공으로 확대하지 않는다.
