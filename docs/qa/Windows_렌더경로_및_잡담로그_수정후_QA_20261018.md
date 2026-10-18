# Windows 렌더 경로 및 잡담 로그 수정 후 독립 QA

- 기준: `ac97b6445eb46545cda89347c9363a32ae3d322c` 현재 소스.
- 결론: **v0.4.86에서 확인된 출력 경로 결함의 원인 코드가 제거됐다. 이번 범위에서 새
  Confirmed Bug / Highly Likely Bug를 발견하지 않았다.** 실제 Windows 재실행 성공은 미확인이다.
- 앱의 판독/설정/스레드/워크플로 변경은 없다. 이번 제품 코드 변경은 잡담 거절 로그 보완이며,
  기존 영역 등록·투명 가림의 이전 QA 범위를 그대로 재검증했다고 과장하지 않는다.

## 원래 Windows 실패 경로

- `tests/test_registration_render.py`에서 고정 `Path('/tmp/region-registration-implemented')`가
  `tmp_path / 'region-registration-implemented'`로 바뀌고 해당 fixture 인자가 추가됐다.
- 이전 소스에 위 변경 및 불필요해진 Path import 제거만 적용한 문자열이 현재 전체 파일과
  정확히 일치함을 대조했다. 기존 버튼/가로 스크롤/PNG 저장 assertion과 기본·20px 조건은 그대로다.
- pytest가 생성·관리하는 부모 디렉터리 아래 저장하므로, Windows 드라이브 루트의
  `\\tmp`가 존재해야 한다는 조건을 제거한다. 러너 폴더 생성/skip/기대값 약화 우회가 아니다.
- 실제 검사는 한글·공백을 포함한 `--basetemp='/tmp/qa-render-fix-20261018-한글 경로'`로
  실행했다. 두 테스트가 서로 다른 하위 폴더에 여섯 탭+안내 PNG를 각각 저장해 총 14개가 생성됐다.
- 이 실행은 Linux의 PNG 저장과 경로 격리 확인이다. WindowsPath를 직접 실행하거나
  새 Windows 러너에서 원래 실패가 통과하는 것까지 확인한 것은 아니다.

## 잡담 표시 직전 거절 로그

- 첫 자격 확인이 통과해도 선택 문장 배치/두 번째 노출 확인이 거절되면, 이제 수동 요청은
  사유 범주와 유효 대사 수를 한 번 기록한다. 이전 QA의 P3 개선 사항을 보완했다.
- 새 네 조건(배치/노출 × 수동/자동)은 거절 결과, 말풍선 미표시, 만료 타이머 비활성,
  표시 이력 미기록과 수동 로그 1회/자동 로그 0회를 확인하며 통과했다.
- 기존 실제 클릭/자동 표시, 투명·불투명·부분 알파, 데이터/캐시 실패, 자동 틱 100회
  로그 비누적, 자원 영역 독립 해제 검사도 함께 통과했다.
- 표시 성공/차단 정책을 바꾸지 않고 기존 단축 평가 분기를 분리해 로그만 추가한 것을
  소스로 확인했다. 여전히 개별 차단 HWND/알파를 특정하는 상세 진단은 제공하지 않는다.

## 실행과 범위

```bash
PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest tests/test_registration_render.py tests/test_region_registration.py tests/test_tracking_callback_generation.py tests/test_release_notes.py tests/test_creator_dialogue.py tests/test_dialogue_transparent_occlusion.py docs/qa/assets/dialogue_registration_fix_20261018/probe.py -q -m 'not windows_integration' --tb=short --basetemp='/tmp/qa-render-fix-20261018-한글 경로'
```

- **121 passed, 1 deselected (17.47초)**. 제외한 것은 기존 실제 Windows 알파 0 HWND 검사다.
  새 실패를 숨기기 위해 skip하거나 기존 assertion을 변경하지 않았다.
- Linux Qt offscreen, 기존 원본 및 명시적 외부 API/캡처 대체 환경이다. 실제 사용자 PC의
  잡담 클릭 해결 여부, Windows 알파 합성/DPI/장시간 부하/네이티브/exe는 미검증이다.
- 해당 제품 SHA의 Actions 실행 기록은 조회 시 0개였다. 일반 푸시에서 Windows를 시작하지
  않는 정책을 유지했으며, 같은 실패 태그 재실행이나 별도 유료 실행을 요청/시작하지 않았다.

## 릴리즈 준비

- 원격 최신 태그 v0.4.86은 실패한 소스를 가리킨다. 삭제/이동하지 않으며 다음은 **v0.4.87**이다.
- 미게시 v0.4.86 노트의 제목만 v0.4.87로 변경했다. 배포되지 못한 사용자 대상 기능 설명은
  유지하고 내부 CI 수정/QA 문구는 추가하지 않는다. v0.4.85 이하 본문은 원격 태그와 동일하게 보존한다.
- QA에서는 보고서와 위 최소 노트 버전 조정만 커밋·main 푸시한다. 태그/Release는 사용자가
  직접 실행하며 전체 Windows 회귀/네이티브/exe가 모두 성공해야 게시된다.
