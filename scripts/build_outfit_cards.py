"""착장 카드 그림 만들기(기획 11-25) — 상반신.png를 지금 card.png와 같은 틀로(얼굴 맞춤) 잘라
assets/characters/<폴더>/outfits/<key>/card.png 로 저장.

방법: card.png(회색, 흰 배경 합성)의 얼굴 영역(세로 18~55%, 가로 28~72%)을 템플릿으로, 상반신을 배율 0.25~1.2(96단계)
바꿔 가며 matchTemplate(TM_CCOEFF_NORMED) → 최고 위치·배율로 card 크기 캔버스(투명)에 붙임.

    uv run --frozen python -m scripts.build_outfit_cards
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon.character import outfits
from mabinogi_addon.image_io import imread, imwrite

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "characters" / "assets"
ASSETS = ROOT / "src" / "mabinogi_addon" / "assets" / "characters"
FACE = (0.18, 0.55, 0.28, 0.72)
MAX_GROW = 1.05   # 아래를 채우려 배율을 키우는 한도(얼굴 크기 차이 ≤ 5%)
MAX_SHIFT = 5     # 그래도 모자라면 위로 올리는 한도(얼굴 위치 차이 ≤ 6px — 반올림 여유 1px)   # 세로 위·아래, 가로 왼·오른(비율)


def _gray_on_white(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:].astype(np.float32) / 255
    g = cv2.cvtColor(np.ascontiguousarray(rgba[..., :3]), cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None]
    return (g * a + 255 * (1 - a))[..., 0].astype(np.uint8)


def fit(card: np.ndarray, upper: np.ndarray) -> tuple[np.ndarray, float, float]:
    """(카드 크기 그림, 일치 점수, 배율)."""
    h, w = card.shape[:2]
    y0, y1, x0, x1 = (int(FACE[0] * h), int(FACE[1] * h), int(FACE[2] * w), int(FACE[3] * w))
    tmpl = _gray_on_white(card)[y0:y1, x0:x1]
    gray = _gray_on_white(upper)
    best = (-2.0, 1.0, (0, 0))
    for k in np.linspace(0.25, 1.2, 96):
        g = cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        if g.shape[0] < tmpl.shape[0] or g.shape[1] < tmpl.shape[1]:
            continue
        res = cv2.matchTemplate(g, tmpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best[0]:
            best = (float(score), float(k), loc)
    score, k, (lx, ly) = best
    # 아래까지 채우기(QA 11-25 '착장 카드 아래가 비어 짧아 보임'): 상반신 아래 끝(가운데 칸 불투명)이 카드 아래에 못 미치면
    # 얼굴 가운데를 고정한 채 배율을 키움 — 최대 MAX_GROW(얼굴 크기 차이 ≤ 5%). 그래도 모자라면 짧은 채(호출 쪽이 알림)
    th, tw = tmpl.shape
    fx, fy = (lx + tw / 2) / k, (ly + th / 2) / k            # 원본 얼굴 가운데
    cx, cy = x0 + tw / 2, y0 + th / 2                          # 카드 얼굴 가운데
    mid = upper[:, upper.shape[1] // 3: upper.shape[1] * 2 // 3, 3] > 128
    rows = np.nonzero(mid.mean(axis=1) > 0.5)[0]
    bottom = float(rows.max() + 1) if len(rows) else float(upper.shape[0])
    need = (h + 2 - cy) / max(1.0, bottom - fy)   # +2: 반올림으로 아래 한두 줄이 비지 않게
    if need > k:
        k = min(need, k * MAX_GROW)
    big = cv2.resize(upper, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    ox, oy = round(cx - fx * k), round(cy - fy * k)   # 상반신을 카드 좌표로 옮기는 양(얼굴 가운데 고정)
    short = h - (oy + bottom * k)                     # 그래도 모자란 줄 수 → 위로 최대 MAX_SHIFT px 올려 채움
    if short > 0:
        oy -= int(np.ceil(min(short, MAX_SHIFT)))
    out = np.zeros((h, w, 4), np.uint8)
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    cw = min(w - dx0, big.shape[1] - sx0)
    ch = min(h - dy0, big.shape[0] - sy0)
    out[dy0:dy0 + ch, dx0:dx0 + cw] = big[sy0:sy0 + ch, sx0:sx0 + cw]
    return out, score, k


def build() -> list[tuple[str, str, float, float]]:
    done = []
    for folder, items in outfits.OUTFITS.items():
        card = imread(ASSETS / folder / "card.png", cv2.IMREAD_UNCHANGED)
        for outfit in items:
            if outfit.key == outfits.BASE:
                continue
            upper = imread(SRC / folder / "의상" / outfit.name / "상반신.png", cv2.IMREAD_UNCHANGED)
            image, score, k = fit(card, upper)
            dest = ASSETS / outfits.asset(folder, outfit.key, "card.png")
            dest.parent.mkdir(parents=True, exist_ok=True)
            imwrite(dest, image)
            done.append((folder, outfit.name, score, k))
    return done


if __name__ == "__main__":
    for folder, name, score, k in build():
        print(f"{folder} {name}: 일치 {score:.2f} 배율 {k:.2f}")
