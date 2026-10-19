# 자원 등록 fixture 수정 후 독립 QA

- 검증일: 2026-10-19
- 대상: `8d81372eaa00aa62ed18ed1a29597e6f78c6db2f`
- 앞선 보고서: [전투 보조 조작 정돈 독립 QA](전투보조_조작정돈_독립QA_20261019.md).
- 결론: 앞선 테스트 준비 결함은 해결됐다. 이번 검증 범위에서 추가 결함은 확인하지 못했다. 제한된 베타 기준으로 릴리즈 명령 제공 가능.

## 소스 확인

커밋 이력/메시지 대신 정확한 소스 트리를 비교했다. 앞선 QA 공유본 `6b5d50e` 대비 변경은 아래 세 파일뿐이며 제품·설정 스키마·워크플로·공개 노트는 동일하다.

- `tests/test_resource_integration.py`: 외부 경계를 먼저 대체하고 `save_boxes()`와 두 컨트롤러의 실제 `_accept_region()`으로 fixture를 준비한다. 등록된 메모리/디스크/버튼 상태 일치 검사도 추가했다.
- `tests/test_resource_common_settings.py`: 자동찾기 중 지정 해제 테스트에서 클릭 전 버튼 활성, 해제 후 메모리/디스크 영역 제거, 버튼 비활성, 후보 승인 없음 확인을 유지/추가했다.
- `docs/resource-fixture-registration-fix.md`: 원인 및 개발 검증 기록.

강제 `setEnabled(True)`, 제품 비활성 정책 제거, 실패 skip, assertion 약화는 없다.

## 실행 결과

Linux PySide6 offscreen 및 기존 외부 경계 격리에서 **84개 통과, 실패 없음**. 세 실행은 서로 다른 probe 모듈명 충돌을 피하도록 별도 프로세스로 실행했다.

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest \
  tests/test_resource_integration.py tests/test_resource_common_settings.py \
  tests/test_resource_null_sections.py tests/test_setup_common_resources.py \
  docs/qa/assets/interaction_polish_20261019/probe.py \
  -q --tb=short --show-capture=no
```

**78 passed / 28.91초**. 일반 회귀 74개와 조작 정돈 독립 검사 4개를 포함한다.

- 원래 실패한 해제 중 자동찾기와 동일 시나리오의 새 MainWindow 프로세스 검사 모두 통과.
- 자원 표시/알림 조합, 부분 성공·취소·로그아웃·종료·쓰기 실패·영역 동시 변경·손상/null 설정 복구·자동설정 검사 통과.
- 버프 이름 편집 중 기준 버프 전환 2개, 커스텀 선택/적용/시작 및 저장 실패/다른 이름 저장 분리, 실제 도르카 등록 후 탐색 중 해제 대조 검사 통과.

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest \
  docs/qa/assets/common_resource_settings_20261018/probe.py \
  -q --tb=short --show-capture=no
```

**2 passed / 0.81초**. 변경 fixture를 사용하는 기존 공통 자원 독립 검사.

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest \
  docs/qa/assets/dialogue_registration_fix_20261018/probe.py \
  -q --tb=short --show-capture=no
```

**4 passed / 1.86초**. 변경 fixture를 사용하는 교차 기능 독립 검사.

소스 차이의 `git diff --check`도 통과했다.

## 이전 결과와의 관계

- 앞선 UI QA의 511개 통과는 동일한 제품 소스의 검증 자료로 재사용한다. 이번에 511개 전체를 다시 실행했다고 주장하지 않는다.
- 앞선 2개 실패는 동일 fixture 결함의 중복 실행이었다. 둘 다 이번 일반 회귀에서 성공했다.
- `scripts/qa_interaction_clear_gate_20261019.py`는 수정 전 fixture의 비활성 상태를 먼저 단정하는 역사적 재현 자료다. 수정된 fixture에서 그 전제가 성립하지 않으므로 현재 합격 게이트로 사용하지 않으며 원본은 보존했다. 원래 실패한 일반 회귀와 실제 등록 대조 검사를 직접 실행해 해결 여부를 확인했다.
- 제품 소스가 동일하므로 이전 8개 화면 렌더·폭·둘러보기·잠금·저장·종료 검증도 재사용한다.

## 제한과 배포 조건

- Windows 네이티브·exe·실게임·DPI·멀티모니터·장시간 실행은 이번 환경에서 실행하지 않았다. 이번 결과는 Windows 통과나 배포 성공을 뜻하지 않는다.
- 제작자 잡담이 실제 PC에서 계속 막히는 현상은 이번 fixture 수정으로 해결됐다고 주장하지 않는다. 앞선 실제 창 영역/차단 프로그램 진단 수정의 라이브 확인 범위로 남는다.
- Windows 수동 실행을 추가 요청하지 않는다. 실제 태그 릴리즈의 전체 회귀·네이티브·exe 필수 게이트를 유지한다.
- 확인 시점 원격 최신 태그는 `v0.4.90`, 다음 태그는 `v0.4.91`, 공개 노트 맨 위도 `v0.4.91`이다. 제품 노트 변경은 필요 없다.
- 이 후속 QA 문서만 main에 공유한다. 제품/기존 테스트를 임의로 수정하지 않으며 태그 생성·푸시와 릴리즈는 사용자가 직접 한다.
