# Windows v0.5.0 전체 회귀 실패 분석

- 검증일: 2026-10-19
- 실패 대상: `f25cf5bc2398759e8cfca277aadbafd6d3c5c1c9`, 태그 `v0.5.0`.
- 실행: [release 39214063189](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39214063189), 작업 `117933726405`.
- Windows 일반 회귀: **36 failed, 1778 passed, 1 skipped, 10 deselected / 806.11초**.
- 실패 단계는 `Test gate (pytest)`다. Windows 네이티브·exe·Release 게시·공개 업데이트·Discord 공지는 건너뛰었다. 결제/러너 차단이나 빌드 오류가 아니다. 확인 시 공개 최신 버전은 여전히 v0.4.90이다.
- Linux에서 실패한 6개 파일을 실행해 **같은 36개 실패**를 재현했다. 모두 테스트 준비/테스트 규칙 위반으로 원인을 좁혔으며, 이번 로그만으로 제품의 실제 잡담/판독 장애라고 단정하지 않는다.

## Confirmed Bug 1: 첫 사용 안내 상태로 잡담을 검사하는 fixture

- 심각도: P2, 회귀/배포 게이트 결함. 29개 실패의 공통 원인.
- 발생 조건: `tests/test_creator_dialogue.py`의 `window` fixture가 비로그인·신규 임시 설정으로 MainWindow를 만들고 곧바로 잡담/얼굴을 검사한다.
- 사용자 영향: 전체 테스트가 실패해 배포를 차단한다. 실제 첫 사용 안내 중 잡담을 차단하는 제품 동작 자체는 승인된 정책이며 제거하면 안 된다.
- 기술적 원인: 이번 공개 정책에서 비로그인도 첫 사용 안내로 진입한다. 기존 fixture는 로그인하지 않으면 곧바로 메인 화면이 나온다고 가정했다. `_pages`는 `setup_guide`에 있고 실제 잡담의 `_eligible()`은 메인 화면 밖이므로 거부한다. 얼굴/설정 버튼도 숨은 페이지에 있어 hover 검사부터 실패한다. 이 fixture를 가져오는 Windows 가림 검사도 실제 native 판정 전에 같은 화면 상태 가드에서 멈춘다.
- 관련 위치:
  - `tests/test_creator_dialogue.py:277`: 신규 비로그인 MainWindow fixture.
  - `src/mabinogi_addon/ui/main_window.py:442`: 비로그인에도 첫 사용 화면 적용.
  - `src/mabinogi_addon/ui/creator_dialogue.py:260`: 메인 화면/안내/모달 상태 검사.
  - `scripts/qa_dialogue_transparent_occlusion.py:88`, `tests/test_dialogue_transparent_occlusion.py:118`, `tests/test_dialogue_window_region.py:96`: 같은 fixture 상태의 영향.
- 실패 분포: `test_creator_dialogue.py` 25개, `test_dialogue_transparent_occlusion.py` 3개, `test_dialogue_window_region.py` 1개.
- 검증: 동일 실패를 Linux에서 재현했다. 독립 대조 검사에서는 비로그인 신규 안내 중 잡담 거부, 실제 `skipSetup=true` 설정으로 메인 진입 후 잡담 표시를 각각 확인했다. 가림 판정 우회가 아니라 화면 진입 조건만 준비한 결과다.
- 개발 전달: 메인 화면을 검사할 fixture는 지원되는 설정/안내 완료 흐름으로 준비한다. 첫 안내·투어 중 잡담 차단 검사는 별도 유지한다. 제품의 `_eligible()`을 완화하거나 fixture에서 항상 참으로 바꿔 해결하지 않는다.

## Confirmed Bug 2: 일반 계정으로 제작자 전용 % 표시를 기대하는 기존 pipeline

- 심각도: P2, 회귀/배포 게이트 결함. 6개 실패의 공통 원인.
- 발생 조건: 과거 투아림 저구간/19% 표시 검사가 공유하는 pipeline이 일반 계정 `id='qa'`로 도르카를 만들고 % 체크를 켠다.
- 사용자 영향: 배포 게이트가 실패한다. 이 로그는 실제 16/19 등의 숫자를 잘못 읽었다는 증거가 아니다. 오버레이 생성 전 권한/전환 조건에서 막힌다.
- 기술적 원인: % 표시는 제작자 ID에만 허용되며 최초 정책 전환은 체크를 OFF로 초기화한다. 기존 pipeline은 두 조건을 반영하지 않았다. 일반 투아림 알림과 도르카 표시도 꺼 둔 채 %만 요청하므로 표시 오버레이가 없는 것이 정상이다.
- 관련 위치:
  - `scripts/qa_tuarim_low_range_display.py:71`: 일반 계정 준비.
  - `scripts/qa_tuarim_low_range_display.py:79`: 권한 없는 % 체크 조작.
  - `scripts/qa_tuarim_low_range_display.py:91`: 오버레이가 있어야 한다는 실패 assertion.
  - `scripts/qa_tuarim_visible_nineteen_20261018.py:10`: 같은 pipeline 가져오기.
  - `src/mabinogi_addon/ui/dorcha_tab.py:136`, `src/mabinogi_addon/ui/dorcha_tab.py:148`: 제작자 표시 권한과 체크 처리.
  - `src/mabinogi_addon/config.py:878`: 최초 정책 전환.
