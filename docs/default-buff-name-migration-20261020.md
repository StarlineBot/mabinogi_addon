# 기본 버프 이름 이관 및 큰 글꼴 목록 폭 수정

2026-10-20 개발 수정 기록. 기준 소스는 `703c5ce`이며
[후속 QA와 추가 요청](qa/헤일로개발과_잡담로그_통합QA_20261020.md)을 처리한다.
기존 투어·잡담의 후속 독립 QA 확인은 유지하며, 이번 수정은 다시 후속 확인 대상이다.

## 기본 버프 이름 1회 이관

- `catalog.DEFAULT_BUFF_NAMES`의 14개 기본 ID만 대상으로 한다. 저장된 `name`이 해당 ID와
  정확히 같은 경우만 한글 기본 이름으로 바꾼다. 빈 이름, 다른 한글/영문 별칭, 추가 버프는 보존한다.
- dataclass로 설정을 다시 만들지 않고 원본 JSON의 대상 `name` 필드만 수정한다.
  목록 순서와 삭제/숨김 상태, 알림/시간 표시, 사용자 이미지, 다른 섹션과 미지 필드를 보존한다.
- `defaultBuffNamesKoreanMigrated: true` 표식과 이름 변경을 기존 원자 저장 함수의 한 번의
  교체로 저장한다. 성공 표식이 있으면 다시 저장하거나 이름을 변경하지 않는다.
- `MainWindow`의 새 설치 기본값 초기화 후, 창 위치 복원/기존 버프 설정과 UI를 읽기 전에 실행한다.
  첫 화면의 기준 버프 패널/일반 목록이 같은 한글 이름을 사용한다. 새 설치 기본 선택도 유지한다.
- 정상 문서와 복구 문서를 찾지 못하면 표식만 있는 새 문서를 만들지 않는다.
  쓰기 실패도 표식을 남기지 않고 경고만 기록해 다음 실행에서 재시도한다.
- 설정 복구 읽기를 공유 helper로 추출해 없는 문서와 유효한 빈 dict를 구분했다.
  JSON 문법 오류·잘못된 UTF-8·dict가 아닌 루트는 기존 `.bak` 복구 경로로 보낸다.
- 복구 중 쓰기 실패가 발생하면 정상 백업까지 잃는 기존 저장 경계를 보완했다.
  손상된 본 파일을 `.bak`로 덮어쓰지 않는다. 정상 본 파일의 직전 버전 백업과 fsync/원자 교체는 유지한다.
- 임시 설정에 14개 이름·혼합 이름·사용자 항목/미지 필드를 넣어 대상과 전체 보존을 검사했다.
  fsync와 최종 replace 실패를 주입해 원본/표식 상태와 정상 재시도를 확인했다.
  손상 본 파일+정상 백업에서도 실패/재시도를 확인했고, 이관 후 ID 이름으로 다시 바꾼 값도 유지됐다.
  실제 MainWindow 최초 로드/종료/재실행에서 기준 버프와 일반 이름을 확인했다.

## 목록 1px 가로 스크롤

- QA 원본은 수정 전 **1 passed, 1 failed / 1.41초**였다. 실패 값은 28px 글꼴에서
  `(폭 186, viewport 184, 항목 힌트 185, 스크롤 최대 1)`이었다.
- 글자 advance에 수동 여백을 더하던 계산을 제거했다. 두 계산기의 모든 이름을 가진 임시 모델과
  실제 목록의 delegate/style option으로 크기 힌트를 구하고, 프레임 두께를 더해 공통 폭을 확보한다.
  스크롤바를 숨기거나 고정 숫자 여백을 추가하지 않는다. 임시 모델은 함수 종료 후 해제된다.
- 12 → 20 → 28 → 12px에서 양쪽 폭은 **136 → 140 → 187 → 136px**,
  행 높이는 **32 → 43 → 55 → 32px**이며 선택이 보존되고 가로 스크롤이 없다.
  기본 136px/상하 7px 밀도는 사용자 승인안과 같다.
- 원본 QA 재현을 그대로 실행해 **2 passed / 1.38초**를 확인했다.
  글꼴 왕복 사례는 `tests/test_calculator_result_state.py`로 옮겼고 원래 QA 명령은 이를 import하는
  호환 진입점으로 유지한다. CI가 같은 사례를 두 경로로 함께 수집하지 않는다.
- 렌더 스크립트도 28px와 원래 글꼴 복귀를 포함한다. 실제 Qt delegate 크기·전체 이름·클릭/방향키와
  오른쪽 표 공간을 검사했고 28px에서도 두 표 폭 573px를 확보했다.

## 검증

- 이관/원자 저장/계산기/원본 후속 QA: **26 passed / 3.01초**.
  원본 QA와 정식 회귀의 같은 글꼴 왕복 사례가 이 개발 명령에서는 중복되므로 고유 사례 수로 합산하지 않는다.
- 추가 설정/가져오기/보존/공개 정책/설정 안내/Unicode 묶음: **222 passed / 55.57초**.
- 전체 격리 회귀: **2108 passed, 15 deselected / 666.60초**. localhost 콜백 테스트를 위해 로컬 네트워크 사용을 허용한 환경에서 실행했다.
  15개는 `windows_integration` 선택 대상이므로 Linux 통과에 포함하지 않는다. 기존 toast 테스트의 Qt deprecated 생성자 경고 3건이 남았다.

```bash
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_buff_name_migration.py tests/test_config_atomic.py tests/test_calculator_result_state.py scripts/qa_live_followup_20261020.py -q
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not windows_integration' -q
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/render_calculator_sidebars.py /tmp/qa-followup-sidebars
```

제품·검사 입력이 바뀌었으므로 이전 Windows 후보를 재사용할 수 없다. 준비 중인 0.7.1 노트에
이름 갱신을 추가했고 버전을 새로 올리거나 태그/Windows workflow/Release를 실행하지 않았다.
개발 검증을 이번 수정의 후속 독립 QA나 실제 Windows/NVIDIA/DPI 검증으로 대신하지 않는다.
