# Windows 무료 한도 정책 변경 독립 QA

- 날짜: 2026-10-18 (Asia/Seoul).
- 검증 SHA: `5ce8774e3fdbee02316bd22fb5eadc93554411c3`.
- 요구: 일반 푸시의 Windows 실행 중단, 위험 변경만 선택 사전 검증,
  태그 릴리즈의 전체 테스트/네이티브/exe 필수 게이트 유지 및 지침 정합성.
- 기준 QA `ab3893e`와 현재 트리만 비교했다. 커밋 이력/메시지를 조회하지 않았다.
  이번 QA에서 제품/워크플로/기존 테스트는 수정하지 않았다.

## 판정

**확인한 범위에서 정책 변경은 요구와 일치하며 추가 결함을 발견하지 못했다.**
관련 로컬 검사와 독립 조건 검사는 통과했다. 무료 한도를 소비하는 Actions 실행이나
실제 Windows/PyInstaller 빌드는 시작하지 않았으므로 플랫폼 실동작 통과로 표현하지 않는다.

## 실행 조건

| 상황 | 변경 후 동작 |
| --- | --- |
| 일반 main 푸시 | 두 Windows 워크플로 모두 예약되지 않음 |
| windows.yml 수동 실행, 기본값 | 전체 회귀 + 네이티브, exe/아티팩트 없음 |
| build_exe=true | 검증 후 exe 빌드, 업로드는 별도 선택 |
| upload_exe=true | build_exe=false여도 exe 빌드 후 선택 업로드 |
| v* 태그 | 릴리즈 전체 회귀 -> 네이티브 -> exe 필수 |
| 테스트/네이티브/빌드 실패 또는 미실행 | Release/업데이트 저장소/공지가 게시되지 않음 |
| release.yml 수동 실행 | 기존처럼 검증·빌드하되 태그가 아니므로 게시하지 않음 |

- `.github/workflows/windows.yml`의 이벤트는 workflow_dispatch 하나이며 두 입력은 기본 false다.
  빌드 조건 `inputs.build_exe || inputs.upload_exe`를 실제 bool 입력 조합으로 확인했다.
- `.github/workflows/release.yml`의 push는 tags v*만 있다. 일반 브랜치 푸시가 실행되지 않는다.
  전체 테스트/네이티브/빌드에는 if나 continue-on-error가 없고 순서도 유지된다.
- 네 게시 지점은 모두 success(), 태그 ref, unit/native/build 각각 outcome=success를 요구한다.
  Discord는 여기에 webhook 존재를 추가 요구한다.
- summary의 always()는 결과 기록일 뿐이며 후속 게시가 필수 단계를 우회하게 만들지 않는다.
  선택 아티팩트 업로드만 경고로 분리하며, 기본 OFF/보관 1일도 유지한다.
- 공개 저장소의 제작자 대사 파일을 최초에만 생성하고 기존 파일을 보존하는 검사도 통과했다.
- 관련 위치: `windows.yml:3-13,45-57`, `release.yml:38-48,73-76,98,153,190,205`.

## 독립 검증

`docs/qa/assets/windows_policy_20261018/probe.py`는 현재 YAML을 구조적으로 읽으며
비밀값 접근, 실제 GitHub 실행, git push/릴리즈/웹훅 호출을 하지 않는다.

- **4,000개 게시 결정**: 네 게시 지점에 대해 unit/native/build 각각
  success/failure/skipped/cancelled/빈 값, 이전 단계 성공 여부, 태그/브랜치, 웹훅 유무를 조합했다.
  실제 조건식을 평가해 모든 차단/허용 결과가 기대와 같음을 확인했다.
- **20개 변형**: 각 게시 조건의 필수 단계/태그/success 조건을 하나씩 제거하면
  원래 차단돼야 할 상태가 허용되는 것을 확인해 검사 도구가 그런 누락을 잡을 수 있음을 검증했다.
  제품 YAML은 변경하지 않았다.
