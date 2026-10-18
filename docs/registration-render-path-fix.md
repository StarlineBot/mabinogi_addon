# Windows 렌더 검사 저장 경로 수정

- 날짜: 2026-10-18 (Asia/Seoul).
- 확인한 QA: `docs/qa/v0.4.86_Windows_릴리즈실패_분석_20261018.md`,
  `docs/qa/잡담_투명가림_및_영역등록_수정후_QA_20261018.md`.

## 원인과 수정

v0.4.86 실제 Windows 로그에서 렌더 검사 두 조건이 고정 `/tmp` 경로의
없는 부모 디렉터리 때문에 WinError 3으로 실패했다. 앱 실행 결함이나 무료 한도
차단이 아니라 개발 단계에서 놓친 테스트의 경로 호환성 결함이다.

`tests/test_registration_render.py`는 pytest `tmp_path` 아래에 출력 폴더를 만든다.
운영체제별 임시 경로를 사용하며 테스트별 파일 충돌도 피한다. 기본/20px 글꼴,
여섯 탭의 가로 스크롤·버튼 뷰포트 포함·PNG 저장 assertion은 유지했다.
테스트 skip이나 러너의 임의 `/tmp` 생성으로 우회하지 않았다. 제품 코드는 변경하지 않았다.

## 검증

```bash
OPENCV_FOR_THREADS_NUM=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_registration_render.py tests/test_region_registration.py tests/test_tracking_callback_generation.py tests/test_release_notes.py -q --tb=short
```

- Linux offscreen: 38 passed (8.63초). `git diff --check` 통과.
- 실제 Windows 재실행·네이티브·exe 빌드는 이번 작업에서 미실행이다.
  일반 푸시의 Actions 중단 정책을 유지하며 Linux 통과로 Windows 성공을 주장하지 않는다.
- QA 보고서의 원래 Windows 실패와 네이티브/exe/게시 단계 skipped 결과는 그대로 유지한다.
- 잡담/영역 등록 후속 QA에서는 새 배포 차단 결함을 찾지 않았다. 표시 직전 두 번째
  노출 거절의 추가 로그는 P3 진단 개선이며 이번 경로 수정에 포함하지 않았다.

## 전달

기존 v0.4.86 태그를 삭제하거나 이동하지 않는다. 테스트 전용 수정이므로 공개 노트에
내부 CI 항목을 추가하지 않았다. 후속 QA에서 원격 태그와 노트를 확인해 다음 버전을
준비한다. 이 수정 푸시에서는 릴리즈 명령·태그·Release 게시를 진행하지 않는다.
