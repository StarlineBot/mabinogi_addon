"""Reproduce native eye-icon evidence without changing product assets."""

import json
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.detect.icon_matcher import match_icon
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(__file__).resolve().parent
NAME = "이면을 보는 눈"
SOURCE = "tests/data/스크린샷 2026-10-16 210734.png"
BOXES = {"boss": (1043, 1214, 16, 16), "center": (1317, 475, 16, 16)}


def main():
    frame = image_io.imread(ROOT / SOURCE)
    template = image_io.imread(ROOT / "src/mabinogi_addon/assets/debuff/icon" / f"{NAME}.png")
    assert frame is not None and frame.shape == (1440, 2560, 3)
    assert template is not None
    engine = DebuffEngine({NAME: template}, [NAME])
    variant = engine._variants[NAME][0]
    crops = {}
    scores = {}
    for key, (x, y, w, h) in BOXES.items():
        crop = frame[y:y+h, x:x+w].copy()
        assert crop.shape == variant.shape == (16, 16, 3)
        crops[key] = crop
        scores[key] = match_icon(crop, variant).score
        assert scores[key] >= engine.detect_threshold_for(NAME)
        assert image_io.imwrite(OUTPUT / f"{key}.png", crop)
    metrics = {
        "source": SOURCE,
        "source_git_blob": "baec4d9cbbbb415a6e36927e136cc05a417c7cea",
        "native_boxes_xywh": BOXES,
        "registered_shape": list(template.shape),
        "runtime_variant_shape": list(variant.shape),
        "existing_template_scores": scores,
        "detect_threshold": engine.detect_threshold_for(NAME),
        "boss_center_score": match_icon(crops["center"], crops["boss"]).score,
        "same_pixels": bool(np.array_equal(crops["boss"], crops["center"])),
        "scope": "Two positions in one screenshot; not cross-scene accuracy or replacement approval.",
    }
    (OUTPUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    comparison = np.hstack([
        cv2.resize(crop, (128, 128), interpolation=cv2.INTER_NEAREST)
        for crop in (variant, crops["boss"], crops["center"])
    ])
    assert image_io.imwrite(OUTPUT / "comparison.png", comparison)


if __name__ == "__main__":
    main()
