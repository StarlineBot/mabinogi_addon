"""개발용: 네이티브 캡처에서 시간 글자 템플릿 세트를 만든다.

왜 필요한가: 시간 글자는 7px로 매우 작아, 게임이 모니터에 맞춰 스케일링(울트라와이드
레터박스 등)되면 사람 눈엔 같은 글자라도 픽셀 패턴이 틀어져 기존 템플릿과 안 맞는다
(점수 ~0.5로 깔림). 그 렌더링의 글자로 '세트'를 따로 떠두면, 리더가 환경에 맞는 세트를
골라 쓸 수 있다. 이 스크립트가 그 세트를 만든다.

방법: 버프 패널 캡처(PNG)와 '각 줄의 시간 문자열'(위→아래)을 주면, 정답 문자열로
글자 위치를 유도(guided) 추출한다. 정답을 알고 있으니 숫자 분간이 틀려도 위치만 맞으면
된다. 2패스로 글자 중심을 먼저 찾고, 이웃 글자와의 중점을 경계로 잘라 깨끗이 분리한다.

출력: <out>/{0..9,bun,cho,hour,day}.png + _montage.png(눈으로 검증용).

예:
    uv run python scripts/build_time_templates.py \
        --image tests/data/buff_scaled.png \
        --out src/mabinogi_addon/detect/templates/time/scaled \
        --times "6분47초,8분20초,28분47초,29분3초,29분18초,29분19초,29분27초,1시간0분52초"

    # --times 생략 시 아래 _DEFAULT_TIMES(57.png 기준) 사용

몽타주를 꼭 확인하고(글자가 라벨과 맞고 깨끗한지) 커밋한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mabinogi_addon.detect.binarize import binarize

# 참고용 기본값(테스터 57.png: 울트라와이드 레터박스 렌더링). 보통은 --times로 준다.
_DEFAULT_TIMES = "6분47초,8분20초,28분47초,29분3초,29분18초,29분19초,29분27초,1시간0분52초"

_UNIT_LABEL = {"시간": "hour", "분": "bun", "초": "cho", "일": "day"}


def parse_time_string(s: str) -> list[str]:
    """'1시간0분52초' → ['1','hour','0','bun','5','2','cho'] (글자 라벨 순서)."""
    labels: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit():
            labels.append(ch)
            i += 1
        elif s[i : i + 2] == "시간":
            labels.append("hour")
            i += 2
        elif ch in _UNIT_LABEL:
            labels.append(_UNIT_LABEL[ch])
            i += 1
        else:
            i += 1  # 공백 등 무시
    return labels


def detect_time_rows(im: np.ndarray) -> list[tuple[int, int]]:
    """버프 패널에서 시간 글자가 있는 행 밴드(y0,y1)들을 위→아래로."""
    _h, w = im.shape[:2]
    right = im[:, w // 2 :].max(axis=2)  # 시간은 오른쪽 → 오른쪽 절반만 봐 이름 영향 줄임
    rows = np.where((right > 170).sum(axis=1) > 4)[0]
    if not len(rows):
        return []
    bands: list[tuple[int, int]] = []
    s = p = rows[0]
    for y in rows[1:]:
        if y - p > 5:
            bands.append((int(s), int(p)))
            s = y
        p = y
    bands.append((int(s), int(p)))
    return bands


# 단위 글자의 대략 폭(px). 블롭이 단위인지 숫자 묶음인지 가르는 참고값.
_UNITS = {"bun", "cho", "hour", "day"}
_DIGIT_W = 5  # 숫자 한 자 대략 폭(데이터상 4~5px)


def _trim(g: np.ndarray) -> np.ndarray | None:
    cy = np.where(g.max(axis=1) > 0)[0]
    cx = np.where(g.max(axis=0) > 0)[0]
    if not len(cy) or not len(cx):
        return None
    return g[cy.min() : cy.max() + 1, cx.min() : cx.max() + 1]


def _blobs(colsum: np.ndarray) -> list[tuple[int, int]]:
    """colsum>0 인 연속 구간(블롭) [x0,x1) 들. 0인 열에서 끊는다."""
    on = colsum > 0
    out: list[tuple[int, int]] = []
    i = 0
    n = len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def extract_row(im: np.ndarray, y0: int, y1: int, labels: list[str]) -> dict[str, np.ndarray]:
    """한 행의 시간 글자들을 라벨별로 잘라낸다.

    템플릿 매칭에 의존하지 않고(렌더링이 달라 점수가 낮으므로), 0인 열로 블롭을 나눈 뒤
    정답 라벨 순서로 배정한다: 단위(분/초/시간/일)는 블롭 하나(시간은 넓어 둘일 수 있어
    폭이 모자라면 다음 블롭까지 합침), 숫자는 블롭 폭/_DIGIT_W 만큼의 자릿수로 쪼갠다.
    """
    _h, w = im.shape[:2]
    row = binarize(im[max(0, y0 - 1) : y1 + 2, w // 2 :])
    xs = np.where(row.max(axis=0) > 0)[0]
    if not len(xs):
        return {}
    row = row[:, xs.min() : xs.max() + 1]
    blobs = _blobs((row > 0).sum(axis=0))

    out: dict[str, np.ndarray] = {}
    bi = 0  # 블롭 인덱스
    i = 0  # 라벨 인덱스
    while i < len(labels) and bi < len(blobs):
        lab = labels[i]
        bx0, bx1 = blobs[bi]
        if lab in _UNITS:
            x0, x1 = bx0, bx1
            # '시간'은 두 음절이라 블롭이 쪼개질 수 있음 → 폭이 모자라면 다음 블롭까지
            if lab == "hour":
                while bi + 1 < len(blobs) and (x1 - x0) < 11:
                    bi += 1
                    x1 = blobs[bi][1]
            g = _trim(row[:, x0:x1])
            if g is not None:
                out[lab] = g
            bi += 1
            i += 1
        else:
            # 이 블롭에 숫자 몇 자? 남은 숫자런(다음 단위 전까지)으로 상한.
            run = 0
            while i + run < len(labels) and labels[i + run] not in _UNITS:
                run += 1
            d = max(1, min(run, round((bx1 - bx0) / _DIGIT_W)))
            step = (bx1 - bx0) / d
            for k in range(d):
                sx0 = bx0 + round(k * step)
                sx1 = bx0 + round((k + 1) * step)
                g = _trim(row[:, sx0:sx1])
                if g is not None:
                    out[labels[i + k]] = g
            bi += 1
            i += d
    return out


def build(image: Path, out: Path, times: list[str]) -> None:
    im = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit(f"이미지를 못 읽음: {image}")
    bands = detect_time_rows(im)
    if len(bands) < len(times):
        print(f"[경고] 탐지된 시간 행 {len(bands)} < 준 시간문자열 {len(times)}")
    samples: dict[str, list[np.ndarray]] = {}
    for (y0, y1), tstr in zip(bands, times):
        for lab, glyph in extract_row(im, y0, y1, parse_time_string(tstr)).items():
            samples.setdefault(lab, []).append(glyph)

    out.mkdir(parents=True, exist_ok=True)
    order = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "bun", "cho", "hour", "day"]
    cells = []
    for lab in order:
        if lab not in samples:
            continue
        # 대표 샘플: 폭의 중앙값에 가장 가까운 것(튀는 크롭 배제)
        ws = sorted(samples[lab], key=lambda g: g.shape[1])
        glyph = ws[len(ws) // 2]
        cv2.imwrite(str(out / f"{lab}.png"), glyph)
        big = cv2.cvtColor(
            cv2.resize(glyph, (glyph.shape[1] * 14, glyph.shape[0] * 14), interpolation=cv2.INTER_NEAREST),
            cv2.COLOR_GRAY2BGR,
        )
        big = cv2.copyMakeBorder(big, 20, 4, 4, 4, cv2.BORDER_CONSTANT, value=100)
        cv2.putText(big, f"{lab} {glyph.shape[1]}x{glyph.shape[0]}", (3, 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        canvas = np.full((170, 180, 3), 40, np.uint8)
        canvas[: min(170, big.shape[0]), : min(180, big.shape[1])] = big[:170, :180]
        cells.append(canvas)
    if cells:
        cv2.imwrite(str(out / "_montage.png"), np.hstack(cells))
    missing = [d for d in "0123456789" if d not in samples]
    print(f"저장: {out}  (글자 {sorted(samples)})")
    if missing:
        print(f"[주의] 빠진 숫자: {missing} — 그 숫자가 보이는 캡처를 더 넣어라")
    print(f"검증: {out / '_montage.png'} 를 열어 라벨과 글자가 맞는지 확인")


def main() -> None:
    ap = argparse.ArgumentParser(description="시간 글자 템플릿 세트 생성")
    ap.add_argument("--image", required=True, type=Path, help="버프 패널 PNG")
    ap.add_argument("--out", required=True, type=Path, help="세트 출력 디렉터리")
    ap.add_argument("--times", default=_DEFAULT_TIMES,
                    help="각 줄 시간문자열(위→아래), 쉼표 구분. 예 '6분47초,8분20초,...'")
    a = ap.parse_args()
    build(a.image, a.out, [t.strip() for t in a.times.split(",") if t.strip()])


if __name__ == "__main__":
    main()
