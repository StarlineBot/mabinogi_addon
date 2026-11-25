"""앱 캐릭터 PNG를 작게 다시 저장(QA 11-25 — exe가 200 MiB를 넘음): 알파 0 픽셀 RGB를 0으로 + 압축 9.
보이는 픽셀(알파 > 0)은 그대로인지 저장 전후로 비교한다. 빌드 스크립트도 같은 write_sprite로 저장.

    uv run --frozen python -m scripts.normalize_sprites
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon.image_io import imread, write_sprite

ROOT = Path(__file__).resolve().parents[1] / "src" / "mabinogi_addon" / "assets" / "characters"


def main() -> None:
    before = after = 0
    for path in sorted(ROOT.rglob("*.png")):
        old = imread(path, cv2.IMREAD_UNCHANGED)
        size = path.stat().st_size
        before += size
        write_sprite(path, old)
        new = imread(path, cv2.IMREAD_UNCHANGED)
        if old.ndim == 3 and old.shape[2] == 4:
            seen = old[..., 3] > 0
            if not (np.array_equal(old[seen], new[seen]) and np.array_equal(old[..., 3], new[..., 3])):
                raise SystemExit(f"보이는 그림이 바뀜: {path}")
        elif not np.array_equal(old, new):
            raise SystemExit(f"그림이 바뀜: {path}")
        after += path.stat().st_size
    print(f"{before / 1e6:.1f}MB → {after / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
