"""Rebuild or verify QA-only native debuff crops; never replace product assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


DATA = Path(__file__).resolve().parent
ROOT = DATA.parents[3]


def blob_sha(path):
    raw = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def correlation(image, template):
    return float(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)[0, 0])


def label(canvas, text, x, y):
    cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                .45, (15, 15, 15), 1, cv2.LINE_AA)


def rounded(mapping):
    return {key: round(value, 6) for key, value in mapping.items()}


def close_json(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(close_json(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(close_json(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and isinstance(right, (int, float)):
        return bool(np.isclose(left, right, atol=2e-5, rtol=0))
    return left == right


def build(write=False):
    cv2.setNumThreads(1)
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["baseline_blobs"]:
        assert blob_sha(ROOT / entry["path"]) == entry["sha"], entry["path"]
    frames = {}

    def frame(path):
        if path not in frames:
            frames[path] = image_io.imread(ROOT / path)
            assert frames[path] is not None, path
        return frames[path]

    scenes = {scene["id"]: scene for scene in manifest["scenes"]}

    def crop(scene_id, slot):
        scene = scenes[scene_id]
        assert 0 <= slot < len(scene["labels"])
        x, y = scene["row_xy"]
        x += scene["stride"] * slot
        result = frame(scene["source"])[y:y+16, x:x+16].copy()
        assert result.shape == (16, 16, 3)
        return result, [x, y, 16, 16]

    catalog = {entry["id"]: entry for entry in manifest["icons"]}
    original = {key: image_io.imread(ROOT / entry["path"]) for key, entry in catalog.items()}
    assert all(value is not None for value in original.values())
    old_engine = DebuffEngine(original, list(original))
    replacement = dict(original)
    artifacts = {}
    records = []
    for entry in manifest["candidates"] + manifest["references"]:
        pixels, box = crop(entry["scene"], entry["slot"])
        artifacts[entry["output"]] = pixels
        if entry in manifest["candidates"]:
            replacement[entry["id"]] = pixels
        records.append({"id": entry["id"], "output": entry["output"],
                        "source": scenes[entry["scene"]]["source"], "xywh": box,
                        "status": entry["status"],
                        "pixel_sha256_bgr": hashlib.sha256(pixels.tobytes()).hexdigest()})
    new_engine = DebuffEngine(replacement, list(replacement))
    ids = [entry["id"] for entry in manifest["candidates"]]
    slots = []
    for scene in scenes.values():
        for slot, identity in enumerate(scene["labels"]):
            pixels, box = crop(scene["id"], slot)
            old = {key: correlation(pixels, old_engine._variants[key][0]) for key in ids}
            new = {key: correlation(pixels, new_engine._variants[key][0]) for key in ids}
            slots.append({"scene": scene["id"], "slot": slot, "label": identity,
                          "xywh": box, "old": rounded(old), "native": rounded(new),
                          "pixel_sha256_bgr": hashlib.sha256(pixels.tobytes()).hexdigest()})
    summary = []
    for entry in manifest["candidates"]:
        key = entry["id"]
        positives = [item for item in slots if item["label"] == key]
        holdout = [item for item in positives if item["scene"] != entry["scene"]]
        other = [item for item in slots if item["label"] in ids and item["label"] != key]
        threshold = old_engine.detect_threshold_for(catalog[key]["name"])
        source_pixels = artifacts[entry["output"]]
        source_hash = hashlib.sha256(source_pixels.tobytes()).hexdigest()
        summary.append({
            "id": key, "name": entry["name"], "detect_threshold": threshold,
            "positive_slots": len(positives), "other_scene_slots": len(holdout),
            "other_scene_distinct_non_source_pixels": len({p["pixel_sha256_bgr"] for p in holdout if p["pixel_sha256_bgr"] != source_hash}),
            "source_old_score": round(correlation(source_pixels, old_engine._variants[key][0]), 6),
            "source_native_score": round(correlation(source_pixels, new_engine._variants[key][0]), 6),
            "holdout_old_min": min((p["old"][key] for p in holdout), default=None),
            "holdout_native_min": min((p["native"][key] for p in holdout), default=None),
            "old_cross_identity_hits": [{"scene": p["scene"], "slot": p["slot"], "label": p["label"], "score": p["old"][key]} for p in other if p["old"][key] >= threshold],
            "native_cross_identity_hits": [{"scene": p["scene"], "slot": p["slot"], "label": p["label"], "score": p["native"][key]} for p in other if p["native"][key] >= threshold],
        })
    regions = []
    for scene in scenes.values():
        pixels = frame(scene["source"])[1195:1283, 1000:1570]
        old = old_engine.best_scores(pixels)
        new = new_engine.best_scores(pixels)
        regions.append({"scene": scene["id"], "xywh": [1000, 1195, 570, 88],
                        "old": rounded({key: old[key] for key in ids}),
                        "native": rounded({key: new[key] for key in ids})})
    negatives = []
    for path in manifest["negative_sources"]:
        pixels = frame(path)[1195:1283, 1000:1570]
        old = old_engine.best_scores(pixels)
        new = new_engine.best_scores(pixels)
        negatives.append({"source": path, "xywh": [1000, 1195, 570, 88],
                          "old": rounded({key: old[key] for key in ids}),
                          "native": rounded({key: new[key] for key in ids})})

    identity_repro = []
    pair = ("D13", "D14")
    for actual, slot in (("D13", 7), ("D14", 6)):
        pixels, box = crop("S35", slot)
        for mode, library in (("old", original), ("native", replacement)):
            templates = {catalog[key]["name"]: library[key] for key in pair}
            engine = DebuffEngine(templates, list(templates), gate_mode="off")
            for tick in range(8):
                result = engine.tick(pixels, now=tick * .15)
            identity_repro.append({
                "mode": mode, "source": scenes["S35"]["source"], "xywh": box,
                "actual_icon": catalog[actual]["name"],
                "expected_missing": [catalog[key]["name"] for key in pair if key != actual],
                "observed_missing": [entry.buff_id for entry in result.entries],
                "scores": rounded(engine.best_scores(pixels)),
            })

    for group in ("candidates", "references"):
        entries = manifest[group]
        preview = np.full((((len(entries)+5)//6)*145, 6*160, 3), 245, np.uint8)
        for number, entry in enumerate(entries):
            y, x = number//6*145, number%6*160
            label(preview, entry["id"], x+8, y+19)
            preview[y+27:y+123, x+8:x+104] = cv2.resize(
                artifacts[entry["output"]], (96, 96), interpolation=cv2.INTER_NEAREST)
        artifacts[f"{group}_preview.png"] = preview
    for page in range(2):
        entries = manifest["candidates"][page*7:page*7+7]
        preview = np.full((len(entries)*140+36, 900, 3), 245, np.uint8)
        for column, heading in enumerate(("Stored 28px", "Old matching 16px", "Native crop 16px", "Absolute difference")):
            label(preview, heading, column*220+12, 22)
        for number, entry in enumerate(entries):
            key, y = entry["id"], number*140+40
            pixels = artifacts[entry["output"]]
            images = (original[key], old_engine._variants[key][0], pixels,
                      cv2.absdiff(old_engine._variants[key][0], pixels))
            for column, image in enumerate(images):
                preview[y+20:y+116, column*220+12:column*220+108] = cv2.resize(
                    image, (96, 96), interpolation=cv2.INTER_NEAREST)
            label(preview, key, 12, y+13)
        artifacts[f"comparison_{page+1}.png"] = preview

    metrics = {"baseline_main": manifest["baseline_main"],
               "scanned_screenshots": len(manifest["scanned_sources"]),
               "verified_baseline_blobs": len(manifest["baseline_blobs"]),
               "candidate_count": len(ids), "reference_count": len(manifest["references"]),
               "annotated_scenes": len(scenes), "annotated_slots": len(slots),
               "crops": records, "summary": summary, "slot_scores": slots,
               "full_roi_scores": regions, "background_scores": negatives,
               "identity_repro": identity_repro}
    for relative, pixels in artifacts.items():
        path = DATA / relative
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            ok, encoded = cv2.imencode(".png", pixels, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            assert ok, path
            path.write_bytes(encoded.tobytes())
        else:
            stored = image_io.imread(path)
            assert stored is not None and np.array_equal(stored, pixels), path
    metrics_path = DATA / "metrics.json"
    if write:
        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        assert close_json(json.loads(metrics_path.read_text(encoding="utf-8")), metrics), metrics_path
    print(json.dumps({key: metrics[key] for key in (
        "scanned_screenshots", "verified_baseline_blobs", "candidate_count",
        "reference_count", "annotated_scenes", "annotated_slots")}, ensure_ascii=False))
    for item in summary:
        print(item["id"], item["name"], "old/new holdout min:",
              item["holdout_old_min"], item["holdout_native_min"],
              "cross-identity hits:", len(item["old_cross_identity_hits"]),
              len(item["native_cross_identity_hits"]))
    print("PASS: original pixels, source provenance and comparison artifacts verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    build(write=args.write)
