# 제작자 대사 GitHub 등록 및 개발 전달 안내

- 작성일: 2026-10-15
- 기능 동작의 기준: [제작자 얼굴 및 랜덤 말풍선 명세](creator-dialogue-spec.md).
- 등록용 초기 데이터: [dialogues.json](examples/creator-dialogues/dialogues.json).
- 문장 틀 10개와 고정 대사 2개, 총 12개 항목으로 시작한다. 이후 작성자가 문구를 수정·보충한다.
- 초기 JSON 형식 채택은 확정했다. 앱에서 읽는 기능은 아직 구현하지 않았다.
- 공개 대상: 기존 릴리즈 저장소 `StarlineBot/mabinogi_addon-releases`의 `main` 브랜치, `data/dialogues.json`.
- 이 안내만으로 원격 파일을 업로드/푸시하지 않는다.

## 1. 무엇을 공개하는가

앱 코드나 사용자 설정 대신 대사 데이터만 공개한다. 별도 저장소를 새로 만들지 않고,
기존 공개 릴리즈 저장소 [StarlineBot/mabinogi_addon-releases](https://github.com/StarlineBot/mabinogi_addon-releases)를 사용한다.

대사 파일은 `main` 브랜치의 `data/dialogues.json`에 둔다. 릴리즈 첨부파일이 아니라
브랜치의 Raw 파일을 앱이 읽는다. 대사 명세와 앱 소스, 사진 원본, 설정 파일, 토큰을
함께 공개할 필요는 없다. GitHub Pages나 별도 웹서버도 필수가 아니다.

저장소 이름은 `mabinogi_addon-release`가 아니라 **`mabinogi_addon-releases`**이다.
현재 앱의 배포 워크플로와 업데이트 주소가 참조하는 이름을 기준으로 한다.

현재 `.github/workflows/release.yml`은 공개 저장소를 받은 뒤 `version.json`, `README.md`,
`CHANGELOG.md`를 갱신하고 이 세 파일만 커밋한다. 현재 소스에는 `data/`를 삭제하거나
저장소 전체를 대체하는 처리가 없다. 향후 배포 자동화를 바꿀 때도 수동 관리하는
`data/dialogues.json`을 보존한다.

## 2. GitHub 웹에서 처음 등록하기

1. GitHub에서 `StarlineBot/mabinogi_addon-releases`를 열고 `main` 브랜치를 선택한다.
2. `data` 폴더가 없으면 `Add file` → `Create new file`을 열어 파일명에
   `data/dialogues.json`을 지정한다. 이 프로젝트의
   `docs/examples/creator-dialogues/dialogues.json`을 내용으로 등록한다.
3. `data` 폴더가 이미 있으면 그 폴더 안의 `Add file` → `Upload files`로 샘플을 업로드해도 된다.
   이미 `data/dialogues.json`이 있다면 새 파일로 중복 등록하지 말고 기존 파일을 수정한다.
4. 변경을 `main`에 커밋한다. 예: `제작자 초기 대사 등록`.
5. `main`의 `data/dialogues.json`을 열고 `Raw`를 누른다.
6. 브라우저 주소창의 Raw 주소를 개발 세션에 전달한다.
7. 로그아웃한 브라우저나 비공개 창에서도 그 주소의 JSON이 로그인 없이 열리는지 확인한다.

Raw 주소는 실제 등록 후 얻은 것을 사용한다. 아직 존재하지 않는 주소를 검증된 주소처럼
앱에 넣지 않는다. 파일은 릴리즈 태그가 아닌 `main` 브랜치에 등록한다.

예정 Raw 주소는 다음과 같다. 경로는 정했지만 실제 파일 등록과 접근 성공은 별도 확인이 필요하다.

```text
https://raw.githubusercontent.com/StarlineBot/mabinogi_addon-releases/refs/heads/main/data/dialogues.json
```

앱에는 개별 커밋에 고정된 주소가 아니라 갱신할 브랜치의 파일 주소를 전달한다. Raw 경유의
캐시/통신 때문에 수정 직후 모든 앱에 즉시 반영된다고 보장하지 않는다.
앱은 시작 시 백그라운드에서 한 번 수신하므로 실행 중 수정은 다음 앱 실행의 정상 수신에서 반영된다.

공식 안내:
- [새 파일 등록](https://docs.github.com/en/repositories/working-with-files/managing-files/creating-new-files)
- [파일의 Raw 내용 보기](https://docs.github.com/en/repositories/working-with-files/using-files/viewing-and-understanding-files)

## 3. 초기 대사 데이터 읽는 법

현재 형식은 특정 라이브러리의 실행식 대신 문자열과 선택지 배열을 담는다. 목적은 작성자가
고정 대사와 조합 재료를 관리하는 것이다. RiScript/Tracery 도입을 이 파일이 강제하지 않는다.

```json
{
  "schemaVersion": 1,
  "language": "ko-KR",
  "format": "choice-parts-v1",
  "entries": [
    {
      "id": "todays-resolution",
      "parts": [
        "오늘의 ",
        ["계획은", "목표는", "결심은"],
        " ",
        ["내일 세우겠습니다.", "아직 비밀입니다."]
      ]
    },
    {
      "id": "potato-question",
      "parts": ["감자는 왜 감자일까요."]
    }
  ]
}
```

| 항목 | 의미 |
|---|---|
| `schemaVersion` / `format` | 확정 데이터 형식을 구분하는 값. 대사 하나를 추가할 때마다 바꾸는 번호가 아님 |
| `language` | 대사 언어. 현재 `ko-KR` |
| `entries` | 선택 가능한 대사 또는 문장 틀 목록 |
| `id` | 항목 고유 ID. 다른 항목과 중복하지 않고, 기존 항목의 문구를 고칠 때는 유지 |
| `parts`의 문자열 | 순서대로 그대로 이어 붙일 부분 |
| `parts` 안의 문자열 배열 | 해당 위치에 들어갈 표현 후보. 배열에서 하나를 골라 이어 붙임 |

- 띄어쓰기는 문자열에 들어 있는 공백을 그대로 사용한다.
- 선택지에는 문자열만 넣고 중첩 배열이나 실행 코드를 넣지 않는다.
- `parts`에 문자열 하나만 넣으면 고정 대사이다.
- 직전에 표시한 완성 문장과 같은 문장은 연속 표시하지 않는다. 비교는 자동/클릭과 탭 이동을
  통틀어 적용하며, 같은 문장 틀에서 다른 완성 문장이 나오면 표시할 수 있다.
- 데이터에는 대사별 특별 가중치를 넣지 않는다. 40%/20%는 대사를 띄울지의 확률이며
  개별 단어를 선택하는 확률과 혼동하지 않는다.
- 위 예에서는 `오늘의 계획은 내일 세우겠습니다.` 등의 문장이 가능하다. 준비하지 않은
  소재를 자동으로 창작하는 형식은 아니다.

초기 공개 파일과 앱 내장 기본 데이터는 같은 확정 형식과 12개 샘플로 시작한다.
지원하는 데이터 형식을 나중에 바꿀 때는 기존 배포 앱의 호환성을 확인한다.

## 4. 나중에 대사 추가/수정하기

1. `mabinogi_addon-releases`의 `main`에서 `data/dialogues.json`을 연다.
2. 파일 편집 버튼을 눌러 `entries`에 항목을 추가하거나 기존 `parts`를 수정한다.
3. 새 항목에는 새로운 `id`를 부여한다. 기존 ID를 다른 소재에 재활용하지 않는다.
4. JSON의 따옴표·쉼표·배열 구조와 대사 길이를 확인하고 커밋한다.
5. Raw에서 변경 내용을 확인한다. 앱을 다음에 실행하면 시작 시 1회 갱신에서 수신한다.

앱 릴리즈나 태그 생성은 대사 변경마다 필요하지 않다. 다만 앱이 지원하지 않는 새로운
데이터 형식이나 조합 기능을 추가하는 것은 대사 추가가 아니라 앱 지원 변경이다.

## 5. 개발 세션에 전달할 것

| 자료 | 용도 |
|---|---|
| `docs/creator-dialogue-spec.md` | 노출 범위, 창 높이 확장, 가려짐 조건, 2분/40%/20%/최근 10분/3초와 Acceptance Criteria |
| 실제 등록한 공개 저장소의 Raw 주소 | 앱이 대사 목록을 가져올 실제 주소 |
| `docs/examples/creator-dialogues/dialogues.json` | 채택한 초기 데이터 형식과 12개 대사 샘플 |
| `docs/creator-dialogue-publishing.md` | 작성자 관리 절차와 데이터 해석 설명 |

아래 전달문은 정해진 저장소/경로를 포함한다. 실제 파일 등록 및 Raw 접근 여부를 확인한 뒤 전달한다.

```text
제작자 얼굴과 랜덤 말풍선 기능을 개발해 주세요.

기능 기준: docs/creator-dialogue-spec.md
등록/관리 안내: docs/creator-dialogue-publishing.md
초기 데이터: docs/examples/creator-dialogues/dialogues.json
대사 저장소/경로: StarlineBot/mabinogi_addon-releases, main, data/dialogues.json
예정 Raw 주소: https://raw.githubusercontent.com/StarlineBot/mabinogi_addon-releases/refs/heads/main/data/dialogues.json
위 주소의 실제 파일 등록 및 로그인 없는 접근을 확인한 뒤 연결해 주세요.

확정된 핵심 동작:
- 일반 기능 화면은 기존 콘텐츠 높이를 유지하고 하단 공간을 추가해 얼굴을 표시합니다.
- 설정은 기존 제작자 사진을 사용합니다. 첫 사용/자동설정 등 설정 전용 안내에는 표시하지 않습니다.
- 얼굴과 표시 예정 말풍선 영역이 가려지지 않을 때만 자동 대사를 표시합니다. 포커스만으로 제한하지 않습니다.
- 마지막 추첨으로부터 2분 간격, 기본 40%, 최근 10분 자동 표시 3회 이상이면 20%입니다.
- 앱 실행 후 처음 노출 가능해지면 바로 한 번 추첨합니다. 재실행 시 추첨·자동 표시 횟수 기록은 초기화합니다.
- 노출 복귀 시 간격이 지났으면 한 번만 추첨하고 숨겨진 동안의 추첨을 몰아서 하지 않습니다.
- 얼굴 클릭은 확률과 무관하게 대사를 요청하며 자동 표시 횟수에 포함하지 않습니다.
- 말풍선은 3초 유지하고 클릭으로 닫힙니다. 닫는 클릭은 뒤 컨트롤에 전달하지 않습니다.
- 표시 중 얼굴 클릭은 새 대사로 바꾸고 3초를 다시 계산합니다. 표시 중 자동 추첨은 생략합니다.
- 가림·최소화·잠금·절전 시 말풍선을 닫고 복귀해도 이전 대사는 다시 표시하지 않습니다.
- 말풍선이 콘텐츠 일부를 잠시 가리는 것은 허용합니다. 입력/드래그 감지 억제는 넣지 않습니다.
- 공개 대사 갱신 실패 시 마지막 정상 목록/내장 대사로 동작하고 기존 앱 기능을 막지 않습니다.
- 대사는 main의 Raw 파일을 읽고 릴리즈 첨부파일이나 태그에 묶지 않습니다. 배포 자동화에서 data/dialogues.json을 보존합니다.
- 앱 시작 시 백그라운드에서 한 번 수신합니다. 직전 완성 문장은 연속 표시하지 않습니다.
- 설정에 잡담 사용 옵션을 두고 기본은 켜짐입니다. 끄면 현재 말풍선과 자동/클릭 대사를 표시하지 않습니다.

첨부 JSON 형식과 12개 샘플로 시작합니다. 특정 문장 생성 라이브러리는 필수가 아닙니다.
추가 동작 결정은 없으며 명세 13절의 구현·배포 확인사항을 수행해 주세요.
얼굴/말풍선 레이아웃은 실제 제작자 이미지로 렌더해 보여준 뒤 진행해 주세요.
실제 Windows 가려짐 판정과 DPI 검증을 오프스크린 렌더 결과로 대신하지 마세요.
```

Raw 주소가 아직 없으면 대사 샘플로 로컬 배치 검토를 할 수는 있지만 원격 갱신이 완료되었다고
보고하지 않는다. 자료가 로컬에만 있으면 다른 개발 세션에서도 공유되는지 확인하거나,
기획 문서 푸시 후 최신 소스를 받아 전달한다.
