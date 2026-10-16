"""Build the additional native ornament; never alter the QA source PNG."""

from pathlib import Path
import hashlib

import cv2

from mabinogi_addon import image_io


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "tests/data/스크린샷 2026-10-16 234015.png"
    raw = source.read_bytes()
    assert hashlib.sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest() == "fafa4d8bd995c6e2c0b476ca70e73b3b23a158a4"
    frame = image_io.imread(source)
    assert frame is not None and frame.shape == (1440, 2560, 3)
    crop = cv2.cvtColor(frame[106:163, 569:614], cv2.COLOR_BGR2GRAY)
    target = ROOT / "src/mabinogi_addon/detect/templates/autofind/dorcha_anchor_alt.png"
    assert image_io.imwrite(target, crop)


if __name__ == "__main__":
    main()
