"""레나 서기 → 쓰다듬기 머리색 비교 한 장(사용자 11-24 '쓰다듬을 때 머리색이 달라짐').

실행: uv run python -m scripts.render_lena_hair
위: 보정 전(시트 그대로) 서기 · 쓰다듬기 0·2·5 / 아래: 보정 뒤(앱 그림).
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_dare_frames import ROOT, imread, imwrite, scaled
from scripts.build_lena_frames import OUT, sheet

DEST = ROOT / "docs/assets/character-alpha-20261124/lena_pet_hair.png"


def _on_white(frame: np.ndarray, h: int) -> np.ndarray:
    f = scaled(frame, h / frame.shape[0])
    a = f[..., 3:] / 255.0
    return (f[..., :3] * a + 245 * (1 - a)).astype(np.uint8)


def main() -> None:
    raw = sheet("레나_쓰다듬기")
    before = [imread(OUT / "stand_0.png", cv2.IMREAD_UNCHANGED)] + [raw[i] for i in (0, 2, 5)]
    after = [imread(OUT / f"{n}.png", cv2.IMREAD_UNCHANGED) for n in ("stand_0", "pet_0", "pet_2", "pet_5")]
    rows = []
    for label, frames in (("before", before), ("after", after)):
        tiles = [_on_white(f, 260) for f in frames]
        tiles = [np.pad(t, ((10, 10), (10, 10), (0, 0)), constant_values=245) for t in tiles]
        h = max(t.shape[0] for t in tiles)
        row = np.hstack([np.pad(t, ((0, h - t.shape[0]), (0, 0), (0, 0)), constant_values=245) for t in tiles])
        cv2.putText(row, label, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 60), 2)
        rows.append(row)
    w = max(r.shape[1] for r in rows)
    sheet_img = np.vstack([np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=245) for r in rows])
    imwrite(DEST, sheet_img)
    print(DEST)


if __name__ == "__main__":
    main()
