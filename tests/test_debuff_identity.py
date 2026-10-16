import json
from pathlib import Path

import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[1]
PAIR = ("프라가라흐(마법)", "프라가라흐(물리)")
ASSETS = ROOT / "docs/qa/assets/debuff_native_20261016/candidates"


@pytest.fixture(params=["bundled", "native"])
def library(request):
    directory = (ROOT / "src/mabinogi_addon/assets/debuff/icon"
                 if request.param == "bundled" else ASSETS)
    templates = {bid: image_io.imread(directory / f"{bid}.png") for bid in PAIR}
    assert all(image is not None for image in templates.values())
    return templates


def run(engine, frame, start=0):
    for index in range(12):
        result = engine.tick(frame, now=start + index * .15)
    return {entry.buff_id for entry in result.entries}


@pytest.mark.parametrize("mode", ["off", "band", "percent"])
@pytest.mark.parametrize("padding", [0, 7])
@pytest.mark.parametrize("actual", PAIR)
def test_single_real_icon_does_not_hide_the_other_identity(library, actual, padding, mode):
    pixels = image_io.imread(ASSETS / f"{actual}.png")
    frame = np.pad(pixels, ((padding, padding), (padding, padding), (0, 0)))
    engine = DebuffEngine(library, list(PAIR), gate_mode=mode)
    assert run(engine, frame) == set(PAIR) - {actual}


def test_both_real_identities_at_different_positions_remain_detected(library):
    icons = [image_io.imread(ASSETS / f"{bid}.png") for bid in PAIR]
    frame = np.concatenate([icons[0], np.zeros((16, 2, 3), np.uint8), icons[1]], axis=1)
    engine = DebuffEngine(library, list(PAIR))
    assert run(engine, frame) == set()


def test_identity_change_releases_old_latch_and_empty_frame_restores_both(library):
    engine = DebuffEngine(library, list(PAIR))
    for index, actual in enumerate((*PAIR, PAIR[0])):
        pixels = image_io.imread(ASSETS / f"{actual}.png")
        assert run(engine, pixels, start=index * 2) == set(PAIR) - {actual}
    assert run(engine, np.zeros((16, 16, 3), np.uint8), start=6) == set(PAIR)


def test_identical_custom_templates_do_not_claim_two_identities(library):
    pixels = image_io.imread(ASSETS / f"{PAIR[0]}.png")
    engine = DebuffEngine({bid: pixels.copy() for bid in PAIR}, list(PAIR))
    assert run(engine, pixels) == set(PAIR)


def test_unregistered_peer_does_not_disable_a_single_template(library):
    for actual in PAIR:
        engine = DebuffEngine({actual: library[actual]}, [actual])
        pixels = image_io.imread(ASSETS / f"{actual}.png")
        assert run(engine, pixels) == set()


def test_annotated_original_scenes_and_single_slots_keep_identities(library):
    manifest = json.loads((ASSETS.parent / "manifest.json").read_text(encoding="utf-8"))
    names = {"D13": PAIR[0], "D14": PAIR[1]}
    checked = 0
    for scene in manifest["scenes"]:
        if not set(names).intersection(scene["labels"]):
            continue
        frame = image_io.imread(ROOT / scene["source"])
        x, y = scene["row_xy"]
        width = (len(scene["labels"]) - 1) * scene["stride"] + 16
        row = frame[y:y + 16, x:x + width]
        expected = set(PAIR) - {names[label] for label in scene["labels"] if label in names}
        assert run(DebuffEngine(library, list(PAIR)), row) == expected, scene["id"]
        for slot, label in enumerate(scene["labels"]):
            if label not in names:
                continue
            sx = x + slot * scene["stride"]
            patch = frame[y:y + 16, sx:sx + 16]
            assert run(DebuffEngine(library, list(PAIR)), patch) == set(PAIR) - {names[label]}, (
                scene["id"], slot, label)
            checked += 1
    assert checked > 2


def test_identity_verification_has_bounded_color_work(library, monkeypatch):
    from mabinogi_addon.tracker import debuff_engine as module

    pixels = image_io.imread(ASSETS / f"{PAIR[0]}.png")
    frame = np.pad(pixels, ((7, 7), (7, 7), (0, 0)))
    original = module.match_icon
    calls = []
    def record(region, template):
        calls.append(region.shape)
        return original(region, template)
    monkeypatch.setattr(module, "match_icon", record)
    engine = DebuffEngine(library, list(PAIR))
    engine.tick(frame, 0)
    assert 0 < len(calls) <= len(PAIR) * 4 * 2
    assert all(shape == (16, 16, 3) for shape in calls)
