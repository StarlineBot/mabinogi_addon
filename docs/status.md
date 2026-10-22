# 현재 상태

갱신: 2026-10-23. 개발·QA 결과는 이 문서의 관련 항목을 갱신한다. 커밋별 문서를 추가하지 않는다.
규칙은 [AGENTS.md](../AGENTS.md), 실행 절차는 [Windows 검증](windows-validation.md),
기능 명세는 [기획서](기획서.md)를 따른다. 과거 QA 문서는 필요한 근거만 찾아본다.

## 배포와 검증

- [v0.10.1](https://github.com/StarlineBot/mabinogi_addon-releases/releases/tag/v0.10.1) 게시 완료.
  태그 소스는 `035abc29`, exe와 업데이트 정보의 크기·해시 일치를 API로 확인했다.
- [검증 실행](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39724316823): 총 3분 20초.
  변경 기능 155개/10.47초, Windows 기동 2개/7.16초 통과. exe 빌드 단계는 1분 21초였다.
- [기존 후보 게시](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39724905534) 성공.
  게시 승인 실행 시작부터 완료까지 1분 9초였으며 검사·빌드는 반복하지 않았다.
- 사용자의 업데이트 후 RSS 적용 확인 실패 제보를 조사 중이다. 위 배포 결과는 빌드 exe의 실게임 검증이 아니다.
- 현재 CI 기준은 `d1387f0b`: 목표는 검증/게시 전체 5분, 배포 작업별 상한은 15분이다.
  5분 초과 성공도 목표 미달로 점검한다. 이 시간 정책 변경은 로컬 관련 검사 60개가 통과했고,
  위 실제 Actions 성공은 정책 변경 전 `035abc29`의 결과다.

## 열린 문제

- 0.11.1 라이브 제보 3건 — 0.11.2로 소스 수정 완료, Windows 실장치·실게임 미검증.
  재현 `uv run python -m scripts.qa_live_0111_rss_blackbox`는 수정 후 3건 not reproduced/종료 코드 0.
  - RSS 복구 잠김: 계획을 물리 코어 대표 CPU 기준으로 생성(9800X3D 7+1 → 14/1). 현재값이 적용 범위 안에서
    범위 필드만 줄어든 경우를 장치 정규화로 인정해, '네트워크 원복' 재클릭 시 값 확인 창 후 원본 재기록.
    기존 잠긴 recovery.json도 이 경로로 해소(스키마 불변, 다른 필드 변경은 계속 보류). 실제 NIC 정규화 규칙은
    사용자 화면값 기반 모형이며 실장치 적용·원복은 미검증.
  - 블랙박스 고해상도: 사용자 결정대로 native `bb_open_fit` + D3D11 비디오 프로세서 GPU 축소(CPU 복사 전),
    비율 유지·짝수·확대 없음·입력 최대 3840×2160·첫 출력 크기 고정·GPU 실패 시 중단. CPU 이후 1080p 경로 불변.
    **DLL 컴파일·GPU 축소·실게임 녹화는 미검증**(이 환경에 MSVC/Windows SDK 없음). 녹화 중 창이 첫 출력보다
    작아지거나 종횡비가 바뀌면 고정 출력에 맞춰 늘이거나 비율이 달라질 수 있어 실측 확인 대상.
  - 단축키: 'Ctrl+Alt+F10'처럼 키 이름 표시, 단축키 입력마다 결과를 6초간 오류 문구보다 우선 표시.
    훅 실제 수신은 녹화 정상 상태에서 실게임 확인 필요(미검증).
  - 독립 QA(2026-10-23, `65bccca`): 재현 3건 not reproduced/종료 0, 기존 기록(15/2→14/1) 해소 경로 포함.
    0.11.2 배포 검사 382건/31.73초, 최적화·블랙박스 관련 116건/9.91초 통과. 코드 검토상 배포 차단 없음.
    남은 점: 재현 스크립트 단축키 판정이 `startswith('VK ')`라 'Ctrl+Alt+VK 79' 형태 회귀를 못 잡음
    (`'VK ' in label`이 맞음, 테스트 보완 대상). native DLL 빌드·GPU 축소·RSS 실장치는 Windows 미검증.
- 0.11.2 실사용(독립 QA, 2026-10-23): 기존 RSS 잠김은 '네트워크 원복' 2회(정규화 확인)로 해소, '원복 완료' 확인.
  이어 '최적화 시작'(7+1, TCP는 기존 값과 같아 변경 없음) 결과 CPU 131개 적용 후 세션 중단·전부 원복,
  상태 "다른 도구가 CPU 배치를 바꿨어요", RSS 새 계획(14/1) 적용 1건 미적용·확인 필요.
  - Confirmed(코드): `engine.py` 소유 확인 루프는 적용한 프로세스 중 1개만 값이 달라도 세션 전체를 중단하고,
    어떤 프로세스인지 상태·로그 어디에도 남기지 않는다. 원인 프로세스(게임 자신 포함) 식별 불가.
  - Confirmed(코드): `_run`의 예외 처리가 status를 덮어 results/notices(RSS 미적용 이유 포함)를 버린다.
  - UX: 정규화 원복이 2회 클릭 구조, 새 작업 시작 시 이전 '원복 완료' 문구가 그대로 남아 진행 중 표시 없음.
  - 미확정: 실제로 배치를 바꾼 주체, RSS 14/1 확인 실패 이유(위 두 결함으로 정보 소실).
  - 재시도(CPU 끔, TCP+RSS): ack/nodelay/autotuning 변경 없음, "rss 미적용·확인 필요: 적용값을 확인하지
    못했어요" → 새 계획 14/1도 재시작 전 즉시 확인 실패. apply 실패 문구에 필드별 현재/적용 차이가 없어
    원인 미상(restore의 `_difference`처럼 표시 필요). CPU를 끄고도 "게임 실행 대기 · CPU는 아직…"으로
    세션이 게임을 기다리는 표시도 혼동 요인. 이 NIC에서는 RSS 두 계획 모두 확인 실패.
- 0.11.2 블랙박스 실사용: 입력 크기 오류는 사라졌으나 "BrokenPipeError: [Errno 32] Broken pipe"로 녹화 오류,
  확보 0초. 단축키는 Ctrl+Alt+F10으로 표시되나 사용자 체감상 무반응.
  - Confirmed(재현): `blackbox_codec.stream_process`가 인코더 비정상 종료 시 입력 스레드의 BrokenPipe를
    returncode/stderr 진단보다 먼저 raise한다. stderr에 실제 오류를 쓰고 exit 1 하는 가짜 인코더+1080p
    15프레임 입력으로 3/3회 BrokenPipeError만 표시됨. 실제 ffmpeg/h264_mf 실패 원인이 가려진다.
    수정 방향: 프로세스 종료 코드가 0이 아니면 stdin 쓰기 실패(BrokenPipe/ConnectionReset)보다
    `encoder exited N: <stderr>`를 우선 표시하고 app.log에도 남길 것. 그 뒤 실제 원인 재확인.
  - 단축키: 반응 문구가 6초만 표시돼 게임에서 누르고 앱으로 전환하면 이미 사라질 수 있다. 훅 수신 여부
    미확정. 앱 창을 앞에 둔 채 누르면 '게임 창이 앞에 있을 때만 저장해요' 문구로 수신 확인 가능.
    실기: 앱 창을 앞에 둔 상태에서는 해당 문구가 떠 훅 수신은 확인. 게임 창을 앞에 두고 누르면 문구 없음
    → 게임 포커스 중 WH_KEYBOARD_LL 미수신(코드상 수신 시 어떤 분기든 문구가 뜸).
    유력 원인: `7faf18a`(10/21)에서 `--uac-admin` 제거 → 실행 경로별 권한 불일치(더블클릭=일반, 자동실행 작업=최고
    권한, 업데이트 재실행=이전 권한 상속). 앱 일반·게임 관리자면 UIPI로 훅 미수신. 둘 다 관리자면 보안 모듈 차단 가능성.
    판별 대기: 작업 관리자 '권한 상승' 열(mabinogi-addon.exe/Client.exe), 관리자 실행 후 재시험.
    autostart.py/updater.py 주석은 아직 '항상 관리자' 전제라 현행과 불일치.
    확정(실기): 앱을 관리자 권한으로 실행하자 게임 포커스 중 단축키 문구가 떠 원인은 UIPI(권한 불일치).
    Highly Likely(코드): autostart.reconcile이 매 시작 `schtasks /Create /RL HIGHEST`를 호출하나 일반 권한
    실행에서는 등록이 실패해 로그만 남는다(신규 등록·해제 불가, 기존 작업은 잔존). 자동실행 작업 자체는 이미
    최고 권한이라 '자동실행만 관리자로'로는 해결 안 됨 — 더블클릭·업데이트 재실행 경로가 일반 권한.
    사용자 결정(2026-10-23): A) 항상 관리자 권한 실행(--uac-admin 복원). 자동실행 등록 실패 안내·주석 정리 포함.
  - Confirmed(코드): 녹화 실패로 남은 미완성 파일이 있으면 `BlackboxService.prepare_close`→`spool.close`가
    'owned sources must be resolved before close'로 실패해 앱 종료가 취소되고 '저장 내역·복구' 창이 뜬다.
    창은 이유·필요 조치 설명 없이 내부 ID를 노출하고, 해결 버튼(폐기)은 클릭 취소 결함에 걸려 사실상 종료 불가.
    개선 방향: 앱 톤의 확인 창 1개([지우고 종료]/[남겨두고 종료]/[취소]), 미완성 자료는 종료를 막지 않고
    다음 실행에 정리 안내, 내부 ID 대신 시각 표시.
  - 저장 내역·복구 창: 세션 `28508:…`과 '미완성 캡처 자료' 1건 → 캡처·GPU 축소 후 프레임이 인코더까지
    도달했고 첫 구간 인코딩에서 실패한 것으로 좁혀짐(축소 결과 화면은 미확인).
  - Confirmed(재현): '선택한 실패 자료 폐기' 무반응. 컨트롤러 100ms 타이머가 창 표시 중 매번 `refresh()`하고,
    목록을 비웠다 다시 채우며 폐기 버튼을 잠깐 비활성화해 누르는 중 클릭이 취소된다.
    `QT_QPA_PLATFORM=offscreen uv run python -m scripts.qa_blackbox_recovery_click`(미수정 시 REPRODUCED/종료 1).
    '원본 정리 다시 시도'는 runtime 정리만 하고 미완성 캡처 자료(orphan)는 처리하지 않으며 결과 안내도 없다.
    수정 방향: 내용이 바뀔 때만 갱신(또는 버튼 상태 유지), 정리 결과를 문구로 표시.
    사용자 실기 관찰로 확정: 폐기를 누르면 포커스가 '원본 정리 다시 시도'로 넘어가며 클릭이 사라지고,
    빠르게 두 번 누르면 확인 창이 떠서 삭제된다(갱신 사이에 누르고 떼기가 끝난 경우).
