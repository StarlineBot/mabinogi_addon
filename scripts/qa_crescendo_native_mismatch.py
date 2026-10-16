"""Unresolved Crescendo detection mismatch. Explicit pytest entry point."""

from pathlib import Path

import pytest

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[1]
NAMES = ("크레센도", "불협화음")


def engine(mode):
    templates = {name: image_io.imread(ROOT / "src/mabinogi_addon/assets/debuff/icon" / f"{name}.png")
                 for name in NAMES}
    assert all(value is not None for value in templates.values())
    return DebuffEngine(templates, list(NAMES), gate_mode=mode)


def source():
    image = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-16 214902.png")
    assert image is not None and image.shape == (1440, 2560, 3)
    return image


@pytest.mark.parametrize("mode", ("off", "auto"))
@pytest.mark.parametrize("sample", ("new-slot-5", "new-full-roi", "old-U04-2"))
def test_reported_crescendo_icon_must_confirm_application(mode, sample):
    image = source()
    if sample == "new-slot-5":
        frame = image[1214:1230, 1079:1095]
    elif sample == "new-full-roi":
        frame = image[1195:1283, 1016:1537]
    else:
        frame = image_io.imread(ROOT / "docs/qa/assets/debuff_native_20261016/references/U04.png")
        assert frame is not None
    runtime = engine(mode)
    for index in range(8):
        runtime.tick(frame, index * .15)
    assert runtime._matched["크레센도"] is True, runtime.best_scores(frame)
    assert runtime._shown["크레센도"] is False


@pytest.mark.parametrize("mode", ("off", "auto"))
@pytest.mark.parametrize("sample", ("new-5", "old-2"))
def test_dissonance_counter_controls_still_confirm_application(mode, sample):
    if sample == "new-5":
        frame = source()[1214:1230, 1061:1077]
    else:
        frame = image_io.imread(ROOT / "docs/qa/assets/debuff_native_20261016/references/R02.png")
        assert frame is not None
    runtime = engine(mode)
    for index in range(8):
        runtime.tick(frame, index * .15)
    assert runtime._matched["불협화음"] is True
    assert runtime._shown["불협화음"] is False
    assert runtime._shown["크레센도"] is True
