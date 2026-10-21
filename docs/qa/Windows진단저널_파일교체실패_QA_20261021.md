# Windows 진단 저널 파일 교체 실패 QA

- 날짜: 2026-10-21 (한국 시간).
- 실제 실행: [39617505288](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39617505288), attempt 1, SHA `4dbea247b6d21b9ea5390f79d915f3dfdd21ca93`.
- 실패 job: `119282385060`. 현재 main `0ac60525f829a78deb982cc5d8604ac1c4cd5307`에서도 아래 두 코드 경로가 동일함을 확인했다.
- 결론: **새 진단 코드의 Windows 파일 교체 예외로 검증이 중단됐다. 배포 차단이며 수정 전 전체 재실행/게시를 안내하지 않는다.** QA는 제품·기존 테스트·워크플로를 수정하지 않았다.

## 1. 18분 대기의 실제 상태

| 시각 (한국 시간) | 결과 |
|---|---|
| 23:31:14 | 전체 workflow 시작 |
| 23:31:38 | Windows validate job 시작 |
| 23:32:18 | 격리 회귀 시작 |
| 23:33:02 | 진단 저널 교체 중 `PermissionError` / pytest `INTERNALERROR` 발생 |
| 23:33:08 | 격리 회귀 실패, 외부 프로세스 종료 코드 1 |
| 23:33:15 | validate job 종료, `completed/failure` |
| 23:50~51 조회 | 전체 run은 `in_progress`였지만 반환된 job들은 request 성공/validate 실패로 이미 종료 |
| 23:51:24 | 전체 run도 `completed/failure`로 갱신. 후속 API 재조회로 확인 |

**회귀가 18분 동안 계속 실행된 것이 아니다.** 검증 job은 시작 약 1분 37초 뒤 실패했다. 전체 run의 상태가 남아 있는 이유는 미확정이며, job의 확정 실패를 정상 진행이나 단순 대기로 안내하지 않는다.

현재는 전체 실행도 실패로 끝났으므로 추가 대기·취소 조작은 필요 없다.

네이티브 검사·exe 빌드·후보 보관은 `skipped`다. 진단 수집/업로드만 성공했고 `regression-diagnostics-39617505288-1`(약 12KiB)이 남았다. `117 passed in 48.04s`는 중단 전 일부 사례 결과이며 전체 통과가 아니다.

## 2. Confirmed Bug: 진단 교체 실패가 pytest hook 밖으로 전파

- 심각도: **높음 / 배포 차단**.
- 발생 조건: Windows 병렬 검사 중 진단 진행 저널의 `.tmp` → `.json` 교체가 한 번이라도 거부될 때.
- 사용자 영향: 앱 기능 검사를 끝까지 수행하지 못하고 CI 자체가 중단된다. 아직 앱 사용자 기능의 오작동으로 확인된 것은 아니다.
- 확인된 원인: `test_support/progress.py:43`의 `_REPLACE(temporary, self.path)`에 실패 처리 경계가 없다. `pytest_runtest_logreport()`(:94)에서 예외가 전파돼 pytest/xdist `INTERNALERROR`로 전체 검사를 종료한다.
- 실제 로그 요약(절대 경로 제외):

```text
test_support/progress.py:94 in pytest_runtest_logreport
    _state.emit(outcome=report.outcome)
test_support/progress.py:43 in emit
    _REPLACE(temporary, self.path)
PermissionError: [WinError 5] Access is denied:
    controller-2600.tmp -> controller-2600.json
117 passed in 48.04s
Process completed with exit code 1.
```

### 독립 재현

`scripts/qa_progress_replace_failure_20261021.py`는 실제 Journal과 report hook을 호출하며 `_REPLACE`의 첫 호출에만 일시적인 `PermissionError`를 주입한다. Windows 커널을 재현했다고 설명하지 않는다. 실패 처리 경로를 Linux에서 결정적으로 확인하는 fault injection이다.

```bash
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q scripts/qa_progress_replace_failure_20261021.py --tb=short
```

결과: **1 failed, 1 passed (0.05초)**. 무경합 report 저장은 통과하고, 일회성 거부는 실제 Windows와 같은 `pytest_runtest_logreport → emit → _REPLACE` 경로에서 hook 밖으로 전파된다. 실패를 xfail/skip으로 숨기지 않았다. 이전 Linux QA는 이 Windows 파일 잠금 실패를 포함하지 못했다.

## 3. Highly Likely Bug: 감독 reader와 journal writer의 Windows 공유 충돌

- 심각도: 높음. 위 확정 실패를 일으키는 유력한 충돌 경로다.
- 발생 조건: 감독 프로세스가 `scripts/run_regressions.py:90`의 `path.read_text()`로 JSON을 읽는 순간 writer가 같은 목적지를 `os.replace()`한다.
- 기술적 근거: Windows에서는 읽기 핸들이 삭제 공유를 허용하지 않으면 열린 목적지의 교체가 거부될 수 있다. 독자·기록자가 별도 프로세스에서 반복 접근하며 실제 실패도 그 목적지 교체에서 발생했다. POSIX의 열린 파일 교체 성공을 Windows 보장으로 사용하면 안 된다.
- 미확정: 해당 순간의 Windows 핸들 소유자/공유 플래그를 직접 캡처하지는 못했다. 외부 파일 접근 등 다른 일시 거부 원인까지 배제한 것은 아니다. 원래 50분 정체의 원인으로 소급하지 않는다.

## 4. 개발 수정 요구와 완료 기준

1. 자체 reader/writer의 Windows 교체 충돌을 제거하거나 유한 재시도·backoff로 처리한다. 단순 in-process mutex는 별도 감독 프로세스를 보호하지 못한다. JSON 원자성·부분 파일 방지·상한을 보존한다.
2. 일시적인 진단 실패를 pytest hook의 무처리 예외로 내보내지 않는다. 영구적인 진단 실패도 조용히 무시해 정상 배포하지 말고, 제한된 별도 실패 통지/감독 경로로 명확한 인프라 실패를 남긴다. 무한 재시도·기록 없이 진행 시각만 갱신하는 방식은 금지한다.
3. JSON 교체뿐 아니라 event journal 회전·읽기/쓰기·진단 수집의 동시 접근 경계를 확인한다. 진단 실패 때문에 원래 테스트 실패 코드/timeout·소유 자손 정리 근거를 잃지 않게 한다.
4. 위 일회성 거부 재현, 영구 거부의 bounded 실패, reader가 삭제 공유 없이 목적지를 실제로 연 동안의 Windows 교체, xdist 중 동시 읽기/기록·정상 전체 검사를 추가/실행한다. Windows 네이티브 경합을 Linux mock 통과로 대체하지 않는다.
5. 테스트/진단 assertion 완화·watchdog 제거·관리자 권한 실행 권유·Windows 시간 제한 확대로 해결하지 않는다. 이는 사용자의 사용법이나 무료 한도 초과가 아니라 확인된 코드 실패다.
6. 개발 수정 후 관련 검사와 후속 독립 QA를 먼저 진행한다. 다음 전체 Windows 실행은 수정본 한 번으로 모으며 이전 실패 실행을 무작정 rerun하지 않는다.

QA 자료만 커밋·푸시한다. 태그/릴리즈를 만들거나 사용자를 대신해 workflow를 실행하지 않는다. 이번 실패가 해결되기 전에는 앞선 v0.10.1 준비 명령을 재실행 안내로 사용하지 않는다.