- 위 0.11.2 실사용 결함 → **0.11.3 소스 수정 완료**(개발, 2026-10-23). Windows 실장치·실게임 미검증.
  - 최적화: CPU 소유 확인은 달라진 프로세스만 관리 제외(`released`, 원복 안 함)하고 이름·PID·적용/현재 마스크를
    상태·로그에 기록, 게임 자신은 별도 문구. `_run` 예외는 기존 결과/안내에 이어 붙임. apply 확인 실패에 필드별
    현재/적용 표시(RSS 14/1 즉시 실패 원인은 다음 실사용 문구로 확인). 정규화 원복은 감지 즉시 확인 창(감지당 1회).
    시작/원복/환경 확인 시 상태 즉시 '…중', CPU 끈 세션은 게임 대기 없이 종료. RSS 체크는 이미 기본 꺼짐(저장 안 함).
  - 블랙박스: 인코더 비정상 종료 시 `encoder exited N: <stderr>` 우선 표시+app.log 기록(가짜 인코더 3/3 확인).
    복구 창은 내용이 바뀔 때만 다시 그림(`qa_blackbox_recovery_click` 종료 0). '원본 정리 다시 시도'는 정리 개수/
    대상 없음과 미완성 자료 폐기 경로 안내(미완성 자료 자동 삭제는 기존 정책대로 안 함). 마지막 단축키 입력
    시각·결과를 라벨에 계속 표시. 재현 스크립트 단축키 판정을 `'VK ' in label`로 강화.
  - 남은 점: 실제 h264_mf 실패 원인(새 문구로 실사용 확인), 0.25초 구간마다 ffmpeg+하드웨어 인코더를 새로 띄우는
    구조의 초기화 비용·동시 세션 제한(점검 대상, 미변경), 단축키 훅 실제 수신, RSS 실장치 확인.
- 0.11.2 validate-and-publish [39807034177](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39807034177)
  실패: Linux `Install Qt runtime libraries`의 apt install 120초 상한 초과(exit 124). 124MB 중 49개
  패키지(약 35MB)만 받음, archive.ubuntu.com 약 0.3MB/s(이전 성공 실행은 124MB/19초). 테스트·DLL 빌드·게시 미실행.
  코드 원인 아님. 반복 재발(0.11.1 다운로드 제한 실패 포함) → 근본 대책은 CI 동결 해제 승인 필요(.deb 캐시 등).
  재실행 [39808027057](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39808027057) 성공(apt 1분50초,
  배포검사 23초, Windows 기동 13초, exe·DLL 빌드 6분2초) → 게시 성공. v0.11.2 태그 `d41298a`, Release exe
  sha256 `94091c7c…728f`/162,530,922 bytes가 후보 manifest·version.json과 일치. 실게임 확인은 남음.
- v0.10.1 RSS: 사용자 조회의 CPU 범위 14~15·MaxProcessors 2·큐 2·ClosestStatic은
  요청값과 일치했지만 두 그룹 값이 null이었다. 이 입력은 기존 코드에서 동일한 적용 확인
  오류를 재현했다. 단일 활성 그룹을 Windows API로 확인한 경우에만 null을 0으로 보완했다.
  실제 Windows API/장치 적용·원복은 아직 미검증이다. 기존 recovery.json은 삭제하지 않는다.
- 전체 회귀 #92 (`07850f0f`, 실행 `39715832248`)의 정체 원인은 미확정이다.
  API에서 Qt 로딩 성공·약 25분 후 취소 종료·Windows 빌드 미실행을 확인했다.
  사용자 제공 Annotations는 20분 제한 초과였고, 같은 실행 URL에 대한 로그는 46%까지 PASSED였다.
  API 원본 로그는 404였다.
  마지막 사용자 제공 자원 샘플은 가용 메모리 약 14.2GiB·디스크 84GiB·OOM 0이었다.
  이를 libpulse 누락과 같은 원인으로 분류하지 않는다. 전체 회귀는 배포 필수 경로가 아니다.

## 마지막 작업

### 0.11.3 실사용 결과 수정 — 최적화 세션·블랙박스 진단·복구 창

- 로컬 `run_release_checks --version 0.11.3` 391건/28.26초, 노트·정책 216건, 재현 스크립트 2종 종료 코드 0.
  새 회귀(A1·A2)는 수정 전 코드에서 실패함을 확인. 단축키 라벨 2줄 렌더 미리보기를 사용자에게 공유.
- Actions·태그·배포 미실행. CI apt 캐시는 승인 대기(이번 범위 아님).

### 0.11.2 라이브 제보 수정 — RSS 잠김·블랙박스 1440p·단축키 표시

- 커밋: RSS 물리 코어 계획·정규화 원복, 단축키 키 이름·반응 표시, 블랙박스 GPU 축소. 노트·변경 검사 목록 0.11.2.
- 로컬 `QT_QPA_PLATFORM=offscreen uv run python -m scripts.run_release_checks --version 0.11.2` 382건/24.94초 통과,
  릴리즈 노트·정책 216건 통과. 재현 스크립트 종료 코드 0.
- Actions/Windows 검증·태그·배포는 실행하지 않았다. native DLL 변경이 있어 0.11.2 후보는 `windows.yml` verify-only로
  DLL 빌드부터 확인해야 하며, 실제 GPU 축소·RSS 장치 원복·단축키 수신은 실게임 QA 대상이다.

### 0.11.1 설치 개선 후보 — 모든 job 성공, run 상태 갱신 대기

- [39797107299](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39797107299),
  SHA `de4178a69a9b64368392c0b8db2ed8ec2614ac52`, version0.11.1, verify-only, attempt1.
- Linux 공식archive다운로드124MB/19초(기존156MB보다32MB감소),347건/18.48초통과.
  Windows기동2건/6.61초,codec host14:40:12,DLL14:40:23,FFmpeg14:43:43,
  exe14:45:10(162520572bytes)빌드성공. validate job은14:45:23completed/success확인.
- 후보artifact12434910896, verified-windows-39797107299-1,163619539bytes,
  만료2026-10-23T14:45:15Z. APIarchive digest
  `ebc0f48189198fcaa042fc86d313531fe0fef2cc3ae73a9a4d1572ce10f0fffb`(exe해시아님).
- 개별job/단계성공에도run및attempt전체API는in_progress/conclusionnull이어서최종갱신확인대기.
  성공후사용자수동입력은windows.yml/main/version0.11.1/modepublish-existing/candidate_run39797107299.
  현재게시실행하지않음. 후보manifest다운로드/로컬exe해시대조는미수행이며게시gate가재검증한다.
- 증거 `/tmp/verify-39797107299-linux.log`, `/tmp/verify-39797107299-windows-excerpt.log`.
  실게임단축키/RSS최초차단/실제녹화오류해결은미검증. 추가run/태그/Release/배포없음.

### 승인된 최소 apt 설치 개선

- 사용자 승인 범위로 기존 runner 미러의 Ubuntu 공식 archive 우선순위를1로, Azure를2로
  교체하고 install에 --no-install-recommends만 추가했다. security3과기존fallback목록은그대로다.
  예상archive항목이없으면명확히실패하며알수없는sources로진행하지않는다.
- 필수7패키지와의존성,서명검증,update60초/install120초/kill10초/retry1,테스트/배포gate유지.
  캐시·미러순환재시도·시간연장·검사skip은없다. 실제다운로드속도개선은후보실행에서확인한다.
- 개발 workflow/release-checks 최종검사53건/3.95초통과. 설치명령은mock으로검사했고
  로컬호스트패키지/미러는변경하지않았다. 외부네트워크속도성공을뜻하지않는다.
  독립QA workflow40건/1.72초및정상/공백/이미교환/항목누락4모형통과.
  `/tmp/apt_mirror_independent_qa.py`. 설치shell외workflow/gate동일확인.

### 0.11.1 단축키 포함 후보 검증 — 다운로드 제한 재실패

- 사용자 승인 1회 [39793252768](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39793252768),
  SHA `531474fed8554e1f004fe76dcf4a1e31c0197638`, version0.11.1, verify-only.
  run 최종 completed/failure 확인(updated14:18:11UTC). 요청 준비 성공, Linux 의존성 설치 실패.
- update는12.5MB/1초로 성공했으나 install120초/exit124가 재발했다. 이번 마지막 실제
  다운로드 항목은14:12:03의libavformat60(1153kB),14:12:05에시간초과. 폰트까지도달하지
  않았으므로 fonts-noto-cjk 하나의 문제로 분류하지 않는다. 상세 로그는
  `/tmp/verify-39793252768-job.log`, 상태 추적은 `/tmp/verify-39793252768-watch.log`.
- 검사/Windows기동/native/FFmpeg/exe빌드 미실행. 아티팩트는 release-request-39793252768-1
  (12430919845,402bytes)뿐이며 verified candidate가 없으므로 게시 입력을 제공하지 않는다.
  개별job상태API는로그완료후에도늦게갱신됐으며run최종실패와설치실패원문을구분확인했다.
- 추가 Actions/설치방식·시간제한 변경/태그/게시/배포는 하지 않았다. 단축키 로컬347건과
  독립QA결과는 유효하지만 실제 Windows게임 단축키/RSS최초차단/녹화오류 해결은 미확정이다.


### 블랙박스 지정 단축키 관찰 방식 전환

- 사용자가 기존 실패 방식의 재검증보다 참고 앱 방식 우선 구현을 지시했다.
  참고 저장소는 기존 기획에 명시된 rubystarashe/nogirem, 조사 SHA는
  `4b68b4e7f481761a61121c37bf7ded37519f078e`다. 외부 소스 복사/실행 없이 공식 API 기반 자체 구현했다.
- 기존 폐기 커밋5caead7은 GameGuard와 양쪽 High 권한을 이유로 기록했지만,
  당시 thread 등록 필터가 windows_generic_MSG만 수락해 dispatcher 메시지를 제외할 수 있었다.
  따라서 과거 원인을 GameGuard 하나로 확정하지 않는다. 이번 선택은 사용자 우선순위를 따른다.
- RegisterHotKey를 WH_KEYBOARD_LL 전용 메시지 스레드로 대체한다. 지정 조합 상태만 유지하고
  키 로그 없이 항상 CallNextHookEx로 전달한다. 주입 입력/자동 반복을 제외하고 key-up을 반영한다.
  수신시각/foreground HWND를 최대2개 보존하고 GUI 소비 시 게임 foreground와 제작자 권한을
  재확인한다. GUI 처리시각으로 저장 끝점을 늦추지 않는다. 넘침/등록/루프/해제 실패를 표시한다.
- 키 훅에서 UI를 호출하거나 게임 입력을 생성/소비하지 않는다. 권한 상승·게임 주입·보안 우회는 없다.
  Ctrl+Alt+F10, 녹화/저장 조건과 세션 잠금·절전 처리는 유지한다.
- 개발 모형 12건 통과. 독립 QA에서 잠금 중 key-up 누락 뒤 수식 키 상태가 남아 단독 F10이
  접수되는 결함을 재현했고, 입력 세대를 경계마다 무효화해 수정했다. 지연 콜백도 이전 세대로 폐기한다.
  수정 후 공동 검사 `uv run python -m scripts.run_release_checks --version 0.11.1`는
  347건/38.49초 통과(`UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen`).
  로그 `/tmp/hook-0.11.1-final-checks.log`, XML `/tmp/hook-0.11.1-final-results.xml`.
  수정 후 독립 QA 관련27건/3.30초 및 별도4모형 통과. 잠금/절전 키 상태 잔존과 지연 콜백,
  CallNextHookEx 반환, 수신 끝점, 비활성/다른 HWND/권한 해제, 해제/종료 경계를 재검증했다.
  독립 재현 `/tmp/blackbox_hotkey_independent_qa.py`. 검사 범위의 추가 결함은 발견하지 못했다.
- 실제 Windows 훅 등록/게임 수신은 미검증이다. OS가 느린 훅을 조용히 해제할 수 있으므로
  등록 또는 모형 성공을 게임 지원 완료로 보고하지 않는다. 이 변경의 Actions는 미승인·미실행이다.


### 0.11.1 비게시 검증의 의존성 설치 실패

- 사용자 승인 1회 실행 [39790964211](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39790964211),
  SHA `626f50844481212c96ca6706bb78b9cd3b6844e4`, version0.11.1, mode verify-only.
  request 성공, regression 의존성 설치 실패, Windows validate skipped. 후보는 생성되지 않았다.
