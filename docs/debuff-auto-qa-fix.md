# 디버프 자동 통합 QA 수정

- 대상: [독립 QA](qa/디버프_자동통합_독립_QA.md)의 `DEBUFF-AUTO-QA-01`.
- 원인: 준비 상태가 보존된 `debuffGateMode=percent`만 보고 자동 모드에도
  선택 사항인 보스 HP 영역을 필수로 추가했다. 같은 결과가 준비 문구와 자동찾기 후보에 전달됐다.
- 수정: 전달된 설정의 `debuffAutoGate is False`이며 `debuffGateMode=percent`인
  명시적 진단 3차에서만 HP 영역을 요구한다. 자동 플래그 없음/True는 HP 없이 준비 완료다.
  별도 경로 설정 재조회, 설정 초기화/저장, 추적 엔진 변경은 하지 않는다.
- 기존 공유 영역 테스트는 명시적 진단 3차 설정을 사용하도록 갱신했다. 필수 영역 검사는
  유지하며 자동 모드 조합과 로그인/비로그인 실제 준비 화면 회귀 21건을 추가했다.

## 실행 검증

- QA 원본 재현 코드 수정 없이 실행: 수정 전 **6 failed, 3 passed**, 수정 후 **9 passed**.
- 준비 화면·자동 엔진·원본 독립 QA 집중 검사: **183 passed (30.66초)**.
- 최초 전체 검사: **976 passed, 1 failed, 4 deselected**. 실패는 Discord 로그인
  테스트의 로컬 서버 바인딩이 샌드박스에서 `Operation not permitted`로 거부된 결과다.
  제품 코드나 assertion을 바꾸지 않고 로컬 서버 실행 권한으로 전체 검사를 다시 실행했다.
- 권한 적용 후 전체 격리 회귀: **977 passed, 4 deselected, 3 warnings (189.17초)**.
  제외는 별도 Windows 네이티브 검사 4건, 경고는 기존 QMouseEvent API 사용이다.
- QA 원본 문서와 재현 코드는 변경하지 않는다. 독립 후속 QA와 개발 검증은 구분한다.
- 기존 제품 `e60f67c`의 Windows 성공은 독립 QA에 기록되어 있지만, 이번 수정 커밋의
  Windows 회귀·네이티브·exe 빌드 결과는 별도로 확인해야 한다.
- 실제 게임·혼합 DPI·장시간 자원 사용은 이번 Linux offscreen 수정 검증 범위가 아니다.
  릴리즈·태그는 진행하지 않는다.
