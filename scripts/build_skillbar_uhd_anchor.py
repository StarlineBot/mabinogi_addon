"""개발용: 4K 단축바 페이지 화살표(◀▶ 2줄) 앵커 변형을 만든다(0.30.4).

4K에서는 화살표가 회색에 검은 테두리가 거의 없이 그려져 기본 앵커와 0.91~0.93(< 0.97)으로만 맞았다.
배경이 다른 4K 두 장(파란 얼음 213520·붉은 바닥 214016)에서 같은 자리(564,24)를 39×69로 떠서,
앵커 = 두 장 평균, 마스크 = 예전 전체 마스크(0.30.0 이전 1020px) 안에서 두 장 값 차이 < 40인 픽셀(배경 제외).
나머지 4K 5장(image55·213927·213942·214051·214648)은 세트에 쓰지 않고 따로 검증한다(tests/test_skillbar_4k.py).

    uv run python scripts/build_skillbar_uhd_anchor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mabinogi_addon import image_io  # noqa: E402

TRAIN = ("mabinogi_2026_10_30_213520.png", "mabinogi_2026_10_30_214016.png")
X, Y, W, H = 564, 24, 39, 69
# 0.30.0 이전 마스크(화살표 둘레 전체, 1020px) — git show 5376862^:.../skillbar_mask.png
FULL_MASK = ROOT / "scripts/data/skillbar_mask_full.png"


def main() -> None:
    crops = [image_io.imread(ROOT / "tests/data" / name)[Y:Y + H, X:X + W].astype(np.int16) for name in TRAIN]
    full = image_io.imread(FULL_MASK, cv2.IMREAD_GRAYSCALE) > 0
    stable = (np.max(crops, axis=0) - np.min(crops, axis=0)).max(axis=2) < 40
    mask = np.where(full & stable, 255, 0).astype(np.uint8)
    anchor = np.mean(crops, axis=0).round().astype(np.uint8)
    folder = ROOT / "src/mabinogi_addon/detect/templates/autofind"
    image_io.imwrite(folder / "skillbar_anchor_uhd.png", anchor)
    image_io.imwrite(folder / "skillbar_mask_uhd.png", mask)
    print("skillbar_anchor_uhd.png", anchor.shape, "mask", int((mask > 0).sum()), "px")


if __name__ == "__main__":
    main()