- apt update는 12.5MB/1초로 성공. install은 156MB 다운로드 요청 후 120초 제한으로 exit124.
  마지막 다운로드 항목은 fonts-noto-cjk 61.2MB이며 단독 원인으로 단정하지 않는다.
  테스트/네이티브/exe 빌드 전 실패다. 로그 `/tmp/verify-39790964211-failed.log`.
- 상세 조사: update는 13:54:30~34에 완료했고 install은 13:54:35부터 시작했다.
  신규103개/156MB 요청, 첫 libva2 다운로드 로그는13:54:50, ffmpeg는13:56:01,
  fonts-noto-cjk 61.2MB는13:56:03, 제한 종료는13:56:34다. 404/서명/의존성 오류나
  dpkg unpack/configure 로그 없이 다운로드 단계에서 종료됐다. 폰트만의 오류로 단정하지 않는다.
  이전 성공39771240282는 동일156MB를8초/20.1MB/s에 받았다. 이번에는 여러 패키지 전송이
  느렸으며 원격 미러/네트워크의 구체적 내부 원인은 현재 로그로 구분할 수 없다.
- 제한 시간/필수 패키지/검사를 유지한 채 원인을 해결한다고 입증할 최소 코드 수정은 없다.
  재시도만으로 해결을 보장하지 않는다. 캐시·미러 변경·다운로드 분리 등 설치 구조 변경은
  별도 범위이며 이번에 도입하지 않았다. 추가 실행·CI 변경·태그·게시도 하지 않았다.
  진행 중 요청된 단축키 전환은 이 실행 SHA에 포함되지 않는다.


### 블랙박스 녹화 오류 진단 및 버퍼 경계 보완 — 0.11.1 준비

- 사용자 화면의 `0x8007007a`는 확인했지만 발생 단계는 기존 메시지로 구분할 수 없다.
  영상 용량 초과, 오디오 패킷 용량 초과 또는 하위 API 반환이 가능하다. 사용자 해상도나
  오디오를 원인으로 단정하지 않으며, 실제 녹화 오류 해결로 보고하지 않는다.
- 영상 용량 초과 시 실제 너비·높이를 반환하고 COM/영상/오디오의 시작·읽기 오류를 구분한다.
  오디오 GetBuffer의 실제 크기를 64비트로 다시 검사하고 초과하면 복사 없이 버퍼를 반환한다.
  기존 입력 1920×1080, 메모리 한도와 게임창/프로세스 오디오 범위는 유지한다.
- 개발 producer/service/window-probe 19건/2.56초 통과. 독립 QA 관련 22건/5.03초 및
  실제 bb_audio_read를 추출한 C++ 모형 7개 경계 통과. signed HRESULT, 반환 실패,
  실제 패킷 초과, 32비트 크기 초과와 출력 경계 보존을 확인했다.
  독립 재현 `/tmp/blackbox_audio_bounds_qa.py`. Windows SDK 컴파일·실제 캡처는 미검증이다.
- FPS/RSS/블랙박스 보완 공동 후보 0.11.1로 기존 21개 변경 검사 목록의 버전만 맞췄다.
  `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m scripts.run_release_checks --version 0.11.1`
  공동 변경 검사 330건/23.94초 통과. 로그 `/tmp/combined-0.11.1-checks.log`,
  XML `/tmp/combined-0.11.1-results.xml`. 검사 약화/게이트 변경, Actions 실행, 태그·릴리스·배포는 하지 않았다.


### RSS 원복 실제 제보 조사 및 재연결 후 검증 보완

- 사용자0.11.0 제보는 RSS failed 기록과 원복 보류/시작 차단이다. 제공된 숫자값은 applied와 같고
  Profile2는정적Closest프로필, 그룹값은null이었다. 앱동일 문자열조회+단일그룹 보정에서는
  applied와일치한다. 공개exe내 코드도직접확인했으며 보정 누락이아니다. 사용자조작/버전탓으로판단하지않는다.
- 독립 전체경로(_ps UTF8/JSON→read→Recovery재로드→Engine→UI) 조사에서 별도확정결함:
  재연결전원복확인만하여 드라이버가 재연결후값을바꾸면 원복완료/시작허용이될수있었다.
  반대로 재연결전불일치→재연결후applied와일치하면 이전오류와pending이남는다.
  실제사용자PC가이순서를겪었는지는미확정이며 원제보완전해결로보고하지않는다.
- 원복요청경로만 재연결후기록된원본과다시조회/비교한다. 불일치/조회실패시failed와원본및
  재연결표식을디스크에보존하여시작을차단한다. 추가원복쓰기·기록삭제·guard완화는없다.
  기존불일치문구는외부조작단정대신 비교시점RSS필드의현재/적용/원본값을표시한다.
  GUID/어댑터이름/PowerShell원문은출력하지않는다. 정상적용경로의재연결은변경하지않았다.
- 수정전재연결후값변화모형에서잘못된원복완료를재현. 수정후개발관련137건/28.02초,
  독립QA92건/23.67초및별도6시나리오통과. 정상/값변화/조회실패/중간종료재로드/부분적용/
  이전시점불일치에서원본보호와UI시작/복구상태를검증했다.
  `/tmp/rss-post-restart-tests.log`, `/tmp/rss_engine_fix_independent_qa.py`.
- Windows실제RSS적용/원복은미실행. 원제보추가판별에는동일GUID의앱동일조회(문자열Profile),
  활성그룹수, 비교시점및restart_targets가필요하다. FPS수정과공동후보검증은아직실행하지않았다.

### FPS 시작 후 게임 전환 시 측정 종료 회귀 수정 — 0.11.1 준비

- 사용자 제보: 이전 버전에서 보이던 FPS가 0.11.0에서 앱의 측정 시작 후 게임으로 전환하면
  표시되지 않고, 앱 복귀 시 시작 전 상태로 돌아갔다. 단순 버튼 비활성화가 아닌 측정 종료다.
- 이전 정상 배포035abc29와0.11.0의3d8e9a8c 차이를 추적했다. 새 `_line` 비활성/최적화 전환
  필터가 PresentMon의 최초 CSV 헤더까지 버렸고, 게임 진입 후 데이터에서 헤더 없음 오류로
  `_failed → stop_frames`가 실행됐다. 수정 전 같은 UI 경로 모형에서 해당 메시지와 frames=False를 재현했다.
- 헤더 검증/보존과 표본 수락을 분리했다. 비활성·최적화 전환 중에도 헤더는 유지하되 프레임은
  집계하지 않는다. 권한 해제·잘못된 헤더·PID·누락 오류 보호와 AltTab 구간 분리는 유지한다.
  v1+BOM 및 modern 헤더에서 앱 시작→게임 진입→오버레이50FPS/측정 유지 회귀 검사를 추가했다.
- 개발 FPS/UI/요약/RSS/노트81건/20.78초 통과. 독립 QA 관련50건/20.10초 및 별도4개 모형 경계
  통과: 비활성 시작, AltTab 재개, 다른 스레드가 복구 lock 보유 중 헤더 수신, 잘못된 헤더/PID 보호.
  최신 v1+BOM/modern UI2사례도 독립 QA에서2.39초에 재통과했다.
  로그 `/tmp/fps-focus-regression-tests.log`, 독립 재현 `/tmp/fps_header_independent_qa.py`.
- 실제 Windows 게임 수정본 실행은 미검증이다. 버그 수정 노트0.11.1만 준비했으며 Actions/
  릴리스/태그/배포는 실행하지 않았다. 배포 후보 검사 목록 확정과 새 후보 검증은 아직 별도다.
- RSS 원복 차단은 미해결이다. 사용자 제공 old/applied/current는 단일 그룹·문자열 Profile 조건에서
  일치해 개발/독립 모형에서 원복 성공했다. 배포 exe에도 그룹 null 보정과 Profile 문자열 조회가
  포함됨을 확인했다. raw numeric2 직접 입력은 외부 변경이 아닌 형식 오류다. 강제 원복·기록 삭제·
  guard 완화를 하지 않았으며 실제 비교 시점 차이의 근거가 아직 부족하다.

### 0.11.0 여섯 번째 비게시 후보 검증 성공

