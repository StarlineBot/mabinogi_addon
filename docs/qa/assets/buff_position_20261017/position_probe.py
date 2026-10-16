"""Independent one-shot Buff auto-find translation checks; no runtime following."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector


ROOT = Path(__file__).resolve().parents[4]
SOURCES = (
    ("스크린샷 2026-10-12 000512.png", 14, 871, 16),
    ("스크린샷 2026-10-09 190901.png", 16, 873, 16),
    ("스크린샷 2026-10-12 200511.png", 14, 967, 16),
    ("2026-10-11_111640.png", 3541, 919, 16),
    ("2026-10-11_123333.png", 208, 573, 15),
    ("스크린샷 2026-10-16 234015.png", 16, 849, 16),
    ("스크린샷 2026-10-17 012459.png", 16, 945, 16),
)


@pytest.fixture(scope="module", autouse=True)
def single_opencv_thread():
    before = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(before)


@pytest.fixture(scope="module")
def assets():
    return detector_assets("buff")


@pytest.mark.parametrize("name,sx,sy,size", SOURCES)
@pytest.mark.parametrize("position", range(8))
def test_refind_after_position_change(name, sx, sy, size, position, assets):
    frame = image_io.imread(str(ROOT / "tests" / "data" / name), cv2.IMREAD_COLOR)
    assert frame is not None, name
    height, width = frame.shape[:2]
    cx, cy = width // 2, height // 2
    destinations = (
        (cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1),
        (32, 600), (width - 320, 600),
        (32, height - 200), (width - 320, height - 200),
    )
    ex, ey = destinations[position]
    # Integer translation preserves native UI pixels; this is not a live capture.
    matrix = np.float32([[1, 0, ex - sx], [0, 1, ey - sy]])
    moved = cv2.warpAffine(frame, matrix, (width, height), flags=cv2.INTER_NEAREST)
    assert np.array_equal(moved[ey:ey + size, ex:ex + size],
                          frame[sy:sy + size, sx:sx + size])
    trace = {}
    result = run_detector("buff", moved, assets, trace)
    assert result is not None, (name, destinations[position], trace)
    best = trace["best"]
    assert (best["x"], best["y"], best["size"]) == (ex, ey, size), trace
    assert best["score"] >= 0.85, trace
    x, y, w, h = result
    assert 0 <= x <= ex and 0 <= y <= ey
    assert x + w <= width and y + h == height
    assert ex + size <= x + w and ey + size <= y + h
    assert 0 <= ex - x < 50


@pytest.mark.parametrize("name", (
    "스크린샷 2026-10-09 193901.png", "스크린샷 2026-10-09 195115.png",
))
def test_real_absent_anchor(name, assets):
    frame = image_io.imread(str(ROOT / "tests" / "data" / name), cv2.IMREAD_COLOR)
    assert frame is not None, name
    assert run_detector("buff", frame, assets, {}) is None