- 실패 분포: `test_tuarim_low_range_display.py` 5개, `test_tuarim_visible_nineteen.py` 1개. 순수 문자 판독은 같은 파일 묶음에서 통과했다.
- 검증: 기존 pipeline의 표시 실패를 재현한 뒤, 같은 인스턴스에서 제작자 계정으로 전환하고 실제 % 체크를 켰다. 원본 16/19의 판독·안정화·표시 일치 및 100%의 `None`/`--%` 안전 보류가 모두 통과했다.
- 개발 전달: 제작자 positive pipeline은 최초 전환 완료 후 명시적 opt-in으로 준비한다. 일반 계정/비로그인에서 표시 차단 검사는 유지한다. 제품 접근 제한을 풀거나 문자 판독 assertion을 삭제하지 않는다.

## Confirmed Bug 3: 새 헤일로 테스트의 텍스트 인코딩 미지정

- 심각도: P2, 테스트 이식성/게이트 결함. 1개 실패.
- 발생 조건: 전체 일반 회귀에서 테스트 파일의 텍스트 입출력 계약을 검사한다.
- 사용자 영향: 배포 게이트가 실패한다. Windows 기본 코드페이지와 무관한 UTF-8 읽기를 테스트에서 명시하지 않았으며, 이 결과가 제품의 PNG/JSON 저장 실패를 의미하지는 않는다.
- 기술적 원인: `tests/test_halo_capture.py:191`의 `metadata.json.read_text()`에 `encoding='utf-8'`이 없다. AST 기반 `tests/test_unicode_io_contract.py:63`이 정확히 이 위치를 보고한다. Linux에서도 같은 계약 검사로 실패한다.
- 검증: 원래 계약 검사를 그대로 실행해 동일 위반을 재현했다. 제품 저장은 UTF-8 바이트를 사용하므로 제품 코드를 바꿀 근거는 없다.
- 개발 전달: 새 테스트의 읽기에 인코딩을 명시하고 계약 검사 전체를 재실행한다. 계약 검사 자체를 skip/삭제/완화하지 않는다.

## 원본 재현 및 대조 실행

실패 SHA와 실행 미러 기준 `c1db581`의 비문서 파일 blob이 동일함을 확인했다. 실패 SHA에서 추가된 것은 QA 완료 문서뿐이다. 커밋 이력/메시지는 조회하지 않았다.

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest \
  tests/test_creator_dialogue.py tests/test_dialogue_transparent_occlusion.py \
  tests/test_dialogue_window_region.py tests/test_tuarim_low_range_display.py \
  tests/test_tuarim_visible_nineteen.py tests/test_unicode_io_contract.py \
  -q --tb=short --show-capture=no
```

Linux 결과: **36 failed, 116 passed, 1 skipped / 21.25초**. Windows의 실패 36개와 테스트 ID가 일치한다. Windows 전용 skip은 통과로 집계하지 않았다.

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest \
  scripts/qa_release_050_gate_20261019.py \
  docs/qa/assets/release_050_failure_20261019/probe.py \
  -q --tb=short --show-capture=no
```

결과: **3 failed, 5 passed / 2.56초**. 세 원인의 대표 실패 3개와 위 화면/권한 대조 5개다. 기존 테스트나 제품은 수정하지 않았다. 실패 스크립트는 일반 자동 수집에 추가하지 않았다.

## QA 범위 누락 및 후속 조건

- 앞선 QA는 변경 기능·관련 회귀와 발견된 중첩 스크롤/워커 대기를 검사했지만, 이번 공개 정책에 영향받는 기존 잡담 fixture와 과거 % 표시 pipeline 소비자, 새 테스트의 인코딩 계약까지 포함하지 못했다. 따라서 앞선 관련 범위 통과는 전체 일반 회귀 통과가 아니었고, 해당 범위 선정 누락을 이번 실패로 확인했다.
- 개발 세션은 위 공유 fixture의 모든 소비자를 추적해 현재 요구사항의 정상 사용 조건으로 준비해야 한다. 첫 진입/공개 권한/설정 전환이 바뀌면 직접 MainWindow/컨트롤러를 만드는 기존 테스트를 함께 확인하고, 새 테스트 파일에는 Unicode I/O 계약 검사도 포함해야 한다.
- 수정 후 위 6개 파일과 첫 사용 안내·공개 정책/수집·투아림 알림/표시의 반대 조건을 재검증한다. 다른 실패가 없는지는 이후 태그 전체 게이트가 최종 확인한다. 원인을 고치기 전 같은 SHA의 Re-run all jobs는 권하지 않는다.
- `v0.5.0`은 이미 사용한 실패 태그다. 삭제/이동/재사용하지 않는다. 제품 기능 추가가 아닌 이번 검증 수정 후 QA가 통과하면 버전 정책에 따라 다음 미사용 패치 번호(현재 `v0.5.1`)와 공개 노트를 맞춘다. 이번 분석 단계에서는 릴리즈 명령이나 태그를 만들지 않는다.
- 실패 기록을 main에 공유하되 제품·기존 테스트·공개 노트는 QA에서 임의로 수정하지 않는다. Windows 네이티브/exe는 이번 실패 실행에서 미검증이다. 정상 통과나 배포 완료로 안내하지 않는다.
