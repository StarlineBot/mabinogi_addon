"""Preserve music debuff evidence; candidate replacement is memory-only."""

import json
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.detect.icon_matcher import match_icon
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(__file__).resolve().parent
NAMES = ("불협화음", "크레센도")


def main():
    frame = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-16 214902.png")
    assert frame is not None and frame.shape == (1440, 2560, 3)
    templates = {name: image_io.imread(ROOT / "src/mabinogi_addon/assets/debuff/icon" / f"{name}.png")
                 for name in NAMES}
    engine = DebuffEngine(templates, list(NAMES))
    crops = {"dissonance": frame[1214:1230, 1061:1077].copy(),
             "crescendo": frame[1214:1230, 1079:1095].copy()}
    refs = {"dissonance": "R02", "crescendo": "U04"}
    metrics = {"source": "tests/data/스크린샷 2026-10-16 214902.png",
               "source_git_blob": "9755f8239fd29a9c1306a2df4fb230e704fed92b",
               "samples": {}, "runtime": {}, "candidate_probe": {}}
    preview = []
    for (key, crop), name in zip(crops.items(), NAMES):
        variant = engine._variants[name][0]
        old = image_io.imread(ROOT / "docs/qa/assets/debuff_native_20261016/references" / f"{refs[key]}.png")
        assert old is not None
        assert image_io.imwrite(OUTPUT / f"{key}.png", crop)
        metrics["samples"][key] = {
            "xywh": [1061 if key == "dissonance" else 1079, 1214, 16, 16],
            "current_to_new": match_icon(crop, variant).score,
            "current_to_old_counter": match_icon(old, variant).score,
            "new_to_old_counter": match_icon(old, crop).score,
            "current_to_new_top10_rows": match_icon(crop[:10], variant[:10]).score,
        }
        preview.append(np.hstack([variant, crop, old]))
    roi = frame[1195:1283, 1016:1537]
    for mode in ("off", "auto"):
        runtime = DebuffEngine(templates, list(NAMES), gate_mode=mode)
        for index in range(8):
            runtime.tick(roi, index * .15)
        metrics["runtime"][mode] = {"scores": runtime.best_scores(roi), "matched": runtime._matched,
                                    "missing_overlay_shown": runtime._shown}
        candidate = dict(templates)
        candidate["크레센도"] = crops["crescendo"]
        runtime = DebuffEngine(candidate, list(NAMES), gate_mode=mode)
        for index in range(8):
            runtime.tick(roi, index * .15)
        assert all(runtime._matched.values()) and not any(runtime._shown.values())
        metrics["candidate_probe"][mode] = {"matched": runtime._matched,
                                            "scope": "Same-source feasibility only, not accuracy proof."}
    comparison = cv2.resize(np.vstack(preview), (384, 256), interpolation=cv2.INTER_NEAREST)
    assert image_io.imwrite(OUTPUT / "comparison.png", comparison)
    (OUTPUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
