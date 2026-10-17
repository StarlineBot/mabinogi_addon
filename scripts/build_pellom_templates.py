"""Extract lossless detector samples from the 2026-10-18 live screenshots."""

from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io, paths
from mabinogi_addon.detect.boss_name_matcher import _binary
from mabinogi_addon.detect import boss_hp_reader as hp

ROOT = Path(__file__).resolve().parents[1]


def trim(binary):
    ys, xs = np.nonzero(binary)
    if not len(xs):
        raise ValueError("empty sample")
    return binary[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def build():
    frame = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 001801.png")
    if frame is None:
        raise ValueError("source screenshot missing")
    upper = frame[1246:1283, 1016:1537]
    lower = frame[1280:1317, 1016:1537]
    name = trim(_binary(upper[:, :312]))
    auxiliary = trim(_binary(lower[:, :312]))
    numeric = upper[:, int(upper.shape[1] * .58):]
    band = hp._bright_mask(numeric)[int(37 * hp._YBAND[0]):int(37 * hp._YBAND[1])]
    pitch = hp._PITCH * 37 / hp._REF_H
    right = round(numeric.shape[1] - hp._FIRST * 37 / hp._REF_H + 3)
    digit = trim(band[:, round(right - pitch):right])
    assets = {
        "boss/pellom/name_live_20261018.png": name,
        "boss_auxiliary/erg.png": auxiliary,
        "boss_hp_digits/bright_d8_0.png": digit,
    }
    for relative, sample in assets.items():
        target = paths.resource_dir() / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not image_io.imwrite(target, sample):
            raise OSError(f"cannot save {target}")
        print(relative, sample.shape, int(np.count_nonzero(sample)))


if __name__ == "__main__":
    build()
