"""캐릭터 카드 테두리(기획 11-25, docs/characters/카드_테두리.md) — 원본 테두리를 카드(224×280) 크기로 9칸 나눠 늘려
2배 해상도 그림 하나로 저장: assets/characters/<폴더>/frame.png + frame.json {x, y, w, h}(카드 왼쪽 위 기준 px, 카드 좌표).

- 원본의 '테두리 선 사각형'(L,T,R,B)을 카드 사각형에 맞춤. 가로는 배율 c = 카드폭 / (R−L) 하나, 세로는 모서리 CS px만
  비율 그대로(위·아래 묶음) 두고 가운데 변만 늘림/줄임. 선 밖 장식(날개·리본)은 카드 밖으로 넘침(x·y가 음수).

    uv run --frozen python -m scripts.build_card_frames
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon.image_io import imread
from mabinogi_addon.image_io import write_sprite as imwrite   # 알파 0 RGB 0·압축 9

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "characters" / "assets"
ASSETS = ROOT / "src" / "mabinogi_addon" / "assets" / "characters"
CARD_W, CARD_H = 224, 280
SCALE = 2   # 저장 해상도(카드 2배)

# 이름: (L, T, R, B, 모서리 CS) — 원본 px(기획 측정)
FRAMES = {
    "다래": (85, 43, 1104, 1304, 250),
    "아리아": (146, 64, 1106, 1195, 330),
    "레나": (93, 36, 1087, 1290, 340),
    "이안": (86, 33, 1103, 1304, 110),
    "Starline": (110, 40, 1040, 1273, 300),
}


def nine_slice(src: np.ndarray, box: tuple[int, int, int, int, int], w: int, h: int) -> tuple[np.ndarray, int, int]:
    """(결과 그림, 카드 왼쪽 위의 결과 안 x, y) — 결과에서 카드 사각형은 (x, y, w, h)."""
    left, top, right, bottom, cs = box
    sh, sw = src.shape[:2]
    c = w / (right - left)
    full = cv2.resize(src, (round(sw * c), round(sh * c)), interpolation=cv2.INTER_AREA)
    ox, oy = round(left * c), round(top * c)
    top_end = round((top + cs) * c)                  # 위 묶음(원본 0 ~ T+CS)
    bot_start = round((bottom - cs) * c)              # 아래 묶음(원본 B−CS ~ 끝)
    out_h = oy + h + (full.shape[0] - round(bottom * c))
    out = np.zeros((out_h, full.shape[1], 4), np.uint8)
    dest_bot = oy + h - (round(bottom * c) - bot_start)
    mid_h = dest_bot - top_end
    out[:top_end] = full[:top_end]
    out[dest_bot:] = full[bot_start:bot_start + (out_h - dest_bot)]
    if mid_h > 0:
        out[top_end:dest_bot] = cv2.resize(full[top_end:bot_start], (full.shape[1], mid_h), interpolation=cv2.INTER_AREA)
    return out, ox, oy


def build() -> dict[str, dict]:
    done = {}
    for folder, box in FRAMES.items():
        src = imread(SRC / folder / "카드_테두리.png", cv2.IMREAD_UNCHANGED)
        image, ox, oy = nine_slice(src, box, CARD_W * SCALE, CARD_H * SCALE)
        ys, xs = np.nonzero(image[..., 3] > 0)   # 투명한 바깥은 잘라 냄
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        image = image[y0:y1, x0:x1]
        meta = {"x": float(round((x0 - ox) / SCALE, 2)), "y": float(round((y0 - oy) / SCALE, 2)),
                "w": float(round((x1 - x0) / SCALE, 2)), "h": float(round((y1 - y0) / SCALE, 2))}
        imwrite(ASSETS / folder / "frame.png", image)
        (ASSETS / folder / "frame.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
        done[folder] = meta
    return done


if __name__ == "__main__":
    for folder, meta in build().items():
        print(folder, meta)