- [verify-only #39771240282](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39771240282),
  소스 `3d8e9a8c2c5583b67799aefbb7848118937326cc`, 버전0.11.0, attempt1 성공.
  Linux 변경검사320건/19.05초, Windows 최소 기동2건/9.08초 통과.
- 실제 Windows에서 codec host(11:34:14), native DLL(11:34:27), FFmpeg(11:37:24),
  앱 exe(11:38:47, 162,512,589바이트) 생성 확인. candidate seal/업로드까지 성공했다.
  이전 namespace/projection 컴파일 오류는 이 SHA에서 해소됐다. 실제 게임 캡처/프로세스 오디오/
  하드웨어 인코딩/게임 부하 및 RSS 실제 장치 적용은 미검증이며 빌드 성공과 구분한다.
- request16초/Linux1분1초/Windows5분52초, 전체11:31:41~11:38:56 UTC 7분15초로5분 목표 미달.
  apt 약21초(156MB/8초), exe 빌드 약4분57초. 네이티브는 빌드 시작37초 이내 완료했고
  이후 FFmpeg 준비/빌드 약3분, 최종 패키징 약1분20초가 남았다. 이번 다운로드는 빨랐으므로
  속도 차이를 timeout 수정의 효과로 단정하지 않는다. 캐시는 승인/도입하지 않았다.
- 후보 `verified-windows-39771240282-1`, artifact12422911841, 163,608,231바이트,
  만료2026-10-23 11:38:49 UTC. API 아티팩트 SHA256:
  `9fc367e5c47fcc4a055754f2866b99e9b9205401b31ee3761f6ec15e98b0bc02`.
  이는 아티팩트 해시이며 exe 해시가 아니다. 후보 다운로드는 Azure Forbidden으로 거부되어
  재시도/우회하지 않았고 로컬 manifest/파일 해시 대조는 수행하지 못했다.
  정상 완료 로그는 `/tmp/blackbox-verify-39771240282-full.log`에서 확인했다.
- 수동 게시 입력은 windows.yml/main, version0.11.0, mode publish-existing이며 후보 run은39771240282.
  기존 게시 절차가 후보 출처/manifest/해시/유효기간을 다시 검증한다. 사용자만 게시를 실행한다.
  v0.11.0 미사용 확인. 7차 실행/태그/Release/배포는 수행하지 않았다.

### 0.11.0 설치 대기 제한 및 네이티브 선행 컴파일

- 사용자가 최소 두 개선과 수정 후 여섯 번째 verify-only 1회를 승인했다. apt update60초/
  install120초, 종료 유예10초, HTTP/HTTPS 연결15초·재시도1회로 제한했다. 실패 시 단계/종료코드/
  제한시간과 마지막80행을 출력하며 update 일부 실패도 오류 처리한다. 필수7패키지는 그대로다.
- native configure/build를 FFmpeg 다운로드·빌드 앞으로 옮겼다. 실패 시 FFmpeg에 진입하지 않는다.
  캐시 도입·검사 생략·게이트 변경·시간 상한 증가는 하지 않았다. 실제 성공 소요시간은 미측정이다.
- 개발 관련51건/1.71초, 실제 변경 기능 검사320건/21.14초 통과. 독립 QA 관련56건/2.08초 및
  설치 성공/update·install 실패·시간초과·강제종료 6개 모형 경계 통과. 실제 미러/Windows는 별도다.
  개발 로그 `/tmp/blackbox-sixth-local-checks.log`, 독립 재현 `/tmp/blackbox_apt_boundaries_qa.py`.

### 0.11.0 다섯 번째 후보 검증 — Linux 설치 시간 초과

- 승인된 [verify-only #39768567858](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39768567858)을
  `23bb753ffa6a2cad5fd87f3a6b9047e3ea84f193`/0.11.0 대상으로 중복 없이 1회 실행했다.
  request 성공, regression cancelled(11:10:36~11:25:56 UTC, 15분20초), Windows validate skipped.
  Check annotations에서 `The job has exceeded the maximum execution time of 15m0s`를 확인했다.
- Install Qt runtime libraries는 11:10:52~11:25:51 동안 실행됐다. Linux 변경 기능 검사는 미실행이며
  Windows native DLL/codec host/앱 exe/verified candidate도 이번 실행에서 생성되지 않았다.
  아티팩트 목록에는 release-request만 있다. 실게임/장치 검증과 게시도 수행하지 않았다.
- 해당 job 로그 다운로드가 Azure 전송 단계에서 Forbidden으로 거부되어 재시도/우회하지 않았다.
  설치 내부의 정확한 지연 원인은 미확인이다. 기존 4차 로그의 Ubuntu 미러 Ign 재시도는
  별도 관측이며 이번 지연의 원인으로 확정하지 않는다. 6차 실행은 미승인이다.
- 시간 개선 읽기 검토 및 독립 QA: 4차 apt는 인덱스12.5MB/17초, 패키지156MB/1분46초,
  전체 설치 약2분14초였다. 네이티브는 FFmpeg 의존성이 없지만 FFmpeg 다음에 실행되어
  빌드 시작 약3분17초 후 컴파일 오류가 발견됐다. 선행 컴파일은 실패 발견을 앞당기며
  정상 빌드 총시간 단축을 보장하지 않는다. FFmpeg는 매회 새 임시 폴더에서 빌드한다.
- 최소 개선 후보는 native 선행 컴파일, apt 권장 패키지 제외의 영향 검토 및 연결/재시도 제한,
  원본 압축파일 캐시와 매회 고정 SHA 재검증이다. apt update 무조건 생략이나 미검증 바이너리
  재사용을 권하지 않는다. 빌드 산출물 캐시는 recipe/컴파일러/소스/고지까지 검증해야 한다.
  CI 동결에 따라 개선안은 승인 전 적용하지 않았으며 시간 상한·검사·게이트를 유지했다.

### 0.11.0 네 번째 후보 검증 및 projection 헤더 보완

- 정상 제공된 CLI 인증이 `gh auth status`로 복구됐음을 먼저 확인하고 공개/main SHA/중복0건을 점검했다.
  승인된 [verify-only #39767008861](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39767008861)을
  `629253976e16a029921b2f518da3ef0c9a1e26f6`/0.11.0으로 정확히1회 실행했다. RSS 수정224ef70 포함 확인.
- 실제 Linux 변경검사 **318건/16.30초**, Windows 최소 기동 **2건/11.10초** 통과.
  FFmpeg/ffprobe 설치 및 `blackbox_codec_host.exe` 생성 성공. 이전 namespace 오류는 사라졌다.
  capture.cpp37행 session/pool.Close에서 C3779 `Windows_Foundation_IClosable::Close` 정의 누락으로
  native DLL 빌드 실패. 최종 앱 exe/verified candidate는 생성되지 않았다.
- 전체10:57:52~11:06:02 UTC 약8분10초로5분 목표 미달. request26초/Linux2분59초/Windows4분32초.
  시간제한이나 게이트를 변경하지 않았다. 로그 `/tmp/blackbox-verify-39767008861-{full,failed}.log`.
- `winrt/Windows.Foundation.h`를 명시적으로 포함해 IClosable.Close/TimeSpan 정의를 가져오고,
  직접 사용하는 SizeInt32의 `winrt/Windows.Graphics.h`도 명시했다. 나머지 Capture/DirectX/Direct3D11
  projection과 SDK interop 헤더를 전수 점검했다. audio/host는 C++/WinRT projection을 사용하지 않는다.
  근거: [Microsoft C++/WinRT C3779 안내](https://learn.microsoft.com/en-us/windows/uwp/cpp-and-winrt-apis/faq),
  [명시적 projection 헤더 규칙](https://learn.microsoft.com/en-us/windows/apps/develop/cpp-winrt/get-started).
- 개발 관련24건/2.96초, 독립 QA24건/2.60초 통과. 독립 QA는 모든 projection 메소드/반환형,
  COM interop 구분, audio/host 헤더 및 CMake 링크 라이브러리를 검토했고 추가 확정 누락은 없었다.
  이 수정 후 실제 Windows SDK/MSVC 컴파일은 아직 미검증이다.
  이후 승인된 다섯 번째 검증 결과는 위 항목에 기록했다. 태그/릴리스/배포는 실행하지 않았다.


### RSS 그룹 누락 조회 보완 — 2026-10-22

- 사용자 조회와 같은 null 그룹 입력으로 기존 코드의 적용 확인 오류를 재현했다.
  단일 활성 그룹을 Windows API로 확인할 때만 0으로 보완하며, 명시된 그룹·다른 값은 추정하지 않는다.
- 수정 전 재현 검사는 동일 오류로 실패했다. 최신 원격 main에 합친 뒤 최적화/UI/FPS 요약/
  릴리즈 계획145개가 로컬에서17.60초에 통과했다. 외부 변경 보호와 기존 failed 기록 원복도 검사했다.
  실제 Windows API/장치 적용·원복 성공은 아직 검증하지 않았다.
- 동시 개발된 원격 main의 블랙박스/FPS 변경을 보존해 0.11.0 노트에 함께 반영했다.
  이 작업에서는 workflow/감독기/배포 게이트를 변경하거나 Actions·태그·게시를 실행하지 않았다.

### 0.11.0 세 번째 후보 검증 및 네이티브 이름 충돌 수정

- 추가1회 승인으로 main `b32510034ca1f452269fde5d15bf30f6517b1338`/0.11.0에
  [verify-only #39765171693](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39765171693)를 정확히1회 실행했다.
  실행 전 공개 표준러너/main SHA 일치/중복0건을 확인했다.
- 직접 확인: request11초 성공, Linux regression1분5초 성공, Windows 최소 기동 성공.
  CLI 상태추적이 HTTP401 Bad credentials로 종료돼 조회를 중단했으며 재시도/우회하지 않았다.
- **부모의 정상 GitHub connector 조회 근거**: validate job119779279869는10:50:46 UTC failure.
  FFmpeg `INSTALL ffmpeg.exe`10:48:43 완료 후 native capture.cpp14~16행에서 C2872 `Windows` ambiguous.
  SDK의 `::Windows`와 C++/WinRT의 `winrt::Windows`가 충돌했다. audio.cpp 오류는 해당 로그에 없었다.
  최종 exe/후보는 생성되지 않았다. FFmpeg 경로 수정 후 빌드는 진전됐지만 전체 성공은 아니다.
- capture.cpp의 using namespace3개를 `winrt::Windows`로 명시하고 DXGI interop 접근은
  SDK 헤더에 정의된 `::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess`로 명시했다.
  native 나머지 파일에는 같은 모호한 Windows 참조가 없다. 캡처 동작·권한·오디오 정책은 변경하지 않는다.
- 개발 producer/windowprobe/bundle/startup 회귀24건/12.16초 통과. 추출된 실제 using 선언과
  두 Windows namespace 타입 모형의 g++ C++20 syntax 검사는 수정 전 ambiguous 실패/수정 후 성공.
  재현 파일 `/tmp/blackbox-namespace-{before,after}.cpp`. 독립 QA도 실제 선언/as표현식 추출 모형의
  수정 전 실패/수정 후 성공과 네이티브 전수참조를 확인했고 관련22건/1.35초 통과했다.
  독립 재현 `/tmp/blackbox_namespace_qa.py`. 실제 MSVC/Windows SDK 전체 컴파일은 미검증이다.
- 최초 수정 푸시는 원격 선행 변경 때문에 fetch-first 거부됐다. 정상 git fetch로 원격224ef70의
  RSS 그룹 수정5파일을 확인해 보존하고 rebase했다. status 기록 충돌만 양쪽 보존으로 해결했으며
  앱 코드 충돌은 없었다. 통합 실제 릴리스 검사318건/18.03초 통과(`/tmp/blackbox-rss-integrated-results.xml`).
  독립 QA는 RSS 코드/테스트/노트/명세 보존과 변경범위를 확인하고 관련69건/1.74초 통과했다.
- 네 번째 Actions/태그/게시/배포는 미승인으로 실행하지 않는다. CLI401 조회는 재시도하지 않는다.

### 0.11.0 두 번째 후보 검증 및 빌드 진단 보완 — 2026-10-22

- FFmpeg 검사 의존성 수정 `b19849ce91d5fb77d7cf9fcb786052f9331ef69a`의 main 반영 후,
  추가1회 승인에 따라 [verify-only #39763839419](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39763839419)를 실행했다.
- 실제 Linux 변경검사 **308건/16.12초**, Windows 최소 기동 **2건/8.37초** 통과.
  request14초, Linux작업2분36초, Windows작업1분54초. 결과는 **failure**다.
  Windows FFmpeg configure에서 `C compiler test failed`로 중단됐으며 native CMake/DLL/codec host,
  PyInstaller exe/후보 생성은 미실행이다. 실게임/장치 검증도 없다.
- 당시 `MSYS2_ARG_CONV_EXCL='*'`가 native LLVM의 POSIX 임시 파일 경로 변환을 막고 있었다.
  [MSYS2 공식 경로 문서](https://www.msys2.org/docs/filesystem-paths/)와 FFmpeg configure 임시 파일
  전달 경로상 유력 원인이지만 실제 config.log가 없어 이번 실패의 확정 원인은 아니다.
  빌드 전용 환경에서 상속된 차단값까지 해제하고, configure 실패 시 config.log 마지막80줄을
  출력한 뒤 원래 종료코드를 유지하도록 최소 수정했다. 컴파일러 pin/제품정책/CI 게이트는 유지한다.
- 개발 bundle/startup/WindowsCI 최종 **52건/1.68초** 통과. 경로변환 설정/원본환경 보호 및 합성
  configure 실패진단·종료코드 보존을 검사했다. 독립 QA가 찾은 tail 실패 시 원래 종료코드 덮임을
  수정하고 별도 재현 및 관련15건/0.82초 재통과했다. Linux 모형 통과는 Windows 빌드 성공이 아니다.
- 로그 `/tmp/blackbox-verify-39763839419-{full,failed}.log`. 이전 거부 아티팩트 다운로드는 재시도하지 않았다.
  기존 `/tmp/blackbox-minimal-build/review-bundle`은 이전 recipe의 교차 빌드 참고물이며 이번 수정의
  검증된 Windows 산출물이 아니다. 다음 실제 빌드는 현행 recipe/대응소스/해시를 새로 생성한다.
  세 번째 Actions는 미승인으로 실행하지 않는다. 태그/게시/배포도 실행하지 않았다.


### 0.11.0 첫 Windows 후보 검증 — 2026-10-22

- **후속 수정**: 부모가 기존 패키징 승인에 포함되는 최소 통합임을 확인해 Linux apt 목록에
  ffmpeg1패키지만 추가했다. test_support.codec_tools는 ffmpeg/ffprobe 누락 시 필요한 설치 항목을
  명시적으로 실패로 알린다. 자동 다운로드/skip/검사완화/제품용 번들 변경은 없다.
  같은 검사목록의 외부 실행 도구를 확인했으며 실제 합성검사는 FFmpeg/ffprobe를 쓰고,
  네이티브/CMake/패키징 검사는 모형으로 격리돼 Linux에서 Windows 도구를 요구하지 않는다.
- 개발 실제 릴리스 검사308건/18.567초(실패·skip0), CI/검사목록50건/1.41초 통과.
  실행 서버 연결 단절로 스트리밍 세션이 유실됐으나 저장된 완결 XML로308건 결과를 확인했다.
  결과 `/tmp/blackbox-fps-release-0.11.0-ffmpeg-results.xml`.
  독립 QA59건/5.34초 통과. 도구 개별/전체 누락 및 Windows host 조건 유지, 추가 외부 도구 누락 없음 확인.
  사용자가 수정 후 verify-only 추가1회도 승인했으며 푸시 후 새 SHA로 실행한다.


- 공개 main `f96770d61e8391b80a4db504d92fd3936414fd20`에 공동 변경67파일 푸시 및 원격 반영 확인 완료.
  사용자의 별도 승인으로 [verify-only #39762819006](https://github.com/StarlineBot/mabinogi_addon/actions/runs/39762819006)을 정확히1회 실행했다.
  공개 저장소/표준 ubuntu·windows 러너와 중복실행없음을 확인했다. 비용API403은 재시도하지 않았다.
- 결과 **failure**: request14초 성공, Linux regression62초 중 변경검사 **107통과/6실패(5.10초)**.
  `shutil.which('ffmpeg')`가 None인 상태에서 `Path(None)` TypeError. Ubuntu 준비 단계가 Qt 라이브러리만
  설치하고 합성검사에 필요한 ffmpeg/ffprobe를 설치하지 않은 원격 테스트 준비 누락이다.
  독립 QA도 ffmpeg/ffprobe 탐색 실패 모형에서 같은 TypeError6건을 재현했다(6실패/2통과,0.45초).
  제품 bundle 접근 전 fixture 실패이며 제품 MF 번들 결함을 입증한 결과는 아니다.
  Windows validate는 skipped: Windows 기동/네이티브·FFmpeg·exe 빌드/후보 생성 모두 미실행.
- 진단 아티팩트10,992B와 요청기록401B만 존재하며 배포 후보는 없다. 오류 로그는
  `/tmp/blackbox-verify-39762819006-failed.log`에 보존했다. 요청 아티팩트 다운로드는 Azure 배포URL에서
  Forbidden으로 거부돼 중단했으며 우회/재시도하지 않았다. GitHub 로그 조회는 성공했다.
- 최소 수정안은 windows.yml Linux apt 설치 목록에 테스트용 ffmpeg 패키지 추가다. 제품용 LGPL 최소
  Windows 번들과 구분하며 시험용 libx264를 제품에 동봉하지 않는다. CI 동결에 따라 해당 변경 승인 전
  workflow는 수정하지 않았다. 추가 Actions는 최초1회 승인 범위 밖이라 실행하지 않았다.
  태그/게시/배포도 없으며 원격 main은 위 SHA 유지, v0.11.0 태그는 미사용이다.


### 공동 후보 0.11.0 로컬 준비 — 2026-10-22

- 사용자가 공개 main 소스 푸시를 명시 승인했다. 푸시 직전 원격 main은 기준 `86efafc4`와 같고,
  API는 저장소 `public`을 반환했다. 공개 설정은 변경하지 않았다. 비용 조회 API는 권한 부족403으로
  현재 예산을 확인하지 못했으며 재시도/우회하지 않았다. 과거 사용량을 현재 잔액으로 사용하지 않는다.
- 릴리스 노트 맨 위와 `packaging/release_checks.json`을 `0.11.0`으로 준비했다.
  블랙박스13모듈, FPS/최적화5모듈, 설정2모듈, 빌드1모듈의 명시 목록이다. 전체회귀 필수화나
  workflow 변경은 없다. 버전 고정은 기존 `build_windows.py --version` 경로를 사용한다.
- 개발: `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m scripts.run_release_checks --version 0.11.0`
  **304건/20.27초** 통과. 결과 `/tmp/blackbox-fps-release-0.11.0-results.xml`.
  `uv run python -m pytest tests/test_release_checks.py tests/test_release_candidate.py tests/test_windows_ci.py -q --tb=short`
  **228건/8.59초** 통과. 이전 버전의 settings_export 필수 기대를 이번 변경21모듈의 정확집합으로 갱신했다.
  독립 QA는 관련251건 통과/과거 기대1건 실패를 확인했고, Windows 경로 구분자 문제도 발견했다.
  기대값 및 `as_posix()` 수정 후 최종 해당 검사13건/0.50초 재통과. 노트/버전/21모듈 범위 정합성 확인 완료.
  로컬 candidate preflight도 통과했지만 이는 원격 후보 SHA 확정이나 Windows 실행이 아니다.
- 원격 반영 직전 `v0.11.0` 미사용 여부를 다시 확인해야 한다. 노트/검사목록을 포함한 최종커밋의
  SHA로 검증해야 하며 현재는 미커밋이다. Windows native/exe/WGC/WASAPI/하드웨어 실측은 미실행이다.
  푸시/Actions/태그/게시/소스 Library 업로드는 하지 않았다.


### FPS 구간 요약·수집 모드 개발 — 2026-10-22

- 기준 커밋 `86efafc4adacf4a5c3fc991881cadfa6fdc9fa57`의 로컬 미커밋 변경이다. 기존 블랙박스 변경은 보존했다.
  최신 범위/정의는 [FPS 구간 요약 명세](game-frame-recording-stage1-spec.md). 기존 PresentMon 제출 이벤트를
  재사용해 유한 메모리 집계와 요약 JSON 저장을 연결했다. 매 프레임 디스크 로그/새 수집기/자동 최적화는 없다.
- 평균=N/유효 간격 합, 1% low=느린 ceil(N/100)개 간격 평균의 역수(N≥100), 최대=완성된 고정1초 창
  이벤트 개수 최댓값이다. 표본·시간·꼬리 개수·변동계수·긴 간격·설정 요청과 journal 적용 확인을 함께 남긴다.
  CPU 제한으로 평균/최대가 낮아지며 일정해진 합성 사례는 개선이 아닌 성능/변동 절충으로 표시한다.
- PID/생성 식별자·swapchain·비활성·누락/역순·측정 재시작·최적화 전환에서 구간을 분리한다.
  오류/자료 부족은 안정 상태로 표시하지 않는다. 수집 중 요약 쓰기는 유한 worker 큐, 고유 파일 원자적 완료,
  결과 인수 후 종료로 연결했다. 저장 실패는 자동수집을 멈추고 메모리 요약과 기존 파일을 보존한다.
- 기존 stat_bars/boss/tuarim 수집모드의 저장→폴더→체크박스→경로 패턴을 재사용했다.
  FPS 아래 `요약 저장 / 폴더 열기 / 수집 모드(구간 요약 자동 저장)` 추가 영역의 **렌더 배치 승인 완료**다(2026-10-22 사용자 “1: 이대로 진행”).
  합성 샘플 렌더: `/tmp/fps-summary-preview/fps-summary-tradeoff.png`, `fps-summary-insufficient.png`.
  Library ID: `libfile_049f3b15f4b48191ada061c92445a4b7`, `libfile_e564e8ffa43c81918e014bf5ae3824b5`.
  FPS 배치는 별도로 승인받았으며 동일 내용으로 재확인하지 않는다. 현재 변경은 보존한다.
  패키징 변경과 알파 초기값은 후속 승인됐다. 원격 푸시/Actions/배포 실행 승인은 별도이며 실행하지 않았다.
- 개발 최종 검사는 실제 controller 수집 시작/중지/표시 일시정지/JSON 연결, 완료 후 partial 정리 실패와
  결과 인수 전 종료 방지 회귀 포함 **125건/29.22초** 통과했다.
  명령: `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/test_frame_summary.py tests/test_optimization.py tests/test_optimization_ui.py tests/test_optimization_network.py tests/test_optimization_contract.py -q --tb=short --junitxml=/tmp/fps-summary-results.xml`.
- 구현에 참여하지 않은 독립 QA: 수학/파일 완료3건, 설정 경계/큐3건, 권한 해제/종료/표시 일시정지4건 통과.
  1% ceil 경계와 불완전1초 창, 32개 변동계수 참조 벡터도 확인했다. QA가 찾은 완료 후 partial 정리 실패의
  성공 경로 유실과 종료 직전 미인수 결과 문제는 수정 후 재검증했다. 최종 명세 대조에서 정의/수집 UI 일치를 확인했으며, 독립 관련 검사 **125건/41.38초**,
  별도 경계10건 재통과. 추가 확인된 결함은 없다.
- 합성 비용 검사 `UV_CACHE_DIR=/tmp/mabinogi-uv-cache uv run python scripts/probe_frame_summary.py`:
  CSV 50,000개 기존3.79µs/이벤트→집계6.50µs/이벤트, 200,000개 집계 tracemalloc 현재341,793B/
  최대2,017,249B, 최대16,000개 요약 평균8.85ms(10회). 화면 요약은 최대초당1회다.
  ETW/전체UI/Windows 실제 게임 비용을 측정한 결과가 아니다.
- 변경 파일: `optimization/frame_summary.py`, `frame_summary_store.py`, `frames.py`, `session.py`,
  `ui/optimization_controller.py`, `optimization_panel.py`, `tests/test_frame_summary.py`, `test_optimization_ui.py`,
  `scripts/probe_frame_summary.py`, `render_frame_summary_preview.py`, 기존 FPS 명세/상태/Windows 문서.
  tracked diff는 `git diff HEAD`, 새 파일까지 포함한 목록은 `git status --short`로 확인한다.
  구현 완료 시점 전체 로컬 diff는 `/tmp/mabinogi-combined-local.patch`이며 기준 SHA archive에 apply --check 통과.
  패치는 마지막 로컬 인계 시점에 갱신하며 외부 전송하지 않는다.
  기존 `/tmp/mabinogi-blackbox.patch`는 FPS 추가 전 체크포인트다. 두 패치 모두 외부 전송하지 않는다.
- 남은 검증: 실제 Windows PresentMon 이벤트/포커스 경계/장시간 수집·저장/CPU·메모리 비용,
  동일 게임 장면에서 평균·최대·1% low와 변동을 함께 확인한다. 합성 통과를 실게임 검증으로 대체하지 않는다.
  공동 릴리스의 블랙박스 번들·제품 설정 준비는 아래 최신 상태를 따른다.
  승인된 패키징만 수정했고 CI 게이트는 유지했다.  푸시/PR/Actions/태그/배포/실제 캡처/소스 업로드는 하지 않았다.

### 블랙박스 개발·독립 QA·최상위 탭 승인 — 2026-10-22

- **최신 인계 상태**: 빌드/패키징 수정과 알파 초기값 묶음 승인 완료. 원격 푸시/PR/Actions/태그/Release는
  실행하지 않았다. 기준 SHA `86efafc4adacf4a5c3fc991881cadfa6fdc9fa57`의 미커밋 변경이다.
- 승인 제품 설정 `packaging/blackbox-product.json`: 1080p60/기본10분/1처리+1대기 유지,
  영상12Mbps·AAC192kbps, 임시8GiB·여유4GiB·최근버퍼2GiB, 원시큐512MiB,
  입력 최대1920×1080, 오차50ms, Ctrl+Alt+F10, 커서 제외, 게임오디오 분리 실패 시 중단.
  입력 가로·세로를 각각 검사하며 초과 시 전체화면/해상도 변경/무음으로 몰래 대체하지 않는다.
- 기존 Actions → `packaging/build_windows.py` → `blackbox_bundle.prepare`가 자동 연결된다.
  공식 소스 해시 확인·최소 FFmpeg 공유 빌드 → CMake x64 Release DLL/codec host → 제품 설정/대응소스/고지
  → 버전/인코더/manifest 검사 → 기존 PyInstaller onefile 순서다. `.github`, pyproject/lock은 변경하지 않았다.
  사용자는 개발도구·수동 소스 패치 없이 기존 앱 업데이트를 받는 구조다. 빌드 기계에만 도구가 필요하다.
- BtbN LGPL3 후보는 제품에서 제외했다. 공식 FFmpeg n8.1.3 최소 공유 빌드(LGPL2.1+)로 줄였다.
  GPL/nonfree/version3/libx264/외부 코덱 SDK는 제외하고 하드웨어 `h264_mf`와 내장 AAC를 사용한다.
  FFmpeg 소스 SHA256 `09f990289327d3ebfedf4fc15cae3f884a65dab7a5aac7bbb5b01ff83900efd9`.
  Windows LLVM-MinGW 20261020 SHA256 `fd5462b7f5d93b2ff981fcd3f9c7e427e47f3203c64ea91c27bcc444eebd74cd`.
  정확한 MinGW 소스·컴파일러 출처/해시와 실행 명령은 [Windows 검증](windows-validation.md)에 기록했다.
- Linux→Windows FFmpeg PE 교차 빌드 성공: runtime8파일/6,300,160B. PE import는 번들 FFmpeg DLL6개와
  Windows/UCRT이며 GPU/MFT 런타임 지원을 검증한 것은 아니다. `/tmp/blackbox-minimal-build/review-bundle`에
  실제 바이너리/소스/고지 준비. 대응소스 zip SHA256 `66f63a3947fd4823e74f32188c8c6bc242f65c999c5fcbb22d803edc4ec6ef04`.
  FFmpeg·MinGW 대응소스/정확한 recipe/config/LLVM 고지를 포함하고 앱은 사용자 데이터의
  `third_party/ffmpeg-<source hash>`에 일반 파일로 제공한다. 기존 수정 파일은 덮어쓰지 않는다.
  LGPL/LLVM/MinGW 고지와 소스 제공 조건은 확인했지만 법적 적합성·영상 특허 권리 보증은 아니다.
- 긴 저장은 입력별 거대 명령행 대신 제한된 concat manifest/순차 디코딩을 사용한다. 중단 시간을 제외하고
  선택 구간만 재인코딩한다. 명시적 출력60fps로 저비트레이트 합성 영상 첫 프레임 회색 손실을 수정했다.
  독립 QA 실제 합성 인코딩: 3,001구간→600초/36,000프레임,24.592초; 완전 디코딩·오디오·5초 중단 제외,
  한글/작은따옴표 경로·취소0.112초 확인. 실제 게임/Windows 하드웨어 인코딩 측정이 아니다.
- 개발 최종 회귀 **203건/19.90초** 통과. 명령: `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/test_blackbox*.py tests/test_startup_build.py tests/test_windows_ci.py -q --tb=short --junitxml=/tmp/blackbox-packaging-source-results.xml`.
  최종 독립 QA 패키징·기동·Windows CI 모형 **48건/1.44초** 통과. 명세/제품값/빌드 경로 정합성을 확인했고,
  QA가 지적한 Windows 문서의 과거 미승인 표기를 이전 단계 기록으로 명확히 수정했다.
  앞선 독립 QA 관련23건/4.29초 통과와 별도 입력크기 경계,
  KnownFolder 성공/실패/메모리 해제, 소스 고지 기존 파일 보호/부분 실패 정리/해시 검증을 완료했다.
  독립 QA에서 확인된 제품 결함은 수정·재검증했고 현재 추가 확인된 결함은 없다.
- 변경 핵심: `packaging/{build_windows.py,blackbox_bundle.py,ffmpeg_source.py,ffmpeg_minimal.sh,blackbox-product.json}`,
  `native/blackbox/CMakeLists.txt`, 제품 `blackbox_bundle.py`, `blackbox_codec.py`, `blackbox_producer.py`,
  `system/known_folders.py`, config/controller, probe·관련 테스트·명세/실행 문서다.
- 남은 환경 검증: Windows SDK/MSVC 네이티브 빌드와 PyInstaller exe, WGC 합성창, WASAPI 프로세스 분리,
  Media Foundation 하드웨어 지원/A-V 동기/실게임1080p60/장시간 부하/전역 단축키/업데이트 설치.
  이 환경은 Linux로 해당 실행을 하지 않았다. 수치 승인과 소스 작성/PE 교차 빌드는 실제 Windows 성공이 아니다.
  앱 비정상 종료 후 manifest 자동 복원은 미구현이며 현재 앱 세션의 실패 재시도/명시적 폐기와 구분한다.
  다음은 원격 반영·Windows 후보 검증 실행의 별도 승인 및 기존 절차에 따른 후보 SHA/버전 확정이다.
  실제 게시 실행은 사용자 최종 배포 절차를 유지한다.

#### 이전 단계 기록 — 아래 미구현/승인 대기 표기는 당시 상태이며 최신 상태는 위 항목을 따른다

- **Windows 검증 도구 보완·패키징 읽기 확인(최신)**: `test_support/blackbox_codec.py`의 명시적
  `BLACKBOX_CODEC_HOST`를 producer/audio 합성 fixture에 연결했다. Windows에서 누락/상대/없는 경로는
  실패하며 skip/자동 다운로드하지 않는다. `scripts/probe_blackbox_window.py`는 자기 Qt 합성창 HWND+
  현재 PID만 사용해 WGC→무음MP4→완전디코딩/원자적완료를 검사한다. 임의창/게임창 입력과 오디오는 없다.
  실제 실행은 안 했고, Linux에서는 모형 프레임과 실제 FFmpeg만 사용했다.
- 개발 관련12건/2.90초 통과(`/tmp/blackbox-windows-tools-results.xml`):
  `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/test_blackbox_window_probe.py tests/test_blackbox_producer.py tests/test_blackbox_audio_codec.py -q --tb=short --junitxml=/tmp/blackbox-windows-tools-results.xml`.
  독립 QA6건/0.764초+관련회귀8건 통과. QA가 찾은 초기화실패 창/진단 정리 누락 수정 후
  identity/worker.start 실패 독립2건/0.036초 통과(`/tmp/blackbox_probe_setup_qa.py`).
  `--help`/import는 장치를 열지 않음을 확인. Windows C++ 빌드/WGC 실행은 여전히 미검증이다.
- 복구 화면 구현은 승인됐다. 사용자가 먼저 사용해보고 판단하는 승인으로 피드백에 따라 조정한다.
  실제 자료 삭제 승인은 아니며 작업별 폐기 확인을 유지한다. 사용자는 별도 소스/exe 전달 대신
  기존 앱 업데이트 후 직접 Windows 확인을 기대한다. 소스 Library 업로드는 승인되지 않았고 하지 않았다.
- **릴리스 준비는 미완료**: `packaging/build_windows.py`/`.github/workflows/windows.yml`은 새 DLL/host/
  FFmpeg를 빌드·포함하지 않는다. 이 파일들과 pyproject/lock은 `git diff --exit-code HEAD -- packaging .github pyproject.toml uv.lock`로 변경없음을 확인했다.
  최소 변경은 빌드 쪽 네이티브 생성/의존성 묶음, 승인된 FFmpeg 정확한 바이너리·라이선스·대응 소스,
  앱의 번들 경로/제품 설정 연결, frozen exe 기동 검증이다. 사용자가 Python/MSVC/FFmpeg를 따로
  설치할 필요 없는 기존 onefile 업데이트 방식으로 준비할 수 있으나 아직 구현/승인하지 않았다.
  동봉 권장 검토안은 GPL/nonfree/libx264 제외 LGPL 하드웨어 인코더 빌드의 버전/해시 고정이며,
  실제 빌드 라이선스·GPU 지원·고지/소스 제공 확인이 선행된다. 정책/게이트를 임의 변경하지 않는다.
  정확한 개발자 Windows 명령·필수 도구·최소 패키징 변경은 `docs/windows-validation.md`에 기록했다.
  원격/Actions/배포/실제녹화/소스전송 없음.

- **최신 검증/인계 체크포인트**: 개발 관련 `tests/test_blackbox*.py` + `test_config_atomic.py` +
  `test_startup_smoke.py` **154건/15.95초** 통과(`/tmp/blackbox-results.xml`).
  실행: `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/test_blackbox*.py tests/test_config_atomic.py tests/test_startup_smoke.py -q --tb=short --junitxml=/tmp/blackbox-results.xml`. 저장 예약 후 권한 해제,
  원본 보호·취소·정리, 합성 PCM+실제 FFmpeg 파일 생성/완전 디코딩, Qt 설정·업데이트 보호를 포함한다.
  producer 통합 fixture는 합성 프레임 전달 전에 저장을 누르는 경쟁이 있어 완료 조건 대기를 추가했다.
  기존 끝점·성공 assertion은 유지했다. 이후 영상/오디오/service 10건/2.33초 통과.
- **독립 QA**: 정상 중단 시 PCM이 마지막 영상 프레임 전체를 덮지 못하면 오류가 재개를 막는 결함을
  수정했다. `/tmp/blackbox_audio_transition_real_qa.py`에서 합성 PCM/영상+실제 코덱으로 완결0.1초만
  보존/정상 transition/예산0 정리를 확인했다. 최신 연결 독립5건/0.031초는 업데이트 교체 전 저장대기,
  업데이트 실패 복구, preferences 보존, 접근해제 후 예약취소/늦은flush, 실제 worker 취소와
  partial 보존/명시폐기를 확인했다(`/tmp/blackbox_final_connections_qa.py`). 관련 독립 회귀20건/4.87초도 통과했다. 앱 코드 수정 없는 QA다.
- 마지막 UI 결과 보완: 열린 복구 화면의 ticket/session 선택을 유지하며 worker 결과를 갱신한다.
  독립 QA가 찾은 예약취소 후 진행문구 잔존을 취소 알림으로 수정했다.
  `/tmp/blackbox_ui_results_qa.py` 독립3건/0.262초 통과. 최종 개발 관련 service/UI8건/1.00초,
  직전 access/lifecycle/UI13건/2.88초 통과. `git diff --check` 통과.
- 앱 연결 추가: 보관 시간·저장 폴더 기억, Qt 결과 전달·중단/재시도/명시폐기·이전 게임 버퍼 저장,
  업데이트 재시작 전 저장 보호와 실패 후 runtime 재생성. OS 전용 구현은 기존 규칙대로 `system/`에 둔다.
  제작자 접근을 확대하거나 외부 캡처를 실행하지 않았다.
- 새 복구 UI는 샘플이며 별도 배치 피드백 대기다. 렌더 `/tmp/blackbox-recovery-preview/blackbox-recovery-preview.png`,
  Library `libfile_f1c4ec9746f081919cf3e61bd4acd7e4` 버전0. 기존 승인된 주 탭 배치 재확인은 불필요하다.
- **정확한 미완료**: Windows DLL/codec host는 소스만 작성했고 SDK가 없어 빌드도 하지 않았다.
  WGC/WASAPI/하드웨어 인코더/전역 단축키/실게임1080p60/오디오 분리·동기화/부하·장시간 실행은 미검증.
  Media Foundation 인코더와 앱 비정상 종료 manifest 복원은 미구현이다. 제품은 완전한 명시적
  validationProfile과 외부 바이너리 없이는 녹화를 열지 않는다. 수치·배포 의존성을 몰래 확정하지 않았다.
  다음 로컬 Windows 빌드/합성 검사/승인 후 대상 한정 검증 순서는 `docs/windows-validation.md`에 기록했다.

- **최신 구현 체크포인트(후속 QA 진행 중)**: `native/blackbox/{capture.cpp,audio.cpp,codec_host.cpp,CMakeLists.txt}`,
  `blackbox_native.py`, `blackbox_codec.py`, `blackbox_producer.py`, `blackbox_audio.py`, `blackbox_service.py`,
  `ui/blackbox_events.py`, `ui/blackbox_recovery.py`를 추가했다. 아래 이전 단계의 "네이티브 미구현" 기록은
  이 후속 소스 작성으로 대체되며 **Windows 빌드/실행은 여전히 미검증**이다. 바이너리/의존성 동봉·CI 변경 없음.
  WGC는 HWND/PID/프로세스 생성 시각과 foreground epoch를 검증한다. 오디오는 해당 프로세스 트리 PCM만 받는다.
  전체 화면/마이크/전체 시스템 소리 fallback은 없다. FFmpeg는 명시적 절대 경로 바이너리만 실행한다.
  네이티브 worker→제한된 raw/PCM 큐→디스크 구간→1처리/1대기 큐→Qt 결과/복구·종료를 연결했다.
  명시적 validationProfile이 완전할 때만 runtime을 생성하며 제품 용량/품질/키 기본값은 넣지 않았다.
- 최신 부분 검증: 기존 관련 **136건/11.25초**, 예약 변경 후 관련 **128건/3.78초**,
  audio/service **8건/1.07초**, fake native+실제codec 영상/PCM 통합 **2건/2.11초** 통과.
  독립 QA의 서비스 준비상태/Alt+Tab재개/접수후접근해제/정리재시도 4결함은 수정 후 별도7건 통과.
  제출 실패+정리 실패의 이중예외도 수정 후 독립 재검증을 통과했다. 아직 이번 변경 전체 QA 완료를 뜻하지 않는다.
- 오디오 합성 경계: B-frame/empty_moov가 영상 초기 PTS를 이동시키는 문제를 -bf0/delay_moov로 수정했다.
  작은 합성 0.6초 요청은 영상0.6초/오디오0.621333초였고 명시적 테스트 오차50ms 안에서 검증했다.
  이는 AAC 프레임 꼬리·허용 오차를 Windows에서 확인해야 한다는 근거이며 제품 오차 수치를 승인한 것이 아니다.
  손상 입력은 -xerror/-err_detect explode로 거부한다. 실제 게임 A/V 동기화 검증은 아니다.


- 기준 `86efafc4adacf4a5c3fc991881cadfa6fdc9fa57`: 시작 시 원격 main과 일치하는 깨끗한 `work`
  체크아웃이었다. 로컬 수정만 수행했다. 커밋·푸시·PR·태그·Release·Actions·CI 변경은 없다.
- `AGENTS.md`, `CLAUDE.md`, 블랙박스 명세와 연결된 기획서·프레임 계측 0단계·Windows 지침을
  확인했다. 체크아웃에 `.agents/skills`는 없다. 기존 inventory 2,624건에서 블랙박스 검사/구현은 없었다.
  초기 uv 기본 캐시 읽기 전용 오류는 `/tmp/mabinogi-uv-cache`로 해결했다.
- `blackbox.py`: 기본 10분 실제 녹화 길이, 중단 시간 제외, 저장 시점 불변 계획, 원본 pin,
  시간/바이트/개수 한도, 세션 혼합 거부. `blackbox_session.py`: 제작자 요청별 재확인,
  사용 해제/게임 종료 후 저장 기회, 접근 회수 후 신규 요청 차단과 기존 pin 보호, 늦은 캡처 결과 거부,
  준비/녹화/오류 구분, 저장 중 종료 정리 거부. `config.py`의 체크 저장은 기존 원자적 경로를 사용한다.
- `blackbox_export.py`: 수락된 계획 하나를 worker에서 실행하는 코덱 독립 경계다. 주입된 인코더가
  쓰기 전용 sink에 출력하고 상한을 넘기면 실패한다. 목적지 폴더의 독립 `.partial`에 기록·fsync·
  주입 검증 후 `os.link`로 create-only 확정한다. 기존/경쟁 클립은 덮어쓰지 않고, 실패 partial과
  원본 pin은 보존한다. 검증된 파일만 소유 inode/해시 재확인 후 명시적으로 확정 재시도할 수 있다.
  소유 partial의 명시적 폐기와 완료 뒤 partial 정리 실패도 별도 결과로 알린다. 같은 job의 중복/동시 실행은 거부한다.
- 제한: hard link 미지원 파일시스템은 안전하게 실패하며 복사/덮어쓰기로 폴백하지 않는다.
  일반 코덱 콜백의 시간 제한·취소·실제 디코딩 검증은 어댑터 계약이다. 본 모듈이 임의 콜백을 강제 종료하지 않는다.
  `blackbox_queue.py`/`blackbox_budget.py`에 유한 worker/결과 슬롯·협력적 취소·합산 임시 예산과
  볼륨 여유 공간 검사를 추가했다. 원본은 저장소 어댑터가 명시적으로 등록해야 하며 자동 디스크 전체 탐색은 없다.
  실패/정리 대기 파일은 예산과 결과 슬롯에 남는다. 완료 클립은 임시 예산에서 제외하되 실제 여유 공간에 반영된다.
  큐 정상 종료는 신규 요청을 막고 수락된 작업·결과 인수·복구 결정을 기다린다. 접근 회수도 기존 복구를 막지 않는다.
  취소는 협력적이며 임의 Python 콜백을 강제 중단하지 않는다. 디스크 저장소와 제어 연결은 아래 최신 항목을 따른다. 재시작 복구는 미구현이다.
  원본 pin 해제는 worker가 아닌 제어 스레드에서 결과를 보고 결정한다. 전원 손실 시 파일 내구성/완전 복구는 보증하지 않는다.
- 후속 사용자 `1` 회신으로 디스크 임시 폴더·1개 처리+1개 대기·실패 보존/재시도/명시적 폐기·
  필요한 경계 재인코딩을 승인했다. 명세9절에 반영했다. 용량/품질 숫자·최종 코덱·Windows 기술 채택은 미승인이다.
- `blackbox_spool.py`: 앱 실행마다 새 전용 디스크 폴더를 만들고 제한된 sink로 완결 구간을 기록/fsync한다.
  원본·실패 쓰기를 합산 예산에 등록한다. inode가 일치하는 소유 파일만 읽기/폐기하고 다른 파일·교체된 폴더는 보호한다.
  실패 삭제는 예산/자료를 유지한다. 실패 쓰기 자료는 sources에 남으며 임의 자동 삭제/재시작 혼합은 없다.
- `blackbox_runtime.py`: session의 고정 plan/pin → 1worker/2slot 큐 → 성공 인수/실패 복구 → 원본 retire를 연결했다.
  기존 요청은 접근 해제/종료 대기 중에도 복구할 수 있다. 미검증 인코딩 실패는 같은 plan으로 재인코딩하며
  새 출력 예약을 먼저 확보하고 이전 실패 partial도 명시적 정리까지 보존한다. 정리 실패 원본은 재시도 목록에 남는다.
  독립 QA가 완료 인수 후 원본 삭제 실패로 완료 결과를 잃는 결함을 발견했다. 개발 수정으로 성공 결과와
  cleanup_error를 함께 반환하고 retry_cleanup으로 정리를 다시 시도한다.
  후속 독립 QA에서 다른 ticket에 대기 중인 동일 ExportJob을 retry_encode에 중복 접수할 수 있음을 재현했다.
  개발자가 예산 예약 전 기존 모든 entry.job 동일성 검사로 거부하도록 수정했고 독립 재현으로 재확인했다.
  DiskSpool write는 UI에서 실행하지 않는 어댑터 경계이며 실제 Windows 캡처/인코더 worker는 아직 없다.
- 제품 연결 범위: `ui/blackbox_controller.py`를 main_window에 연결했다. 사용자 후속 결정에 따라
  **제작자에게만 최상위 블랙박스 탭**을 생성하고, 접근 회수 시 제거/파괴한다. 이전 편의기능 내부 탭 안은 대체됐다.
  controller의 직접 명령과 session의 실행 경계 모두 권한을 검사한다. UI 제거는 별도로 소유한 저장 pin을 건드리지 않는다.
  현재 제품에는 Windows 캡처·인코더·단축키와 runtime의 앱 수명주기 연결이 없어 5개 UI 조작은 비활성이다.
  새 접근 권한을 발급하거나 일반 공개하지 않았다. 앱 시작으로 녹화하지 않는다.
- 최신 개발 회귀: 모델50+세션25+내보내기22+큐20+runtime/디스크7+접근7+기존 설정 원자성5+기존 최소 기동2 = **138 passed / 16.54초**.
  Linux 명령:
  `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/test_blackbox.py tests/test_blackbox_session.py tests/test_blackbox_export.py tests/test_blackbox_queue.py tests/test_blackbox_runtime.py tests/test_blackbox_access.py tests/test_config_atomic.py tests/test_startup_smoke.py -q --tb=short --junitxml=/tmp/blackbox-results.xml`.
  전체 회귀·Windows 최소 기동·exe는 미실행이다. 최초 새 검사 1건은 공통 fixture의 app 디렉터리를
  신규 산출물로 잘못 판정해 실패했고, 실행 전후 파일 집합이 동일한지 검사하도록 고쳤다.
- 독립 QA는 구현에 참여하지 않은 `blackbox_independent_qa`가 원 명세/현재 소스와 직접 재현으로 수행했다.
  모델 별도5건/0.279초(무작위 전환20,000회, 저장 중999회 추가), 모델 회귀50건/1.76초 통과.
  세션의 이전 worker 오류가 새 상태를 덮는 결함은 개발자가 permit 식별을 추가해 수정했다.
  수정 후 별도7건/0.003초와 백엔드 회귀75건/1.94초 통과.
- 내보내기 독립 QA는 바이트 수 대신 원소 수/재정의된 len을 믿는 상한 우회와, 교체된 partial을
  여전히 validated로 반환하는 결함을 발견했다. 개발 수정으로 정확한 bytes 타입만 쓰기 전에 허용하고,
  재검증 시작 시 검증 상태를 무효화했다. 수정 후 **독립6건/0.004초, 기존20건/0.75초** 통과.
  이후 큐 추가에 따른 최신 exporter 검증은 아래 결과를 따른다.
- 큐 독립 QA가 fsync 도중 취소 뒤 validator가 실행되는 결함과 외부 삭제 partial 때문에 종료가 막히는 결함을 재현했다.
  개발자가 validate 직전 취소 검사와 동일 부모 inode에서 파일 부재를 확인한 명시적 정리 경로를 추가했다.
  부모 부재/교체는 실패로 유지한다. ExportJob의 plan/output/한도는 공개 속성 재할당을 막아 예약 후 변경을 차단한다.
  수정 후 독립 `/tmp/blackbox_queue_independent_qa.py` **6건/0.138초**, 큐·내보내기 회귀 **41건/1.15초** 통과.
  3worker/4slot, 성공·실패 240작업 후 슬롯/예산 회수와 스레드 종료도 확인했다.
  증거 `/tmp/blackbox-queue-independent-results.xml`; exporter SHA256
  `67a26daf11100ec199bdb4cb5d8eec3d6d6071352d02d9c653c1d52766930eff`.
  자원 한도는 필수 인자이며 테스트 fixture 수치를 제품 기본값으로 채택하지 않았다.
- 접근 독립 QA: **7건/2.23초** 및 별도 200회 권한 전환에서 중복 탭 없음·설정 탭 직전 배치·
  제거 page 파괴·일반 사용자 명령 차단·기존 저장 보호·늦은 허가 거부·종료 중 차단을 확인했다.
  검증한 백엔드/접근 범위에서 남은 차단 결함 없음이며 전체 녹화 기능 QA 통과가 아니다.
  독립 재현은 `/tmp/blackbox_independent_qa.py`, `blackbox_session_independent_qa.py`,
  `blackbox_export_independent_qa.py`, `blackbox_access_independent_qa.py`를
  `UV_CACHE_DIR=/tmp/mabinogi-uv-cache uv run python /tmp/<파일>`로 실행한다.
  증거 XML: `/tmp/blackbox-independent-session-results.xml`, `/tmp/blackbox-export-independent-results.xml`,
  `/tmp/blackbox-access-independent-results.xml`.
- `scripts/probe_blackbox_export.py`는 외부 소스를 받지 않고 새 출력 폴더에 고정 합성 영상만 만든다.
  설치된 FFmpeg7.1.5 소프트웨어 인코딩은 실험 전용이며 제품 fallback/의존성으로 채택하지 않았다.
  `UV_CACHE_DIR=/tmp/mabinogi-uv-cache uv run python -m scripts.probe_blackbox_export /tmp/<새폴더>`.
  개발 `/tmp/blackbox-export-probe-v1`과 독립 `/tmp/blackbox-export-probe-independent` 모두 exit0.
  실제 ExportJob을 거쳐 320×180/60FPS 무음 MP4 **3.5초/210프레임** 생성·완전 디코딩, 중복 경로 거부,
  실패 partial 보존을 확인했다. 독립 색 검사에서 빨강90+파랑120프레임으로 중단5초의 삽입이 없었다.
  concat/inpoint+copy 비교 결과는 **4초/240프레임**으로 정확한 자르기를 대신하지 못했다.
  각 폴더 `results.json`에 명령·ffprobe 결과가 있다. 제품 경계 오차/파일 형식의 승인이나 1080p 성능 검증이 아니다.
  최신 probe는 실제 ExportQueue와 DiskBudget을 경유한다. 개발 `/tmp/blackbox-export-queue-probe-v1`,
  독립 `/tmp/blackbox-queue-probe-independent` 모두 exit0이며 같은 3.5초/210프레임·색 순서와
  큐 종료/예산 회수를 확인했다. 합성 원본/결과는 증거로 남기며 회계 항목 회수를 파일 삭제로 표현하지 않는다.
  최신 `/tmp/blackbox-runtime-probe-v1`은 DiskSpool→session→Runtime→실제 MP4 저장→정상종료를 추가해 exit0.
  이 전용 spool 원본/폴더는 실제 정리됐고 fixture 원본과 성공 클립은 남아 있다. 같은 3.5초/210프레임 출력이다.
  독립 `/tmp/blackbox-runtime-probe-independent`도 exit0. 별도 디코딩으로 빨강90+파랑120과 임시폴더 정리·
  성공 클립 보존을 확인했다. 독립 runtime 재현 `/tmp/blackbox_runtime_independent_qa.py` 5건(0.013초),
  중복 retry 재현 `/tmp/blackbox_retry_identity_qa.py` 통과. runtime/queue/export 독립 회귀 **49건/4.40초** 통과
  (`/tmp/blackbox-runtime-independent-results.xml`). 현재 해당 검사 범위의 미해결 차단 결함 없음.
  실제 Windows/하드웨어/음성 검사는 아니다.
- UI 렌더는 `scripts/render_blackbox_preview.py`로 실제 제작자 최상위 탭에 샘플 상태만 넣는다.
  `UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_blackbox_preview /tmp/blackbox-top-preview`.
  최초 투아림 타이머 캡처 시도는 경계에서 차단됐고 소유 QTimer 중단으로 수정/독립 재검증했다.
  최상위 전환 후 샘플 로그인 name 누락도 수정했다. 최신 개발/독립 렌더 모두 exit0이며,
  독립 경로 `/tmp/blackbox-top-independent-fixed`의 이미지에서 최상위 탭과 예시/녹화 미동작 표시를 확인했다.
  실제 개인 화면/오디오 캡처는 없었다.
- Library 기존 이미지의 **버전1**로 교체했다. 보관 중:
  `libfile_35fd1e6dd8e881918614f744e10779d1` / `file_00000000f81082309a3ef1452bce86ce`.
  일시정지: `libfile_97d2901f538481919f993479efe04d3b` / `file_0000000049908230ae5a5fe4ccbaebaa`.
  부모가 전달한 렌더를 보고 사용자가 `이대로진행`으로 최상위 배치·문구를 승인했다. 재확인하지 않는다.
  탭 접근 연결은 완료했으며 실제 캡처/저장 조작 활성화는 정책과 Windows 어댑터 검증에 의존한다.
- 실제 캡처/인코딩 다음 검토안은 등록 HWND의 WGC + 하드웨어 Media Foundation과,
  WGC + 검증한 FFmpeg 하드웨어 인코더/내보내기를 비교하는 것이다. 전자는 네이티브 연동,
  후자는 바이너리 구성/재배포 조건/작업 프로세스 관리 검증이 필요하다. 어느 것도 제품 채택으로 확정하지 않았다.
  근거: [WGC CreateForWindow](https://learn.microsoft.com/en-us/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow)는 단일 HWND·Windows10 1903 이상,
  [MFTEnumEx](https://learn.microsoft.com/en-us/windows/win32/api/mfapi/nf-mfapi-mftenumex)는 하드웨어/기본 소프트웨어 필터를 구분한다.
  [프로세스 오디오 샘플](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)은 지정 프로세스 트리와 build20348 이상 조건,
  [FFmpeg 라이선스](https://ffmpeg.org/legal.html)는 빌드별 LGPL/GPL 조건을 설명한다.
- 다음 확정 필요: 용량/여유 공간 한도, 보관 범위, 파일 형식/품질/폴더명, 허용 구간 오차,
  커서/오버레이 포함, 무음 안내, 단축키 기본 키는 명세9절대로 기술 검토/확인 대상이다.
  네 가지 저장 방식은 후속 승인됐으므로 다시 묻지 않는다. 용량/품질의 정확한 값은 Windows 실측 근거와 함께
  후속 제시한다. 임의 제품 기본값을 넣지 않았다. 다음 실제 앱 연결은 이 수치와 Windows 어댑터 검증에 의존한다.
- 이전 보고의 정정: Windows 환경 부재는 실행 검증의 제약이지 네이티브 코드 작성 자체의 불가능 사유가 아니다.
  WGC 게임창 캡처, Media Foundation/제품 FFmpeg 인코더, 프로세스 오디오, 게임 전역 단축키,
  foreground/잠금/절전 네이티브 이벤트 어댑터는 **미구현**이다. 코드가 있는데 Windows에서만 미검증인 상태가 아니다.
  기존 dxcam/mss는 화면 영역 기능, PrintWindow는 별도 창 스냅샷 유틸리티이며 블랙박스 연결이 없다.
  FFmpeg probe는 고정된 작은 무음 합성 영상 전용이고 제품 인코더/취소 스트리밍 어댑터가 아니다.
- Windows 없이 가능한 종료 연결을 추가했다. `blackbox_lifecycle.py`는 생산자 request_stop/is_stopped 계약과
  permit 폐기→생산자 완전 정지 확인→저장 결과/복구 확인→원본/폴더 정리를 연결한다.
  stop 실패여도 나머지 생산자 stop을 요청하고, 실패/지연은 종료 완료로 위장하지 않는다.
  main_window의 실제 종료 경로가 controller.prepare_close를 확인하며 트레이 숨김에서는 중지하지 않는다.
  기본 제품 controller에는 lifecycle이 아직 주입되지 않는다. 테스트용 구현만 있으며 네이티브 worker,
  시작/재개/flush 계약의 구체 구현, Qt 결과 전달·성공 인수/실패 복구 UI·종료 재시도 동선은 남은 개발이다.
  이 항목들은 실측 없이는 코드를 쓸 수 없는 것이 아니다. 용량·품질 값은 외부 필수 입력으로 구현 가능하다.
  개발 lifecycle/access/startup 검사 **12건/4.86초** 통과. 독립 lifecycle/access **10건/3.09초**와
  `/tmp/blackbox_lifecycle_independent_qa.py` **3건/1.962초** 통과. 실제 MainWindow의 트레이/종료대기/
  비제작자 탭 제거 뒤 보호와 runtime+spool 종료 순서를 확인했다. 네이티브 API 실행 검증이 아니다.
  독립 명령: `PYTHONPATH=/workspace/mabinogi_addon UV_CACHE_DIR=/tmp/mabinogi-uv-cache QT_QPA_PLATFORM=offscreen uv run python /tmp/blackbox_lifecycle_independent_qa.py`.
- Windows 요청 전 남은 개발: WGC/인코더 연동의 ABI·Python/네이티브 패키징 검토 및 최소 어댑터 작성,
  생산자 callback/flush/stop 구현과 fake 검증, 앱 runtime 생성·결과 전달·복구 UI 연결.
  기술 후보를 최종 채택하거나 배포 의존성을 추가하지 않은 상태이므로 당장 사용자가 실행할 캡처 명령은 없다.
  Windows에서만 확정 가능한 것은 API/드라이버 호환, 실제 창 분리·성능·소리 동기화·키 수신이다.
- 다음 Windows 최소 과제(아직 실행 요청 아님): 먼저 합성 전용 테스트 창으로 native 창 캡처→인코딩→
  정지/저장 검증, 이후 별도 허용 범위에서 마비노기 HWND 하나만 영상 캡처하며 Alt+Tab/최소화 때 중단·
  복귀·요청 끝점·저장 중 종료를 확인한다. 1차는 무음이고 시스템 전체 소리/마이크는 수집하지 않는다.
  게임 소리는 프로세스별 오디오 어댑터 구현과 별도 검증 범위를 정한 뒤 진행한다.
  준비 정보는 Windows 빌드·GPU/드라이버·테스트 폴더 여유 공간, 기존 제작자 계정, 로컬 개발 실행 환경이다.
  계정 비밀값·개인 화면 제공은 필요 없다. 아직 사용자가 장치 연결/녹화를 시작할 단계가 아니다.
- Windows 미검증: 게임 단축키·IME/권한/충돌, 등록 게임만 캡처·비활성/최소화/잠금/절전·게임 재실행,
  1080p60/장시간 부하/하드웨어 인코더, 게임 소리·A/V 동기화, 동영상 폴더, NTFS/기타 볼륨의 원자적 확정,
  디스크 부족/분리/권한/강제 종료 복구와 실파일 재생. Linux의 작은 무음 합성 검증으로 대체하지 않는다.
  현재 사용자 PC에서 실행할 조작은 없으며 전체 개발 목표 완료 상태도 아니다.
- 변경 파일은 `git status --short`로 확인한다. 새 파일을 포함한 전체 diff는 `/tmp/mabinogi-blackbox.patch`.
  tracked diff와 각 새 파일의 `git diff --no-index /dev/null <파일>`을 합쳤다(no-index exit1은 정상 차이 반환).
  주요 파일: `blackbox.py`, `blackbox_session.py`, `blackbox_export.py`, `blackbox_budget.py`, `blackbox_queue.py`, `blackbox_spool.py`, `blackbox_runtime.py`, `blackbox_lifecycle.py`, `config.py`,
  `ui/blackbox_tab.py`, `ui/blackbox_controller.py`, `ui/main_window.py`, `tests/test_blackbox*.py`,
  두 렌더/합성 검증 scripts, `docs/game-blackbox-spec.md`, 이 문서. 제품 기능 미완성이므로 배포 버전/검사 목록은 정하지 않았다.
