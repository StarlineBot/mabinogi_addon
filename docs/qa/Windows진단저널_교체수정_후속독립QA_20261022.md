# Windows 진단 저널 교체 수정 후속 독립 QA

- 날짜: 2026-10-22 (한국 시간).
- 검증 소스: `7993e1fdcb56b113bd97e40d2791eb7262addf92`.
- 대상: [실제 Windows 실패와 원본 재현](Windows진단저널_파일교체실패_QA_20261021.md), [개발 수정 기록](Windows진단저널_교체실패_개발수정_20261021.md).
- 결론: **원래 일시적 교체 거부 재현은 수정 없이 통과했다. 소스·Linux 독립 실행 범위에서 새 배포 차단 결함은 발견하지 못했다.** 실제 Windows 파일 공유 경합·Job·exe는 아직 미검증이다. 아래 복합 장애의 감지 지연은 비차단 위험으로 구분한다.
- 제품·기존 테스트·워크플로·공개 노트는 QA에서 수정하지 않았다. 원격 실행 입력 1,139 blob의 로컬 SHA 대조 결과 누락·불일치 0건이다. 커밋 이력·메시지는 조회하지 않았다.

## 1. 원본 결함 수정 확인

`scripts/qa_progress_replace_failure_20261021.py`를 변경하지 않고 실행했다. 실제 Journal/report hook에서 첫 교체만 거부되는 원래 사례가 통과했다. 무경합 기준 사례도 함께 통과했다.

- `Journal.io()`는 최대 8회, 10/20/40/80/160/160/160ms의 유한 대기 후 끝난다. 임시 파일을 완성한 뒤 `os.replace`로 교체하는 원자성은 유지한다.
- 일시 거부가 해소되면 진행을 저장하고 계속한다. 영구 실패는 Journal을 실패 상태로 고정하며 가짜 진행 시각/파일 갱신을 중단한다. 단순 예외 무시로 성공을 반환하는 수정이 아니다.
- 실패는 제한된 오류 번호·종류·연산 이름의 별도 `.error`/stderr로 전달된다. 기존 pytest hook 밖으로 무처리 OSError를 전파하는 경로는 유한 I/O 처리로 감쌌다.
- 감독은 읽기에 성공한 snapshot만 최근 진행으로 인정한다. 지속 읽기 실패·저널 오류·수집 실패를 비정상 코드로 처리하며, 기존 테스트 실패/timeout 코드 보존 회귀를 직접 실행했다.
- 새 Windows 네이티브 검사 2건은 실제 `CreateFileW`로 삭제 공유 없는 읽기 핸들을 열고, 재시도 중 해제/계속 점유를 검사한다. 소스는 검토했으나 **여기서는 실행하지 못했다.** 새 플랫폼 검사의 Linux 제외를 기존 실패 skip으로 설명하지 않는다.

관련 위치: `test_support/progress.py`의 `Journal.io/fail/emit/pytest_sessionfinish`, `scripts/run_regressions.py`의 `supervise/relay_errors/collect`, `tests/test_windows_journal_contention.py`.

## 2. 직접 실행 결과

| 범위 | 독립 실행 결과 |
|---|---|
| 원본 QA 재현 2건 + watchdog/CI 관련 검사 | **60 passed**, 16.93초 |
| 실제 새 감독 프로세스·xdist 2-worker에서 watchdog/CI/Unicode 계약 검사 | **63 passed**, 11.71초, 감독 종료 코드 0 |
| 새 독립 재시도 한계·출력 캡처별 복합 장애 검사 | **3 passed**, 4.89초 |

앞의 두 묶음은 중복 사례를 포함하므로 고유 테스트 수로 합산하지 않는다. 개발 문서의 전체 Linux 2,524건을 이번 QA가 전체 실행한 결과로 인용하지 않았다.

```bash
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q scripts/qa_progress_replace_failure_20261021.py tests/test_regression_watchdog.py tests/test_windows_ci.py --durations=10 --tb=short
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m scripts.run_regressions --diagnostics /tmp/qa-journal-fix-7993 --case-timeout 180 --session-timeout 300 -- -n 2 -q tests/test_regression_watchdog.py tests/test_windows_ci.py tests/test_unicode_io_contract.py -m 'not windows_integration' --durations=10 --tb=short
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -s scripts/qa_journal_retry_followup_20261022.py --tb=short
```

