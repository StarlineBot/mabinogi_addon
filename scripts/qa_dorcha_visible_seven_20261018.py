"""The uploaded seven is readable but its ornament is rejected in v0.4.87."""

from pathlib import Path
import sys

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_dorcha_tracking import moving  # noqa: E402,F401
from mabinogi_addon import image_io  # noqa: E402
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha  # noqa: E402
from mabinogi_addon.detect.dorcha_reader import read_dorcha  # noqa: E402

BOX = (1237, 55, 28, 23)


@pytest.fixture(autouse=True)
def one_thread():
    count = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(count)


@pytest.fixture
def original():
    frame = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 122605.png")
    assert frame is not None and frame.shape == (1436, 2556, 3)
    return frame


def test_the_exact_numeric_roi_reads_seven(original):
    x, y, w, h = BOX
    trace = {}
    assert read_dorcha(original[y:y+h, x:x+w], diagnostics=trace) == 7
    assert trace["score"] > 0.99


def test_visible_seven_is_found_in_the_original_frame(original):
    trace = {}
    found = locate_dorcha(original, diagnostics=trace)
    assert found == BOX, {"found": found, "reason": trace.get("rejection"),
                          "accept": trace.get("accept_score")}


def test_correct_saved_region_is_revalidated_by_the_actual_controller(moving, original):
    _, tab, state, writes = moving
    state.frame = original
    state.target = (1, 2, 0, 0, original.shape[1], original.shape[0])
    tab._region = dict(zip(("x", "y", "w", "h"), BOX))
    assert tab._verify_registered_region(BOX, state.target) == BOX
    assert not writes
