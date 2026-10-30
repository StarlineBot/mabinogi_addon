"""개발용: 확대·뭉개진 4K 렌더링의 시간 글자 세트를 만든다(같은 글자의 모양 차이를 변형으로 함께 저장).

build_time_templates.py는 라벨마다 글자 하나만 뜬다. 4K에서 게임 UI가 늘어나 그려지면(0.30.1 조사:
글자 8px·9px, 획 뭉침) 같은 숫자도 줄의 세로 위치(리샘플링 위상)·글자색(빨강 시간)에 따라 모양이 달라
하나로는 모든 줄을 못 읽는다. 이 스크립트는 정답 문자열로 줄마다 글자를 잘라 서로 다른 모양을 모두
`<라벨>.png`, `<라벨>~2.png` …로 저장한다(time_reader가 `~` 뒤를 떼고 같은 라벨로 읽는다).

줄 지정: 버프 영역 안 아이콘 위쪽 y(엔진의 icon_y)와 그 줄의 시간 문자열. 시간 글자는 엔진과 같은
위치(icon_y-4 ~ icon_y+24, x 150~)에서 이진화한 뒤, 빈 열로 글자를 나눈다.

예(0.30.1 image55 — 다른 4K 자료도 같은 폴더에 변형으로 합쳤다):
    uv run python scripts/build_time_variant_set.py --image tests/data/image55.png \\
        --box 3546,392,293,1763 --out src/mabinogi_addon/detect/templates/time/uhd \\
        --rows "400:3분20초,424:3분22초,448:1분22초,472:1분22초,568:5분33초,592:6분45초,626:3분20초,650:3분20초,674:3분20초,698:3분37초,722:24분39초"

몽타주(_montage.png는 저장하지 않고 --montage 경로에)로 글자와 라벨이 맞는지 꼭 확인하고 커밋한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mabinogi_addon import image_io  # noqa: E402
from mabinogi_addon.detect.binarize import binarize  # noqa: E402

_UNIT = {"분": "bun", "초": "cho", "일": "day"}
_TIME_RIGHT = 132  # 시간 글자 오른쪽 끝(strip 기준) 너머의 패널 테두리 세로선은 빼고 나눈다


def labels_of(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        if text[i:i + 2] == "시간":
            out.append("hour")
            i += 2
            continue
        if text[i].isdigit() or text[i] in _UNIT:
            out.append(_UNIT.get(text[i], text[i]))
        i += 1
    return out


def glyph_groups(strip: np.ndarray) -> list[list[int]]:
    """빈 열로 나눈 글자 열 묶음. '초'처럼 위 획이 떨어진 글자는 붙어 있는(≤2px) 넓은 묶음끼리 합친다."""
    cols = np.where(strip.max(axis=0) > 0)[0]
    groups: list[list[int]] = []
    for c in cols:
        if groups and c - groups[-1][-1] <= 1:
            groups[-1].append(int(c))
        else:
            groups.append([int(c)])
    merged: list[list[int]] = []
    for g in groups:
        if merged and g[0] - merged[-1][-1] <= 2 and len(merged[-1]) > 5 and len(merged[-1]) + len(g) <= 10:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    return merged


def split_touching(strip: np.ndarray, groups: list[list[int]], labels: list[str]) -> list[list[int]]:
    """9px 굵은 렌더링처럼 이웃 글자가 붙어 묶음이 모자라면, 가장 넓은 묶음을 잉크가 가장 적은 열에서 나눈다."""
    groups = [list(g) for g in groups]
    ink = (strip > 0).sum(axis=0)
    while len(groups) < len(labels):
        wide = max(range(len(groups)), key=lambda i: len(groups[i]))
        g = groups[wide]
        if len(g) < 10:
            break
        cut = min(range(4, len(g) - 4), key=lambda i: (ink[g[i]], abs(i - 5)))
        groups[wide:wide + 1] = [g[:cut], g[cut + 1:]]
    return groups


def extract(image: Path, box: tuple[int, int, int, int], rows: list[tuple[int, str]]) -> dict[str, list[np.ndarray]]:
    frame = image_io.imread(image, cv2.IMREAD_COLOR)
    x, y, w, h = box
    region = frame[y:y + h, x:x + w]
    found: dict[str, list[np.ndarray]] = {}
    for icon_y, text in rows:
        strip = binarize(region[max(0, icon_y - 4):icon_y + 24, 150:])[:, :_TIME_RIGHT]
        labels = labels_of(text)
        groups = split_touching(strip, glyph_groups(strip), labels)[-len(labels):]  # 오른쪽 정렬: 뒤에서부터
        if len(groups) != len(labels):
            raise SystemExit(f"{icon_y} {text}: 글자 {len(labels)}개인데 묶음 {len(groups)}개")
        for label, g in zip(labels, groups):
            x0, x1 = g[0], g[-1] + 1
            if label.isdigit() and x1 - x0 < 5:  # '1'처럼 좁은 숫자는 숫자 칸(5px) 가운데로
                x0 -= (5 - (x1 - x0)) // 2
                x1 = x0 + 5
            glyph = strip[:, x0:x1]
            ys = np.where(glyph.max(axis=1) > 0)[0]
            glyph = glyph[ys.min():ys.max() + 1]
            variants = found.setdefault(label, [])
            if not any(v.shape == glyph.shape and np.array_equal(v, glyph) for v in variants):
                variants.append(glyph)
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description="시간 글자 변형 세트 생성")
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--box", required=True, help="버프 영역 x,y,w,h")
    ap.add_argument("--rows", required=True, help="icon_y:시간문자열, 쉼표 구분")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--montage", type=Path)
    args = ap.parse_args()
    box = tuple(int(v) for v in args.box.split(","))
    rows = [(int(a), b) for a, b in (item.split(":") for item in args.rows.split(","))]
    found = extract(args.image, box, rows)
    args.out.mkdir(parents=True, exist_ok=True)
    tiles = []
    for label, variants in sorted(found.items()):
        for i, glyph in enumerate(variants):
            name = label if i == 0 else f"{label}~{i + 1}"
            image_io.imwrite(args.out / f"{name}.png", glyph)
            print(name, glyph.shape)
            tile = np.zeros((14, 20), np.uint8)
            tile[:glyph.shape[0], :glyph.shape[1]] = glyph
            tiles.append(tile)
    if args.montage and tiles:
        cv2.imwrite(str(args.montage), cv2.resize(np.hstack(tiles), None, fx=6, fy=6,
                                                  interpolation=cv2.INTER_NEAREST))


if __name__ == "__main__":
    main()
