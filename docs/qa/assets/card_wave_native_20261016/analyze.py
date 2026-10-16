"""Validate the new card/wave scenes and preserve native reference crops."""

import json
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(__file__).resolve().parent
NAMES = ("방해 카드", "붕괴의 파동")
SOURCES = {
    "213733": "863ce53400b060e421e227c709e2d9aba5586cac",
    "213830": "8194b92c120fb93e52bffe1cf1ca31c037e04c86",
}
CROPS = {
    "card": ("213733", NAMES[0], 1113, 1212),
    "wave_multi": ("213733", NAMES[1], 1077, 1212),
    "wave_solo": ("213830", NAMES[1], 1023, 1212),
}


def main():
    templates = {name: image_io.imread(ROOT / "src/mabinogi_addon/assets/debuff/icon" / f"{name}.png")
                 for name in NAMES}
    assert all(image is not None for image in templates.values())
    frames, metrics = {}, {"sources": SOURCES, "roi_xywh": [1016, 1195, 521, 88], "scenes": {}}
    for scene in SOURCES:
        frame = image_io.imread(ROOT / "tests/data" / f"스크린샷 2026-10-16 {scene}.png")
        assert frame is not None and frame.shape == (1436, 2556, 3)
        frames[scene] = frame
        roi = frame[1195:1283, 1016:1537]
        entry = {}
        expected = {name: scene == "213733" or name == NAMES[1] for name in NAMES}
        for mode in ("off", "auto"):
            engine = DebuffEngine(templates, list(NAMES), gate_mode=mode)
            for index in range(8):
                engine.tick(roi, index * .15)
            assert engine._matched == expected
            assert engine._shown == {name: not present for name, present in expected.items()}
            entry[mode] = {"scores": engine.best_scores(roi), "matched": engine._matched,
                           "missing_overlay_shown": engine._shown}
        metrics["scenes"][scene] = entry
    preview = []
    engine = DebuffEngine(templates, list(NAMES))
    metrics["crops"] = {}
    for key, (scene, name, x, y) in CROPS.items():
        crop = frames[scene][y:y+16, x:x+16].copy()
        assert image_io.imwrite(OUTPUT / f"{key}.png", crop)
        metrics["crops"][key] = {"scene": scene, "name": name, "xywh": [x, y, 16, 16]}
        pair = np.hstack([engine._variants[name][0], crop])
        preview.append(cv2.resize(pair, (256, 128), interpolation=cv2.INTER_NEAREST))
    assert image_io.imwrite(OUTPUT / "comparison.png", np.vstack(preview))
    metrics["scope"] = "Two positive scenes and one card-absent control, not overall accuracy."
    (OUTPUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
