"""Extract the native thin tens digit; preserve the uploaded original."""

import hashlib
from pathlib import Path

from mabinogi_addon import image_io


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "tests/data/스크린샷 2026-10-18 124011.png"
    raw = source.read_bytes()
    assert hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == "b84671f9b09008202e58878607be7cd8de1f238f"
    frame = image_io.imread(source)
    assert frame is not None and frame.shape == (1440,2560,3)
    cell = frame[86:99,1274:1282].max(axis=2)
    assert cell.shape == (13,8)
    assert image_io.imwrite(ROOT / "src/mabinogi_addon/detect/templates/tuarim/thin_one.png", cell)


if __name__ == "__main__":
    main()
