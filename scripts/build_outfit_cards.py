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
# 상반신이 허리 위에서 끝나 카드 아래가 비는 옷 → 전신.png를 잘라 씀(사용자 11-25 '전신이 있으니 잘라 쓰면 되잖아'),
# 전신은 작게 그려져 있어 배율 상한을 조금 올림
FROM_FULL = {("이안", "vest_tie"): ("전신.png", 1.25), ("이안", "guild_uniform"): ("전신.png", 1.25)}   # 배율 0.002 단위로   # 세로 위·아래, 가로 왼·오른(비율)


def _gray_on_white(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:].astype(np.float32) / 255
    g = cv2.cvtColor(np.ascontiguousarray(rgba[..., :3]), cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None]
    return (g * a + 255 * (1 - a))[..., 0].astype(np.uint8)


def fit(card: np.ndarray, upper: np.ndarray, max_k: float = 1.2, step: float = 0.01) -> tuple[np.ndarray, float, float]:
    """(카드 크기 그림, 일치 점수, 배율)."""
    h, w = card.shape[:2]
    y0, y1, x0, x1 = (int(FACE[0] * h), int(FACE[1] * h), int(FACE[2] * w), int(FACE[3] * w))
    tmpl = _gray_on_white(card)[y0:y1, x0:x1]
    gray = _gray_on_white(upper)
    best = (-2.0, 1.0, (0, 0))
    lo = 0.25 if step >= 0.01 else max(0.25, max_k - 0.2)   # 촘촘히 찾을 땐 상한 근처만(전신은 배율 1.0~1.25)
    for k in np.linspace(lo, max_k, int(round((max_k - lo) / step)) + 1):
        g = cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        if g.shape[0] < tmpl.shape[0] or g.shape[1] < tmpl.shape[1]:
            continue
        res = cv2.matchTemplate(g, tmpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best[0]:
            best = (float(score), float(k), loc)
    score, k, (lx, ly) = best
    big = cv2.resize(upper, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    ox, oy = x0 - lx, y0 - ly   # 상반신을 카드 좌표로 옮기는 양
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
            source, max_k = FROM_FULL.get((folder, outfit.key), ("상반신.png", 1.2))
            upper = imread(SRC / folder / "의상" / outfit.name / source, cv2.IMREAD_UNCHANGED)
            image, score, k = fit(card, upper, max_k, 0.002 if (folder, outfit.key) in FROM_FULL else 0.01)
            dest = ASSETS / outfits.asset(folder, outfit.key, "card.png")
            dest.parent.mkdir(parents=True, exist_ok=True)
            imwrite(dest, image)
            done.append((folder, outfit.name, score, k))
    return done


if __name__ == "__main__":
    for folder, name, score, k in build():
        print(f"{folder} {name}: 일치 {score:.2f} 배율 {k:.2f}")