새 독립 자료 `scripts/qa_journal_retry_followup_20261022.py`는 명시 실행 자료이며 정식 CI 수집에 추가하지 않는다. 실제 재시도 대기로 앞의 7회 거부 후 8회째 성공·오류 표식/거짓 실패 없음을 확인하고, 별도 자식 프로세스로 아래 회복 경로의 제약을 관측했다. 합성 오류는 파일 I/O 경계에만 주입했으며 Windows 커널을 재현했다고 주장하지 않는다.

## 3. Potential Risk: 이중 통지 불가 시 감지 지연 (낮음 / 비차단)

- 발생 조건: Journal 저장이 계속 거부되고 `.error` 파일도 만들 수 없으며, 기본 pytest fd 출력 캡처가 stderr 통지를 가린 상태에서 해당 테스트가 계속 멈춘다.
- 사용자 영향: 잘못된 성공/게시가 아니라 **실패 원인 분류와 중단이 늦어진다.** 현재 CI의 개별 180초 상한까지 기다렸다가 진단 I/O 오류 대신 일반 사례 timeout으로 표시될 수 있다. 앱 사용자 데이터나 게임 기능의 결함으로 확정된 것은 아니다.
- 기술적 원인: `Journal.fail()`의 `_WRITE(2, ...)`도 기본 fd 캡처 대상이다. 기존 개발 검사의 marker 불가 사례는 `-s`를 사용하므로 기본 캡처 상황을 대신하지 못한다. 개발 기록 역시 캡처를 끈 검사임을 구분하고 있다.
- 재현/결과: 독립 자식 실행에서 파일 쓰기와 교체를 모두 거부한 뒤 `Event.wait()`로 멈췄다. 기본 캡처는 **3.268초 / 코드 124 / case timeout**, `-s`는 **0.951초 / 코드 3 / diagnostic infrastructure failure**였다. 합성 3초 상한은 재현용이고 CI의 180초를 바꾸지 않았다.
- 비차단 근거: 두 실행 모두 비정상 종료하고 소유 검사 트리 정리 경로를 거쳤다. 검증을 통과하거나 실패 후보를 게시하는 경로는 확인되지 않았다. 원래 일시적인 파일 교체 거부는 위 재시도로 회복된다.
- 후속 개선: 이 복합 장애까지 즉시 구분해야 한다면 pytest 캡처와 독립된 오류 전달 경계를 마련하고 기본 캡처 조건으로 검사한다. 이를 위해 기존 테스트/누수 검사를 완화하거나 원시 stderr 전체를 공개 업로드하지 않는다.

## 4. Windows·배포 경계

- 이번 소스의 실제 Actions 기록은 조회 시 없었다. 이전 실패 실행 `39617505288`/publish skipped는 새 소스의 Windows 성공이 아니다.
- 실제 Windows 삭제 공유 경합·일시 해제/영구 점유, 중첩 Job·자손 종료, 콘솔/취소, 진단 아티팩트와 exe 빌드는 이 Linux 환경에서 실행하지 못했다.
- 이전 50분 이상 정체의 근본 원인은 여전히 미확정이다. 원본 로그의 WinError 5 실패 경로를 보완한 이번 수정과 혼동하지 않는다.
- 함께 올라온 블랙박스 자료는 기획 문서이며 이번 제품 변경은 CI 진단 코드다. 녹화/인코딩/수집 기능을 구현·QA 완료한 것으로 안내하지 않는다.
- 개발/공개 저장소에서 `v0.10.1` 태그가 없고 공개 노트 맨 위 버전이 v0.10.1임을 확인했다. 새 차단 문제는 발견하지 못했으므로 사용자가 선택하면 아래 한 번으로 수정본의 전체 Windows 격리 회귀·네이티브 검사·exe/후보 보관을 검증하고 **성공한 경우에만** 동일 파일을 게시한다.

```powershell
gh workflow run windows.yml --repo StarlineBot/mabinogi_addon --ref main -f version=0.10.1 -f mode=validate-and-publish
```

별도 사전 verify-only를 반복하라는 안내가 아니다. 에이전트는 workflow·태그·게시를 실행하지 않았다. QA 자료만 커밋·푸시한다.
