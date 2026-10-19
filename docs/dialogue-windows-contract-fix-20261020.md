# 잡담 Windows 검사 계약 보완

## 범위

통합 QA `d4ae00b`의 후속 두 항목을 수정했다. 제품 코드와 가림 판정,
헤일로 동작, 공개 정책은 변경하지 않았다.

- `tests/windows/test_dialogue_visibility.py`: 명시적 region이 없는 경우
  pywin32의 `GetWindowRgn` 예외를 받아 helper가 None을 반환하는 계약을 검사한다.
  `region_error`가 실제 `win32gui.error`의 이름이고 region_type은 없음을 확인한다.
  명시적 shape 사례는 여전히 오류가 없어야 하며 모든 경우 cleanup 오류를 금지한다.
  정보가 없다고 노출을 허용하지 않으며 보수적 차단은 그대로다.
- 같은 파일: `SetWindowRgn` 성공 직후 `PyGdiHANDLE.Detach()`로 Python 소유권을
  해제한다. 실패하면 기존 finally에서 정리하고, 성공하면 HWND가 소유한다.
  종료 시 region 해제와 창 정리, 100회 GDI 증가 검사를 유지한다.
- QA 모델에는 실제 pywin32의 `error` 클래스 export를 연결했다.
  원래 두 재현과 소유권 assertion은 그대로 유지했다.

## 실행 근거

수정 전 다음 독립 재현은 **2 failed / 4.29초**였다.

```bash
env PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_dialogue_windows_contract_20261020.py -q --tb=short --show-capture=no
```

수정 후 같은 두 재현과 region/가림 회귀를 함께 실행했다.

```bash
env PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest scripts/qa_dialogue_windows_contract_20261020.py tests/test_dialogue_window_region.py tests/test_dialogue_transparent_occlusion.py tests/windows/test_dialogue_visibility.py -q --tb=short
```

결과: **40 passed, 7 skipped / 13.30초**. 7개는 기존 Windows 전용 검사다.
실패를 skip하거나 누수 assertion을 완화하지 않았다. 독립 재현은 Windows API 계약 모델이며
실제 Windows 실행 결과가 아니다. 실제 HWND/GDI/프로세스 핸들, CEF 합성 환경과 exe 빌드는
이번 Linux 환경에서 미검증이다. Windows Actions·태그·릴리즈는 실행하지 않았다.
