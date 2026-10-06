# mabinogi_addon

마비노기 화면을 실시간으로 분석해서 버프·디버프를 오버레이로 보여주는 Windows 상주 프로그램.
**전체 기획과 확정된 설계는 `docs/기획서.md`에 있다. 작업 전에 반드시 읽을 것.**

## 소통

- 한국어로 대화한다.
- 사용자는 Spring 백엔드 경력 10년+ 개발자. Python 데스크톱·Windows API·이미지 처리는 익숙하지 않을 수 있으므로,
  새로운 패턴이 나오면 "코드 → 런타임 동작 → 시스템 영향"을 짧게 브리핑 톤으로 설명한다.

## 개발 환경

- 회사 맥(Apple Silicon)과 집 Windows를 오가며 개발. 게임은 Windows에서만 실행 가능.
- Python 3.12, 패키지는 uv로 관리: `uv sync`, `uv run pytest`, `uv run mabinogi-addon`
- Windows 전용 의존성(dxcam, pywin32)은 `sys_platform == 'win32'` 마커로 분리되어 있다.
- 커밋 작성자는 이 저장소 로컬 설정(StarlineBot)을 사용한다. 회사 메일을 쓰지 않는다.

## 구조

```
src/mabinogi_addon/
  capture/   FrameSource 인터페이스와 구현체 (File / Video / Live(dxcam))
  detect/    아이콘 템플릿 매칭, 시간 판독(숫자·단위 템플릿)
  tracker/   버프 상태 머신, 내부 시계, 앵커 판정
  ui/        메인 창, 영역 지정, 오버레이, 트레이 (PySide6)
  system/    OS 의존 기능: 포그라운드 감지, 자동 실행, 중복 실행 방지, DPI
tests/
  data/      테스트용 스크린샷(PNG). 영상은 용량 때문에 git 제외
docs/
  기획서.md
```

## 규칙

- 화면을 **읽기만** 한다. 키 입력·클릭 자동화, 게임 메모리 읽기는 절대 넣지 않는다.
- OS 의존 코드는 `capture/`의 Live 구현체와 `system/`에만 둔다. 나머지는 맥에서 테스트 가능해야 한다.
- OpenCV는 `opencv-python-headless`만 사용 (일반판은 PySide6와 Qt 충돌).
- 성능 목표: 탐지 1회 5ms 이하, CPU 평균 1~2% 이하. 이미지 처리에 Python 픽셀 반복문을 쓰지 않는다.
- `cv2.setNumThreads(1)` 유지.
- 경로는 `pathlib.Path`로 다룬다 (맥/Windows 공용).
- 탐지 로직을 바꾸면 `tests/data` 기반 회귀 테스트를 추가하거나 갱신한다.

## 진행 상황

- [x] 기획 확정, 프로젝트 골격
- [ ] 1단계 탐지 엔진 (테스트 데이터 수집 필요: 기획서 10장)
- [ ] 2단계 GUI
- [ ] 3단계 오버레이
- [ ] 4단계 Windows 통합
- [ ] 5단계 보정·배포
