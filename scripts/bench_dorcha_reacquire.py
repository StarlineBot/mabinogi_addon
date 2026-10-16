"""Offline detector cost only; not a Windows game/CPU impact benchmark."""

from pathlib import Path
from time import monotonic, process_time

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha


def main():
    cv2.setNumThreads(1)
    data = Path(__file__).resolve().parents[1] / "tests/data"
    frames = {stamp: image_io.imread(data / f"스크린샷 2026-10-16 {stamp}.png")
              for stamp in ("211914","234015")}
    frames["missing-ui"] = np.zeros((1440,2560,3),np.uint8)
    for name, frame in frames.items():
        assert frame is not None
        wall, cpu = monotonic(), process_time()
        result = locate_dorcha(frame)
        wall, cpu = monotonic()-wall, process_time()-cpu
        print(f"{name}: result={result}, wall={wall:.3f}s, CPU={cpu:.3f}s, cost-cooldown={wall*20:.3f}s")


if __name__ == "__main__":
    main()
