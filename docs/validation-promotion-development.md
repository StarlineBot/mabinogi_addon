# 검증·배포 분리와 테스트 정리: 개발 검증

기준: `6126026652e11ae039a065a6631507a699247352`, Linux cloud, Python 3.12, 동일 venv.
요청 범위는 구현/검증이며 실제 태그·Release·공지·Windows Actions는 실행하지 않았다.
운영 절차는 [Windows 검증·승격](windows-validation.md)을 따른다.

## 흐름 변경

| 단계 | 기존 | 변경 후 |
| --- | --- | --- |
| 일반 푸시 | 무거운 검사 없음 | 유지 |
| 사전 검증 | 전체 회귀/네이티브, exe/업로드 선택, exe 0.0.0 | 수동 main, 확정 버전 전체 회귀/네이티브/exe/필수 후보 보관 |
| 게시 시작 | v* 태그 푸시 | 사용자 release.yml 수동 승인 |
| 게시 | 전체 테스트/태그 버전 재빌드 | 성공한 후보를 내려받아 증명/해시 확인 후 동일 파일 승격 |
| 보관 | 선택 업로드 1일, 개수 제한 없음 | 1일/최대 2개/각 200MiB, 캐시 저장 비활성화 |
| quota 실패 | 경고, 배포용 별도 빌드 | 테스트/빌드와 구분하되 후보 부재로 게시 차단 |
| 공개 노트 | 커밋 제목/랜덤 문구 | 검증 SHA의 한국어 해당 버전 노트 |

검증 버전이 exe Python 버전/PE 리소스/manifest/version.json/사용자 태그와 동일하다.
게시 워크플로는 Ubuntu에서 실행하며 의존성 설치·pytest·exe 빌드가 없다.
실행 ID/attempt/전체 SHA/버전을 지정하고 GitHub API의 실제 성공 단계와 아티팩트 출처를 대조한다.
제품·빌드·테스트·실행 스크립트 변경은 fingerprint 불일치로 거부하고 문서만의 변경은 허용한다.
두 저장소 초안에 올린 파일을 내려받아 동일 해시를 확인한 뒤 공개한다.
테스트 후 추적 파일 변경과 src/packaging의 예상 밖 비추적 파일이 있으면 빌드 전에 중단한다.
버전/번들 Secrets 생성은 이 검사 이후의 통제된 빌드 단계로 한정한다.
외부 다중 저장소 게시의 원자성은 보장하지 않으며 부분 실패 자동 덮어쓰기는 금지한다.

## 조사와 이관

원래 수집 사례는 1831개(일반 1821, 네이티브 10)다. 함수 소스/매개변수/fixture 경계가
모두 같은 중복은 없었다. 의미상 유사한 도르카 재시작과 자체 창 캡처 제외는 경계가 달라 유지했다.
원본 tests의 직접 정의된 테스트 함수 본문/인자/장식자 AST도 비교했으며 동일 복제본은 없었다.
자원 공통 설정의 같은 계약을 새 메인 프로세스에서 재실행하는 사례도 확인했다.
`MABINOGI_COMMON_MAIN_TEST=1`일 때 독립 패널 대신 실제 MainWindow를 생성하므로 초기화/수명 경계가
다른 검사이며 유지했다. 수집 ID가 같다는 이유로 subprocess 검사를 삭제하지 않았다.
원래 사례 삭제를 목표로 하지 않았으며, 다른 버그·상태 전환·반복 횟수는 그대로 둔다.

| 원래 위치 | 현재 정식 위치 | 정식 수집 위치/보존 범위 |
| --- | --- | --- |
| scripts/qa_tuarim_low_range_display.py | test_support/regressions/tuarim_low_range.py | test_tuarim_low_range_display: 원본 12개 + 기존 오탐 5개, test_release_050_regressions의 역할별 6개 |
| scripts/qa_dorcha_restart_after_move.py | test_support/regressions/dorcha_restart.py | test_dorcha_restart 3개, test_dorcha_self_capture 5개, 서로 다른 compositor fixture 유지 |
| scripts/qa_custom_autosave_import_reset.py | test_support/regressions/custom_replacement.py | test_custom_config_replacement의 원본 10개 + 기존 후속 상태 전환 8개 |
| test_windows_ci의 공개 대사 시드 3개 | test_release_candidate의 동명 테스트 | 없음/작성자 정상 자료/손상 자료 모두 보존, 새 Python 배포 구현을 직접 검사 |
| 동일 빌드 명령·태그 자동 게이트 검사 2개 | test_windows_ci의 수동 전체 검증/무재빌드 승격 검사 | 승인된 신규 요구로 교체; 필수 단계 성공·네이티브 분리·PyInstaller 옵션·업로드/게시 게이트 유지 |
| 선택 업로드 경고 검사 | 저장 실패 가시화/게시 차단 검사 | 단계 결과 분리를 유지하고 신규 필수 보관 정책 반영 |

