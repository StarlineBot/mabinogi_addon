"""Extract a masked ornament reference without changing the source PNG."""

import hashlib
from pathlib import Path

import cv2

from mabinogi_addon import image_io


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "tests/data/스크린샷 2026-10-18 122605.png"
    raw = source.read_bytes()
    assert hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == "c274ba02bf292f76b088657f72b11c02e7b7d5cb"
    frame = image_io.imread(source)
    assert frame is not None and frame.shape == (1436, 2556, 3)
    crop = cv2.cvtColor(frame[38:95, 1229:1274], cv2.COLOR_BGR2GRAY)
    target = ROOT / "src/mabinogi_addon/detect/templates/autofind/dorcha_anchor_seven.png"
    assert image_io.imwrite(target, crop)


if __name__ == "__main__":
    main()
