# 공개 정책 정리 및 헤일로 원본 수집 개발

## 구현 범위

- 기본 도르카·생명력/마나/스태미나 바·단축바 그룹 복제는 로그인 없이 직접 지정·보기·해제·표시·배율·잠금·경고를 사용할 수 있다. 도르카 자동 복구도 유지한다.
- 개별 자동찾기·일괄 자동설정·수집·디버프 강제 진단 방식의 기존 로그인 조건은 유지한다.
- 첫 사용 안내 자체와 기본 기능 선택·설명·둘러보기는 비로그인에도 열리며, 선택과 자동설정 실행 권한을 분리했다. 로그아웃은 자동설정만 취소하고 안내 화면의 진행 단계를 닫지 않는다.
- 기능별 공개 단계·반복 로그인 문구를 제거했다. 설정 Discord 구간에는 짧은 베타 선사용 목적 안내를 유지한다. 실제 캡처/저장 실패와 지원 범위 설명은 유지한다.

## 투아림 % 표시

- 사용자가 제공한 Discord 숫자 ID만 제작자로 인정한다. 기존 앱의 로컬 Discord 계정 정보를 사용하는 공개 대상 구분이며, 로컬 파일 변조까지 방어하는 서버 인증 보장은 아니다.
- `% 표시` 체크와 실제 오버레이 요소·추가 판독 요청을 같은 권한으로 제한한다. 일반 로그인은 이를 허용하지 않는다. 원본/최근 판독값과 일반 임계 알림은 유지한다.
- 최초 정책 적용은 `dorcha.showTuarim=false`와 `dorcha.tuarimAlphaReset=1`을 하나의 원자적 설정 저장으로 기록한다. 이후 제작자의 체크 선택은 저장·재실행에서 보존한다.
- 전환 저장 실패 시 완료로 처리하지 않고 해당 실행의 % 표시만 차단한다. 다른 영역·배치·소리·알림 설정은 유지하고 다음 실행에 전환을 재시도한다.
- 계정 변경/로그아웃 때 % 요소만 제거한다. 도르카·공유 투아림 판독/알림 상태를 재생성하지 않아 중복 알림을 유발하지 않는다.

## 헤일로 수집 1단계

- 사용자 후속 승인에 따라 보스 패턴 알림 안의 `[체력별패턴] [1분 헤일로]` 3차 탭으로 분리한다. 각 탭은 독립 세로 스크롤을 사용한다. 제작자 이외에는 헤일로 탭·UI·캡처·수집을 실행하지 않는다. 권한이 없어지면 체력별패턴으로 돌아가며 기존 설정은 유지한다. 탭 이름과 별개로 향후 실제 알림 주기는 기획의 63초를 유지한다.
- `haloTimer.box`에 별도 영역을 저장하며, 보스/디버프 공유 영역은 건드리지 않는다.
- 직접 지정·영역 보기·지정 해제·원본 미리보기·수집 체크·스냅샷·폴더 열기를 제공한다.
- **아직 시간 판독·동기화·예상 카운트다운·헤일로 알림은 구현하지 않았다.** 현재 상태를 화면에도 명시한다. 원시 판독값은 null 및 `not_implemented`로 기록하며 내부 예상 시간을 정답으로 저장하지 않는다.
- 게임이 포그라운드일 때만 기존 mss 캡처 경로로 지정 영역을 읽는다. 기존 등록 게임 HWND/PID/물리 영역을 확인하며 실제 포그라운드 HWND와 일치하고 지정 영역이 게임창 안에 있을 때만 캡처한다. 캡처 전후 대상이 바뀌면 저장하지 않는다. 등록 게임이나 Windows API 확인이 실패하면 캡처하지 않는다. 전체 일시정지·영역 선택 중에는 캡처하지 않는다. 미리보기도 같은 원본을 쓴다.
- 초당 최대 1장, 900장 또는 100MiB/세션, 입력 이미지 최대 100만 픽셀이다. 수집은 재실행 시 OFF다. 밝고 낮은 채도의 픽셀 마스크 변화는 자료 수집용 휴리스틱이며 판독 정확도를 보장하지 않는다.
- PNG와 JSON을 순번별 폴더에 쓴 뒤 폴더 이름을 확정한다. JSON에는 캡처 시각(UTC)·순서·논리/물리 좌표·이미지 크기·버전·백엔드를 저장한다. 세션 UUID로 재실행/재수집 덮어쓰기를 막는다.
- 같은 시점에 저장 작업은 하나뿐이며, 작업 중 새 이미지는 쌓지 않는다. 인코딩/파일 I/O는 Python 워커에서 수행하고 Qt는 접근하지 않는다. 이미지 복사 후 전달해 캡처 버퍼 재사용과 분리한다.
- 저장 실패/한도 시 수집을 끈다. 실패 이미지는 성공 장수에 포함하지 않는다. 실패·중단된 `.pending` 폴더는 완료 자료와 구별되며 자동 삭제하지 않는다.
- 지정 변경·해제·권한 해제·종료 시 수집을 중단한다. 진행 중 파일 I/O를 강제로 끊거나 UI 종료에서 기다리지 않으며 워커는 Qt 참조 없이 종료하고, 취소 확인 후 새 확정 폴더를 만들지 않는다. OS 파일 호출이 이미 진행 중인 순간까지 되돌린다는 뜻은 아니다.
- 기존 원본 삭제·자동 업로드·자동 Git 반영은 없다. 세션별 한도이며 여러 세션의 전체 보관량 자동 삭제 정책은 도입하지 않았다.

## 검증 범위

