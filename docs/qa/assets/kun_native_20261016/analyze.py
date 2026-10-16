"""Reproduce native Kun icon references without replacing product assets."""

import json
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.detect.icon_matcher import match_icon
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(__file__).resolve().parent
NAME = "쿤"
SOURCE = "tests/data/스크린샷 2026-10-16 213335.png"
BOXES = {"boss": (1023, 1212, 16, 16), "center": (1366, 379, 16, 16)}


def main():
    frame = image_io.imread(ROOT / SOURCE)
    template = image_io.imread(ROOT / "src/mabinogi_addon/assets/debuff/icon" / f"{NAME}.png")
    assert frame is not None and frame.shape == (1436, 2556, 3)
    assert template is not None
    engine = DebuffEngine({NAME: template}, [NAME])
    variant = engine._variants[NAME][0]
    crops, scores, runtime = {}, {}, {}
    for key, (x, y, w, h) in BOXES.items():
        crop = frame[y:y+h, x:x+w].copy()
        assert crop.shape == variant.shape == (16, 16, 3)
        crops[key] = crop
        scores[key] = match_icon(crop, variant).score
        assert scores[key] >= engine.detect_threshold_for(NAME)
        assert image_io.imwrite(OUTPUT / f"{key}.png", crop)
    for mode in ("off", "auto"):
        engine = DebuffEngine({NAME: template}, [NAME], gate_mode=mode)
        for index in range(8):
            engine.tick(frame[1195:1283, 1016:1537], index * .1)
        assert engine._matched[NAME] is True and engine._shown[NAME] is False
        runtime[mode] = {"matched": engine._matched[NAME], "missing_overlay_shown": engine._shown[NAME]}
    metrics = {
        "source": SOURCE,
        "source_git_blob": "1de6717c568cbcb9a90f21bb40c8a4940b1bca18",
        "native_boxes_xywh": BOXES,
        "existing_template_scores": scores,
        "runtime": runtime,
        "scope": "Two locations in one screenshot, not broad accuracy or replacement approval.",
    }
    (OUTPUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    comparison = np.hstack([cv2.resize(crop, (128, 128), interpolation=cv2.INTER_NEAREST)
                            for crop in (variant, crops["boss"], crops["center"])])
    assert image_io.imwrite(OUTPUT / "comparison.png", comparison)


if __name__ == "__main__":
    main()
