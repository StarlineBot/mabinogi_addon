"""Native 42x16 screenshot input must retain the visible tens digit."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from scripts.qa_tuarim_low_range_display import pipeline, sample, hundred  # noqa: E402,F401
from mabinogi_addon import image_io  # noqa: E402
from mabinogi_addon.detect.tuarim_reader import read_percent  # noqa: E402


@pytest.fixture
def nineteen():
    frame = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 124011.png")
    assert frame is not None and frame.shape == (1440, 2560, 3)
    # Coordinates are visible in the app's registration label in this screenshot.
    return frame[85:101, 1265:1307].copy()


def test_native_registered_nineteen_keeps_its_tens(nineteen):
    assert nineteen.shape == (16, 42, 3)
    assert read_percent(nineteen) == 19


def test_actual_reader_and_stabilizer_display_nineteen(pipeline, nineteen):
    pump, _ = pipeline
    result = pump(nineteen)
    assert result["raw"] == result["stable"] == result["overlay"] == 19, result


def test_prior_bright_scene_reads_the_same_nineteen():
    frame = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 122605.png")
    assert frame is not None and frame.shape == (1436, 2556, 3)
    assert read_percent(frame[83:99, 1263:1305]) == 19


@pytest.mark.parametrize("name, expected", [("v06_7466.png", 16), ("v18_197.png", 18)])
def test_prior_narrow_low_range_controls_still_read(name, expected):
    assert read_percent(sample(name)) == expected


def test_full_hundred_is_still_held_as_unreadable():
    assert read_percent(hundred()) is None