새 테스트는 기본/제작자/로그아웃 권한, 최초 전환과 재실행 보존·저장 실패,
비로그인 체력바 판독·소리·흔들림·단축바 12그룹 복제,
원본 PNG 픽셀 일치·한글 경로·세션 분리·수집 속도·변화 억제·용량/개수 제한,
폴더/PNG/메타데이터 실패·권한 해제·영역 변경·워커 종료를 검사한다.
외부 장치·네트워크는 테스트 경계에서 대체한다. 기존 QThread 누수 검사는 유지한다.

Linux Qt offscreen에서 실제 MainWindow의 제작자 헤일로 및 자원 화면,
비로그인 자원·체력바·단축바 화면을 렌더링하고 가로 스크롤을 확인했다.
Windows·exe·실게임 수집 정확도·혼합 DPI·장시간 부하는 미검증이다.
일반 푸시 Windows Actions·태그·릴리즈는 실행하지 않는다. 후속 독립 QA 및 제작자 실게임 자료 검증이 필요하다.

화면 확인:

- [체력별패턴 3차 탭](images/release-policy-20261019/creator-boss-hp.png)
- [제작자 헤일로 수집](images/release-policy-20261019/creator-halo.png)
- [제작자 자원 표시](images/release-policy-20261019/creator-resource.png)
- [일반 사용자 자원 표시](images/release-policy-20261019/public-resource.png)
- [일반 사용자 체력바](images/release-policy-20261019/public-stat_bars.png)
- [일반 사용자 단축바](images/release-policy-20261019/public-skillbar.png)

### 실행 결과

- 최종 공개 정책·수집·설정·자원·체력바·단축바·디버프·종료·업데이트 노트 회귀: **368 passed in 202.27s**.
- 도르카 전체 회귀에서는 189개가 통과했고 이전 로그인 정책을 기대한 1개가 실패했다. 로그아웃 후 자동 복구를 유지하는 새 요구에 맞춰 해당 기대값을 수정한 뒤 추적·게임 문맥·시작 복구 3개 파일을 다시 실행해 **51 passed in 46.08s**를 확인했다. 나머지 통과 결과와 중복 합산하지 않는다.
- 헤일로 캡처 대상·큰 글꼴을 추가한 최종 단독 검사: **17 passed in 8.29s**. 위 묶음과 중복이다.
- 별도 체력바·새 공개 정책·조작 회귀: 63 passed. 초기 55/75/18개 검사와도 중복이므로 총합으로 표시하지 않는다.
- 초기에 새 테스트가 QApplication 없이 QWidget을 만들며 테스트 프로세스가 중단된 문제는 테스트의 QApplication 수명 fixture를 추가해 수정했다. 제품 실행 크래시로 판정하지 않았다. 기존 QThread 누수 검사는 제거하지 않았다.
- 예전 로그인 종속 기대값은 새 공개 정책에 맞춰 바꿨으며 자동찾기·수집 차단과 기본 표시 유지의 반대 조건도 검증한다. 추적 테스트의 `저장 없음` 검사는 유지하고 설정을 최초 전환 완료 상태로 준비했다.
- `git diff --check` 통과. 독립 QA 통과나 실제 Windows 검증을 뜻하지 않는다.

### 3차 탭 후속 변경

- 사용자가 `[체력별패턴] [1분 헤일로]` 배치를 승인하고 앞선 개발분과 함께 검증 후 main 푸시를 요청했다.
- 헤일로 탭 노출/권한 해제 후 체력별패턴 복귀, 반복 전환 중 설정 보존, 12/20px 글꼴 및 크기가 다른 작업 영역에서 각 탭 내부 스크롤로 버튼 접근을 검사한다.
- `test_navigation_all_widths`는 가장 가까운 스크롤 영역을 실제로 이동시켜 각 버튼이 뷰포트 안에 들어오는지 검사하도록 갱신했다. 가로 범위·전체 버튼 영역 검사는 유지한다.
- 일반 회귀에서 사용하는 `scripts/qa_navigation_tour_layout.py`의 시작 데이터는 최초 전환 완료 상태로 준비했다. 설정 불변 검사는 그대로 유지한다. 과거 QA 보고서 내용은 변경하지 않는다.
- 탭 분리 후 최종 실행: `env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_halo_capture.py tests/test_navigation.py tests/test_navigation_all_widths.py tests/test_main_shutdown.py tests/test_feature_release_policy.py tests/test_tour_layout.py -q --tb=short --maxfail=3` → **73 passed in 75.67s**. 앞선 368개 검사와 중복이며 합산하지 않는다.
- 최종 업데이트 노트 검사: `env QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dungeon_release_note.py tests/test_release_notes.py tests/test_release_notes_trigger.py -q --tb=short` → **14 passed in 4.33s**.

최종 회귀 명령:

```bash
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_feature_release_policy.py tests/test_halo_capture.py tests/test_setup.py tests/test_navigation.py tests/test_navigation_all_widths.py tests/test_resource_integration.py tests/test_resource_common_settings.py tests/test_setup_common_resources.py tests/test_stat_bars.py tests/test_stat_bars_stability.py tests/test_stat_shake.py tests/test_skillbar_mirror.py tests/test_debuff_auto.py tests/test_main_shutdown.py tests/test_lifecycle.py tests/test_interaction_polish.py tests/test_release_notes.py tests/test_dungeon_release_note.py -q --tb=short --maxfail=5
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_dorcha_tracking.py tests/test_dorcha_roi_context.py tests/test_dorcha_startup_recovery.py -q --tb=short --maxfail=5
env OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_halo_capture.py -q --tb=short
```