3개 이관 모듈의 모든 함수/fixture AST를 원본 HEAD와 비교하여 **동일함**을 확인했다.
ROOT 경로와 import만 새 경로에 맞췄다. 기존 QA 명령 파일은 호환 진입점으로 남긴다.
CI는 `tests/`만 수집하며 scripts 경로를 함께 실행하지 않는다.
삭제된 검증은 없으며 파일 위치/정책 변경에 따른 사례 매핑은 위 표와 같다.
과거 운영 정책은 windows-validation-history.md/deployment-history.md에 별도 보존했다.
과거 QA 보고서/재현 자료는 수정하지 않았고 현재 게이트로 자동 실행하지 않는다.

기능별 수집 수(일반/네이티브 포함):

| 묶음 | 전 | 후 |
| --- | ---: | ---: |
| resources | 546 | 546 |
| combat | 413 | 413 |
| navigation | 235 | 235 |
| capture | 193 | 193 |
| configuration | 52 | 52 |
| dialogue | 107 | 107 |
| calculator | 18 | 18 |
| delivery | 58 | 132 |
| core | 202 | 204 |
| windows | 7 | 7 |
| 합계 | 1831 | 1907 |

10개 네이티브 사례 중 3개는 dialogue 소유다. 마커로 실행하므로 windows 폴더 7개만 실행하는 것이 아니다.
새 파일의 수집 사례 79개에는 기존 시드 이관 3개가 포함되어 순증은 76개다.
새 묶음은 기존 정상 1개로 축약하지 않으며 전체 Windows 게이트에는 그룹 필터를 쓰지 않는다.
자동 저장 debounce의 고정 450ms 1곳만 실제 완료 조건+1초 제한으로 바꿨다.
늦은 저장 금지 검사의 450ms 관찰, 초기화 격리, QThread 누수 assertion/정리는 유지했다.

## 실행 결과와 시간

