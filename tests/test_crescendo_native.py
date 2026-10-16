"""Native music icons, negative slots and catalog override compatibility."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from mabinogi_addon import catalog, image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine
from scripts.qa_crescendo_native_mismatch import (
    test_dissonance_counter_controls_still_confirm_application,
    test_reported_crescendo_icon_must_confirm_application,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/qa/assets/debuff_native_20261016"
MUSIC = ("크레센도", "불협화음")
MANIFEST = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))


def templates():
    return catalog.build_templates(catalog.load_debuff_catalog(
        icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR,)))


@pytest.mark.parametrize("scene", [scene for scene in MANIFEST["scenes"]
                                  if any(label.startswith("D") for label in scene["labels"])],
                         ids=lambda scene: scene["id"])
def test_crescendo_does_not_match_other_identified_native_slots(scene):
    frame = image_io.imread(ROOT / scene["source"])
    assert frame is not None
    runtime = DebuffEngine(templates(), list(MUSIC))
    x, y = scene["row_xy"]
    for index, label in enumerate(scene["labels"]):
        # Uxx labels are unconfirmed identities, not negative ground truth.
        if not label.startswith("D") or label == "D12":
            continue
        left = x + index * scene["stride"]
        patch = frame[y:y + 16, left:left + 16]
        assert patch.shape == (16, 16, 3)
        score = runtime.best_scores(patch)["크레센도"]
        assert score < runtime.detect_threshold_for("크레센도"), (scene["id"], label, score)


def test_native_template_and_display_are_separate():
    entries = {item.id: item for item in catalog.load_debuff_catalog(
        icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR,))}
    item = entries["크레센도"]
    candidate = ROOT / "docs/qa/assets/music_native_20261016/crescendo.png"
    assert item.match_icon.read_bytes() == candidate.read_bytes()
    assert np.array_equal(image_io.imread(item.match_icon), image_io.imread(candidate))
    assert image_io.imread(item.match_icon).shape == (16, 16, 3)
    assert item.display_image is not None
    assert image_io.imread(item.display_image).shape == (28, 28, 3)
    # Preserve the exact old PNG, including its encoding, rather than upscaling the crop.
    raw = item.display_image.read_bytes()
    header = f"blob {len(raw)}\0".encode()
    assert hashlib.sha1(header + raw).hexdigest() == "4897f486059403742327ef754104862d7254b7ba"
    assert entries["불협화음"].display_image is None


def test_user_icon_override_keeps_own_match_and_display(tmp_path):
    directory = tmp_path / "사용자 아이콘"
    directory.mkdir()
    user = directory / "크레센도.png"
    pixels = np.full((20, 20, 3), (10, 70, 150), np.uint8)
    assert image_io.imwrite(user, pixels)
    before = user.read_bytes()
    entries = {item.id: item for item in catalog.load_debuff_catalog(
        icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR, directory))}
    assert entries["크레센도"].match_icon == user
    assert entries["크레센도"].display_image is None
    assert np.array_equal(catalog.build_templates([entries["크레센도"]])["크레센도"], pixels)
    assert user.read_bytes() == before
