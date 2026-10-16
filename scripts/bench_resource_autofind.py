"""Offline whole-frame locator cost, not a game/FPS or long-running leak test."""

from pathlib import Path
from time import monotonic, process_time

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector


def main():
    cv2.setNumThreads(1)
    data = Path(__file__).resolve().parents[1] / "tests/data"
    cases = {"new-98":image_io.imread(data / "스크린샷 2026-10-17 012459.png"),
             "old-100":image_io.imread(data / "스크린샷 2026-10-09 185117.png"),
             "blank":np.zeros((1440,2560,3),np.uint8)}
    for feature in ("tuarim","dorcha"):
        assets = detector_assets(feature)
        for name,frame in cases.items():
            assert frame is not None
            wall,cpu = monotonic(),process_time()
            result = run_detector(feature,frame,assets,{})
            print(f"{feature} {name}: {result}, wall={monotonic()-wall:.3f}s CPU={process_time()-cpu:.3f}s")
    try:
        import resource
        print(f"Peak RSS (platform units): {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}")
    except ImportError:
        print("Peak RSS unavailable on this platform")


if __name__ == "__main__":
    main()
