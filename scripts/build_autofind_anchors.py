"""Build masked UI anchors from the documented full-screen reference."""

from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-10 190116.png")
    assert source is not None
    target = ROOT / "src/mabinogi_addon/detect/templates/autofind"
    target.mkdir(parents=True, exist_ok=True)
    anchor = source[875:932, 708:782].copy()
    yy, xx = np.indices(anchor.shape[:2])
    radius = np.hypot(xx - 22, yy - 28)
    mask = np.where((radius >= 15) & (radius <= 24), 255, 0).astype(np.uint8)
    for polygon in (
        [(18, 10), (22, 0), (26, 10)],
        [(18, 46), (22, 56), (26, 46)],
        [(6, 18), (0, 13), (10, 15)],
        [(34, 15), (44, 13), (38, 21)],
        [(6, 37), (0, 44), (12, 41)],
        [(32, 41), (44, 44), (38, 35)],
    ):
        cv2.fillPoly(mask, [np.array(polygon, np.int32)], 255)
    mask[33:46, 47:71] = 255
    controls = source[24:93, 1184:1223].copy()
    controls_mask = np.zeros(controls.shape[:2], np.uint8)
    for y in (0, 49):
        controls_mask[y:y + 18] = 255
        controls_mask[y + 4:y + 14, 13:25] = 0
        controls_mask[y:y + 18, :2] = 0
        controls_mask[y:y + 18, 37:] = 0
    for name, pixels in (("tuarim_anchor", anchor), ("tuarim_mask", mask),
                         ("skillbar_anchor", controls), ("skillbar_mask", controls_mask)):
        assert image_io.imwrite(target / f"{name}.png", pixels)
    reference = image_io.imread(ROOT / "tests/data/tuarim_hi/95.png")
    assert reference is not None
    assert image_io.imwrite(target.parent / "tuarim/percent.png", reference.max(axis=2)[:, -10:])
    plain = image_io.imread(ROOT / "tests/data/tuarim_samples/00.png")
    assert plain is not None
    assert image_io.imwrite(target.parent / "tuarim/percent_plain.png", plain.max(axis=2)[:, -10:])


if __name__ == "__main__":
    main()
