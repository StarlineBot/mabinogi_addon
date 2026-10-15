"""실제 PNG의 영역 경계, 원본 픽셀 및 배경 오탐 회귀."""

from itertools import product
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[1]
MAGIC = "마법 방어력 보호 감소"
FRAGARACH = "프라가라흐(마법)"
IDS = (MAGIC, FRAGARACH)
BOX = (1016, 1195, 521, 88)


@pytest.fixture(scope="module")
def templates():
    directory = ROOT / "src/mabinogi_addon/assets/debuff/icon"
    result = {path.stem: image_io.imread(path) for path in directory.glob("*.png")}
    assert set(IDS) <= result.keys()
    assert all(value is not None for value in result.values())
    return result


@pytest.fixture(scope="module", params=["213313", "213734"])
def scene_name(request):
    return request.param


@pytest.fixture(scope="module")
def scene(scene_name):
    frame = image_io.imread(ROOT / "tests/data" / f"스크린샷 2026-10-15 {scene_name}.png")
    assert frame is not None and frame.shape == (1436, 2556, 3)
    return frame


def crop(frame, x, y, w, h):
    return frame[y:y + h, x:x + w]


def test_complete_icon_scores_are_stable_across_roi_grid(scene, templates):
    engine = DebuffEngine({key: templates[key] for key in IDS}, list(IDS))
    reference = engine.best_scores(crop(scene, *BOX))
    for dx, dy, (dw, dh) in product(range(-3, 4), range(-3, 4),
                                  [(0, 0), (-1, -1), (1, 1), (-3, 2), (3, -2)]):
        x, y, w, h = BOX
        region = crop(scene, x + dx, y + dy, w + dw, h + dh)
        assert np.array_equal(region[17 - dy:35 - dy, 7 - dx:177 - dx],
                              crop(scene, *BOX)[17:35, 7:177])
        scores = engine.best_scores(region)
        for key in IDS:
            assert scores[key] >= engine.detect_threshold_for(key) == 0.68
            assert scores[key] == pytest.approx(reference[key], abs=1e-5)


@pytest.mark.parametrize("mode", ["off", "band", "percent"])
def test_original_regions_start_detected_in_every_gate_mode(scene, templates, mode):
    engine = DebuffEngine({key: templates[key] for key in IDS}, list(IDS), gate_mode=mode)
    region = crop(scene, *BOX)
    for index in range(12):
        result = engine.tick(region, now=index * 0.15, bar_region=crop(scene, 1016, 1246, 521, 37))
    assert not result.entries and not result.alerts


@pytest.mark.parametrize("name", ["스크린샷 2026-10-06 223724.png", "스크린샷 2026-10-06 224732.png",
                                  "스크린샷 2026-10-12 024008.png", "스크린샷 2026-10-12 024144.png"])
def test_no_boss_background_never_matches_any_bundled_icon(name, templates):
    frame = image_io.imread(ROOT / "tests/data" / name)
    assert frame is not None
    h, w = frame.shape[:2]
    region = crop(frame, int(1017 * w / 2560), int(1210 * h / 1440),
                  int(524 * w / 2560), int(79 * h / 1440))
    engine = DebuffEngine(templates, list(templates))
    scores = engine.best_scores(region)
    assert not {key: score for key, score in scores.items() if score >= engine.detect_threshold_for(key)}


def test_gray_candidates_are_verified_in_color():
    pattern = (np.indices((16, 16)).sum(axis=0) % 2).astype(np.uint8)
    blue = np.zeros((16, 16, 3), np.uint8)
    blue[:, :, 0] = pattern * 255
    red = np.zeros_like(blue)
    red[:, :, 2] = pattern * 97
    engine = DebuffEngine({"blue": blue}, ["blue"])
    assert engine.best_scores(red)["blue"] < engine.detect_threshold_for("blue")
    assert engine.best_scores(blue)["blue"] == pytest.approx(1.0)


@pytest.mark.parametrize("key, other, offsets", [
    (MAGIC, "물리 방어력 보호 감소", (7, 7)),
    (FRAGARACH, "프라가라흐(물리)", (133, 151)),
    ("프라가라흐(물리)", FRAGARACH, (115, 133)),
])
def test_real_magic_and_physical_icon_color_separation(scene, scene_name, templates, key, other, offsets):
    offset = offsets[0 if scene_name == "213313" else 1]
    region = crop(scene, BOX[0] + offset, BOX[1] + 17, 16, 16)
    engine = DebuffEngine({bid: templates[bid] for bid in (key, other)}, [key, other])
    scores = engine.best_scores(region)
    assert scores[key] >= engine.detect_threshold_for(key)
    assert scores[key] - scores[other] >= 0.1


def test_capture_pixels_are_not_resized_for_matching(scene, templates, monkeypatch):
    engine = DebuffEngine({key: templates[key] for key in IDS}, list(IDS))
    region = crop(scene, *BOX)
    assert engine._scale(region) is region
    monkeypatch.setattr(cv2, "resize", lambda *args, **kwargs: pytest.fail("capture pixels resized"))
    assert all(score >= 0.68 for score in engine.best_scores(region).values())


def test_color_verification_candidate_count_is_bounded(scene, templates, monkeypatch):
    from mabinogi_addon.tracker import debuff_engine as module

    engine = DebuffEngine({key: templates[key] for key in IDS}, list(IDS))
    original = module.match_icon
    calls = []
    def record(region, template):
        calls.append(region.shape)
        return original(region, template)
    monkeypatch.setattr(module, "match_icon", record)
    engine.best_scores(crop(scene, *BOX))
    assert 0 < len(calls) <= len(IDS) * 4
    assert all(shape[:2] == (16, 16) for shape in calls)
