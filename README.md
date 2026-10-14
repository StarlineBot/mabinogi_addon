# mabinogi_addon

마비노기 상태목록창과 보스 디버프 줄을 화면 캡처로 읽어서, 등록한 버프·디버프를 오버레이로 보여주는 Windows 프로그램.

- 버프: 켜진 버프를 지정 순서대로 가로 나열, 남은 시간 표시, 연장 타이밍 알림
- 디버프: 보스에게 아직 걸리지 않은 디버프만 표시

화면을 읽기만 하며, 입력 자동화나 메모리 읽기는 하지 않습니다.

## 개발

```bash
uv sync
uv run pytest
uv run mabinogi-addon
```

기획과 설계: [docs/기획서.md](docs/기획서.md)

## 잊어버리기 쉬운 운영 규칙 (메인테이너용)

### 릴리즈 / 배포
- **배포는 태그로 트리거된다.** `vX.Y.Z` 태그를 push하면 `release.yml`이 exe를 빌드하고
  릴리즈 저장소의 `version.json`을 갱신 → 사용자 앱이 자동으로 새 버전을 감지한다.
- **태그 달기 전에 반드시 `git fetch origin` 먼저.** 로컬 `origin/main`이 오래되면
  엉뚱한(과거) 커밋에 태그가 찍힌다(예전에 한 번 겪음).
- Windows에서도 한 번에 복사할 수 있도록 **세 명령을 하나의 코드 블록**으로 제공한다(`&&` 없이 줄바꿈):
  ```bash
  git fetch origin
  git tag vX.Y.Z origin/main
  git push origin vX.Y.Z
  ```
- **최신 태그 확인**: `git tag -l "v*" | sort -V | tail` → 그 다음 번호로 올린다.
- 버전 문자열은 `src/mabinogi_addon/version.py`에 있지만 **개발 중엔 `0.0.0`**이고,
  릴리즈 빌드가 태그에서 실제 버전을 주입한다. 직접 손대지 않는다.

### 업데이트 노트
- 새 버전 첫 실행 시 뜨는 노트는 `src/mabinogi_addon/assets/release_notes.md`에 있다.
- **내가 직접 쓸 필요 없음** — 기능 만들 때 Claude가 맨 위 `## vX.Y.Z` 섹션에 채워 둔다.
  릴리즈 전에 맨 위 섹션 버전이 붙일 태그와 같은지만 확인하면 된다.

### 자주 까먹는 동작 특성
- **"업데이트 감지 안 됨 / 토스트 안 뜸" 류 수정은, 그 수정이 들어간 버전을 설치한
  "다음" 업데이트부터 효과가 난다.** 지금 켜둔 구버전엔 수정이 없으니 당연히 안 보인다.
- 설정·등록한 버프/디버프 같은 로컬 데이터는 gitignore라 머신별이다. 기본값(버프 이름·순서)을
  바꿔도 **로컬에 저장된 사용자 설정이 우선**하며 덮어쓰지 않는다.
- 커밋 작성자는 이 저장소 로컬 설정(StarlineBot)을 쓴다. 회사 메일을 쓰지 않는다.
- 게임은 Windows에서만 실행된다. OS 비의존 코드는 맥에서 `uv run pytest`로 검증 가능.

## 시크릿 관리

GitHub Actions 시크릿은 리포 **Settings → Secrets and variables → Actions**에서 넣는다.
`release.yml`이 사용하며, 크게 **(A) exe에 구워 넣는 번들 시크릿**과 **(B) CI에서만 쓰는
배포 시크릿**으로 나뉜다.

| 시크릿 | 분류 | 무엇을 하나 | 언제 쓰나 |
|---|---|---|---|
| `NEXON_API_KEY` | A·번들 | 넥슨 오픈 API 호출 키 (**파티 모집** 조회) | 빌드 시 `_bundled.py`에 주입 → 배포 exe 런타임 |
| `INQUIRY_WEBHOOK_URL` | A·번들 | **문의하기**를 Discord 웹훅으로 전송(모드메일 봇이 받아 작성자에게 DM relay) | 빌드 번들 |
| `CONFIG_WEBHOOK_URL` | A·번들 | **설정 백업**(Discord DM 릴레이)용 웹훅 — 봇이 첨부된 설정을 작성자에게 DM | 빌드 번들 |
| `RELEASES_TOKEN` | B·배포 | 공개 릴리즈 저장소 `mabinogi_addon-releases`에 push + GitHub Release 생성 | 태그(`vX.Y.Z`) push 시 |
| `RELEASE_WEBHOOK_URL` | B·배포 | 새 릴리즈를 Discord **포럼에 새 글**로 공지 | 태그 push 후. **없으면 그 단계만 건너뜀**(릴리즈는 계속) |

**앱 런타임 탐색 순서**(번들 시크릿 A): `.env`/환경변수 → `config.local.json` → 번들값.
즉 개발 중엔 `.env`에 넣고, 배포본은 번들값을 쓴다.

> ⚠️ **번들 시크릿(A)은 "진짜 비밀"이 아니다.** exe 안에 들어가므로 받은 사람이
> 추출할 수 있다(난독화 수준). 넥슨 키/웹훅처럼 유출돼도 치명적이지 않은 것만 번들하고,
> 권한 큰 토큰은 절대 번들하지 않는다.
>
> `RELEASES_TOKEN`(GitHub PAT, 릴리즈 저장소 **write** 권한 필요)과 `RELEASE_WEBHOOK_URL`은
> **CI에서만** 쓰이고 exe에 들어가지 않는다 — 안전하게 보관할 것. PAT 만료 시 릴리즈가
> 실패하므로 갱신 주기를 기억해 둔다.
