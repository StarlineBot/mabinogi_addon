# 헤일로 알림음 경로 검사 수정

## 원인과 변경

QA 원격 `0bc244e`를 받아 Windows validation 실행 `39284772652`의 보고를 확인했다.
보고된 결과는 1 failed, 2064 passed, 1 skipped, 15 deselected / 647.78초이며,
실패는 `test_dedicated_notifier_does_not_interrupt_other_sound`의 경로 문자열 비교다.
이 실행에서는 네이티브 검사·exe 빌드·후보 업로드가 실행되지 않았다.

Qt의 `QUrl.toLocalFile()`은 Windows에서도 슬래시를 반환할 수 있다.
Windows Path의 역슬래시 표현과 문자열로 비교하면 같은 파일도 다르다고 판단한다.
`tests/test_halo_live.py`에서 실제 결과를 Path로 감싸 전체 경로로 비교하도록 수정했다.
다른 파일명과 같은 파일명의 다른 디렉터리는 거부하는 대조 검증도 추가했다.
기존 독립 재생기·소리 OFF 시 다른 재생기 유지·finally 정리는 보존했다.
PureWindowsPath 검사로 두 표기 차이와 경로 동등성/비동등성을 Linux에서도 재현한다.
제품 코드나 알림음 파일, 재생 동작은 변경하지 않았다.

## 검증 범위

```bash
env PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_halo_live.py tests/test_halo_presentation.py -q --tb=short
```

결과: **26 passed / 39.19초**. skip이나 assertion 완화는 없으며 전체 경로 일치를 유지한다.

이번 실행은 Linux Qt 및 격리된 오디오 경계의 회귀다. 실제 Windows 전체 검사·네이티브 검사·
exe 빌드·알림음 청취는 미검증이며 이전 실패 실행을 통과로 대체하지 않는다.
Windows Actions·태그·릴리즈를 실행하지 않았다. 후속 QA 후 Windows 검증을 할 때는
실패한 이전 SHA 재실행이 아니라 수정이 포함된 최신 main으로 새 후보를 검증해야 한다.