- 수동 옵션과 이전 단계 성공/실패 조합에서 빌드·업로드가 언제 허용되는지 확인했다.
- 릴리즈 필수 단계가 조건부 skip 또는 soft-failure로 바뀌지 않았음을 확인했다.
- Bash 단계는 bash -n으로 구문만 확인했다. 스크립트의 git log/배포 명령은 실행하지 않았다.
- 조건식 평가는 현재 사용된 bool/문자열/startsWith/status 함수의 JS 호환 부분만 모델링한다.
  GitHub Actions 엔진 자체를 실행한 검증은 아니다. 초기 QA 보조 코드의 JS 문자열 오타는
  도구에서 수정했으며 제품 결함으로 보고하지 않는다.

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest docs/qa/assets/windows_policy_20261018/probe.py tests/test_windows_ci.py tests/test_release_notes.py tests/test_release_notes_trigger.py scripts/qa_tuarim_low_range_display.py -q --tb=short
```

- 최종 **51 passed (3.27초)**. 위 4,000/20조합은 독립 6개 테스트 내부 조건이며 총계에 더하지 않는다.
- 개발의 windows_ci 검사만 별도 재실행한 결과도 **21 passed (0.57초)**다. 위 집합과 중복된다.
- 앞선 투아림 16->6 등 원래 12조건, 정상 한 자리 대조군과 실제 100% None/--% 계약도 통과했다.
  정책 변경에서는 앱 판독/표시 코드를 변경하지 않았다.

## 지침 및 버전

- AGENTS.md/CLAUDE.md/docs/windows-validation.md의 현재 지침이 동일하다.
  일반 푸시 뒤 자동 Windows 대기/매번 수동 실행 요청/매번 exe 빌드 요구는 제거됐다.
- 선택 검증을 실제 시작한 경우 정확한 SHA와 필수 단계 성공을 확인하고, 빌드를 요구한
  경우에만 --require-build를 붙인다. 실행되지 않은 SHA를 기다리지 않는다.
- 로컬 QA를 전달할 수 있어도 Windows 통과나 배포 성공을 주장하지 않는다.
  새 정책은 태그 명령 제공 전 Windows 성공을 일률적으로 요구하지 않지만,
  태그 실행 뒤 필수 게이트를 통과하지 않고 게시하는 예외는 허용하지 않는다.
- 문서의 과거 자동 실행 성공/실패 기록은 역사적 증거로 남겨져 있으며 현재 정책과 구분돼 있다.
- 최신 원격 태그는 v0.4.84 (`19d8d6c`), 새 노트는 v0.4.85다.
  현재 노트의 v0.4.84 이하 전체는 태그 당시 본문과 문자 단위로 동일함을 확인했다.
  새 노트에는 투아림 사용자 설명만 있고 내부 검증 정책은 노출하지 않는다.

## 무료 한도와 릴리즈

사용자 공유 화면에서 Actions 포함 시간 2,000/2,000분과 저장 0.5/0.5GB의 소진을 확인했다.
앞선 39052932417의 runner_id=0/steps=[]와 결제·한도 오류는 테스트 assertion 실패가 아니다.
이번 정책 변경은 앞으로의 중복 소비를 줄일 뿐 이미 소진된 한도를 복구하지 않는다.

새 SHA의 Actions 실행 목록은 비어 있었고, 정책 검사 중 실행을 시작하지도 않았다.
한도 복구/허용 전에는 태그 릴리즈도 실행 차단될 수 있다. 로컬 검증만으로 태그 게이트를
건너뛰거나 Windows 통과로 대신하지 않는다. 태그 생성/푸시와 실제 릴리즈는 사용자가 수행한다.

## 한계

워크플로 YAML과 조건식의 로컬 검증이며 실제 러너 예약/Windows 실행/권한·비밀값 주입/
Release API/공개 저장소 갱신/Discord 전달을 확인하지 않았다. 예산 설정이나 기존 아티팩트를
변경·삭제하지 않았다. 원래 QThread/외부 장치 경계와 앱 회귀 assertion도 유지했다.
