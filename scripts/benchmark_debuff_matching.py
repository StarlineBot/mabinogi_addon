"""동일 PNG/템플릿/단일 OpenCV 스레드로 과거와 현재 판독 틱 비용을 비교한다."""

import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine
from test_support.debuff_baseline import LegacyScaledEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    cv2.setNumThreads(1)
    root = Path(__file__).resolve().parents[1]
    directory = root / "src/mabinogi_addon/assets/debuff/icon"
    templates = {path.stem: image_io.imread(path) for path in sorted(directory.glob("*.png"))}
    for shot in ("213313", "213734"):
        frame = image_io.imread(root / "tests/data" / f"스크린샷 2026-10-15 {shot}.png")
        assert frame is not None and all(value is not None for value in templates.values())
        region = frame[1195:1283, 1016:1537]
        for count in (2, 8, len(templates)):
            keys = ["마법 방어력 보호 감소", "프라가라흐(마법)"]
            keys += [key for key in templates if key not in keys]
            keys = keys[:count]
            for engine_class in (LegacyScaledEngine, DebuffEngine):
                engine = engine_class({key: templates[key] for key in keys}, keys)
                samples = []
                for index in range(args.iterations + 5):
                    start = time.perf_counter()
                    engine.tick(region, now=index * 0.15)
                    elapsed = (time.perf_counter() - start) * 1000
                    if index >= 5:
                        samples.append(elapsed)
                print(json.dumps({"scene": shot, "icons": count, "engine": engine_class.__name__,
                                  "iterations": args.iterations, "median_ms": round(float(np.median(samples)), 3),
                                  "p95_ms": round(float(np.percentile(samples, 95)), 3)}), flush=True)


if __name__ == "__main__":
    main()