전후 동일 명령:

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -ra -m 'not windows_integration' --durations=30 --junitxml=/tmp/validation-before.xml
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -ra -m 'not windows_integration' --durations=30 --junitxml=/tmp/validation-after.xml
```

- 전 실행: **1820 passed, 1 failed, 10 deselected**, 1436.96초.
  실행 중 새 파일을 작성한 탓에 동적 AST 인코딩 검사가 신규 테스트의 UTF-8 명시 누락을 읽었다.
  순수 원본의 전체 녹색 결과라고 주장하지 않는다. 이 실패를 제외/완화하지 않고 신규 파일을 수정했다.
- 원본 HEAD tests 스냅샷에서 같은 인코딩 assertion 재실행: **1 passed, 1.21초**.
  첫 재실행은 스냅샷의 test_support 경로 누락으로 setup error였고 PYTHONPATH를 제공해 해결했다.
- 이관 포함 관련 검사: **141 passed, 50.63초**.
- 최종 워크플로/차단/조사/Unicode 관련 검사: **100 passed, 7.70초**.
- 고정 시드 20261019로 관련 실행 순서를 섞은 검사: **159 passed, 51.41초**.
- 기존 QA 명령 3개 호환 진입점: **27개 수집, 1.26초**. 정식 게이트와 중복 실행하지 않았다.
- 후 전체 실행: **1897 passed, 10 deselected, 기존 경고 3개, 1337.12초 (22분 17초)**.
- 후 전체 실행 중 실제 의존성 추적으로 docs QA 코드/이미지/예제의 fingerprint 누락을 보완하고,
  용량 상한에 manifest 자체 크기도 포함하도록 경계 검사를 보완했다.
  테스트 이후 체크아웃 무결성을 확인하는 빌드 전 게이트도 추가했다.
  이 마지막 보완은 전체 실행이 import한 스냅샷과 다르므로 관련 차단/Unicode 검사를 별도 재실행한다.
- fingerprint 보완 직후 새 프로세스 검사: **100 passed, 16.41초**.
- manifest 자체를 포함한 최종 용량 경계 보완 후 새 프로세스 검사: **100 passed, 7.41초**.
- 빌드 전 체크아웃 게이트까지 포함한 최종 새 프로세스 검사: **100 passed, 8.61초**.
- 별도 통합 마커를 Linux에서 실행: **2 passed, 8 skipped, 1897 deselected, 23.08초**.
  통과한 것은 실제 Qt 루프백 200회와 메인 창 네트워크 수명 20회다. 8개 skip은 원래 Windows API
  플랫폼 조건이며 새로 추가하지 않았다. 이를 Windows 통과로 간주하지 않는다.

첫 전체 실행 도중 짧은 관련 검사를 별도 프로세스에서 실행했으므로 작은 시간 차이를 성능 개선으로
해석하지 않는다. 전후 단위 테스트 수 자체도 달라졌다. 주요 비용 절감은 검증 완료 뒤 게시에서
전체 테스트/빌드를 반복하지 않는 구조이며 실제 Windows 시간 절감은 아직 측정하지 않았다.

| 단계 | 전 | 후 |
| --- | --- | --- |
| Linux 일반 전체 회귀 | 1436.96초, 위 1개 오염 실패 포함 | 1337.12초, 1897 통과 |
| 실제 Windows 전체/네이티브 | 미실행 | 미실행 |
| 실제 PyInstaller exe 빌드 | 미실행 | 미실행 |
| 실제 업로드/승격/공지 | 미실행 | 미실행 |

전 실행 상위 모듈 합계: resource_anchor 228.698초, setup 106.117초,
autofind_mvp 77.557초, dorcha_autofind 73.889초, boss_bar_locate 57.083초.
같은 모듈의 후 실행은 각각 145.191/80.438/69.720/65.679/37.435초다.
전후 모두 짧은 별도 검사가 실행 중 겹쳤고 캐시/부하도 통제하지 않았으므로 통계적 속도 개선으로 주장하지 않는다.
이는 JUnit의 setup/call/teardown 합이며 서로 다른 원본 프레임/좌표/실패 경계를 검사하므로 삭제하지 않았다.
기계 판독 근거는 [전 실행](validation-evidence/before.json), [후 실행](validation-evidence/after.json)에 보관한다.
묶음 소유권은 전후 동일한 최종 분류 규칙으로 정규화했다.
원본 JUnit은 validation-evidence의 before.xml.gz, after.xml.gz, original-contract.xml,
final-gates.xml, shuffled.xml, linux-integration.xml에 보관한다.

## 차단·동일성 검증

`tests/test_release_candidate.py` 69개는 성공 후보의 원본 바이트 보존과 다음을 실제 로컬 실행한다.
Windows PE 읽기/GitHub 전송은 명시적 대체 경계이며 실제 Windows/Release 성공의 증거가 아니다.

- 다른 SHA/버전/repository/run/attempt 거부.
- 필수 5단계 각각 failure/skipped/cancelled 거부.
- 잘못된 workflow/branch/event, 미완료/실패 run 거부.
- 만료/잘못된 이름/잘못된 출처/크기 0 아티팩트 거부.
- exe 원본 바이트 복사, 해시/size/version.json 일치.
- 5개 파일 각각 누락/변조, 24/25시간 만료, payload 초과 거부.
- 실패/빈/모두 skip JUnit, 다른 PE 버전, 이미 사용한 태그 거부.
- 태그 SHA 불일치와 제품 fingerprint 변경 거부; 문서 변경은 fingerprint에 영향 없음.
- 실패 게이트/업로드 손상·누락/업로드 이후 입력 변경 시 공개 edit와 공개 git write가 호출되지 않음.
- 정상 경로의 두 초안 다운로드 해시 확인 뒤에만 공개하며 빌드/테스트 subprocess가 호출되지 않음.
- 보관 정리는 이전 후보 1개만 남기며 다른 아티팩트는 보존.

배포된 파일의 재확인은 Release exe를 다운로드한 뒤 SHA256/크기를 candidate.json 및
version.json과 대조하면 된다. 실행 ID/attempt/SHA/버전도 동일해야 한다.

## 미검증과 후속 QA

무료 한도 보존 정책을 지켜 Windows Actions를 실행하지 않았으며 이 환경은 Linux다.
현재 계정 한도의 회복 여부를 조회하거나 실행을 시도한 것은 아니다.
실제 Windows 테스트/PE 버전 읽기/PyInstaller, GitHub 아티팩트 업로드·다운로드·만료·quota,
GitHub 초안/공개 게시/API 권한/비밀값, 실제 업데이트/공지, 혼합 DPI·장시간 게임 병행은 미검증이다.
PowerShell의 체크아웃 무결성 게이트도 YAML/명령 구조만 로컬 확인했으며 Windows 실행은 하지 않았다.
보관/실패/해시 차단은 로컬 대체 API·파일 경계에서 확인한 결과로만 분류한다.
태그/Release는 만들지 않았다. 사용자가 후속 독립 QA와 최종 배포를 결정한다.
