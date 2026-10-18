"""Observe real controller recovery with an injected search cost, not a time SLA."""

from pathlib import Path
import sys
from time import monotonic

import pytest
from PySide6.QtCore import QEventLoop, QTimer

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_dorcha_tracking import moving, one_cv_thread, place  # noqa: E402,F401
from mabinogi_addon import image_io  # noqa: E402
from mabinogi_addon.detect.dorcha_reader import read_dorcha  # noqa: E402
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha  # noqa: E402
from mabinogi_addon.ui import dorcha_search  # noqa: E402


def visible_five(state):
    source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-16 211352.png")
    assert source is not None
    x, y = (931, 929) if source.shape[0] == 1436 else (933, 931)
    state.ornament = source[y:y + 57, x:x + 45].copy()
    place(state, 20, 20)
    assert read_dorcha(state.frame[20:43, 20:48]) == 5
    assert locate_dorcha(state.frame) == (20, 20, 28, 23)


def drain(app, tab):
    deadline = monotonic() + 5
    while tab._search_worker is not None and monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
        app.processEvents()
    assert tab._search_worker is None


@pytest.mark.parametrize("elapsed", [0.1, 2.0, 8.0, 15.0])
def test_loading_failure_suppresses_readable_saved_region_until_cost_deadline(
        moving, monkeypatch, elapsed):
    app, tab, state, writes = moving
    original = dict(tab._region)
    real_worker = dorcha_search.DorchaSearch

    class CostControlledSearch(real_worker):
        def run(self):
            super().run()
            # Only the measured cost is injected; the detector reads actual pixels.
            self.elapsed = elapsed

    monkeypatch.setattr(dorcha_search, "DorchaSearch", CostControlledSearch)
    state.game = False
    tab._tick()
    assert tab._search_worker is None
    state.game = True
    tab._tick()
    assert tab._tracking_lost and tab._search_worker is not None
    state.now += elapsed
    drain(app, tab)
    assert tab._overlay.value is None
    finished = state.now
    delay = tab._next_search - finished
    assert delay == pytest.approx(elapsed * 20)

    visible_five(state)
    assert tab._verify_registered_region((20, 20, 28, 23), state.target) == (20, 20, 28, 23)
    captures = len(state.captures)
    for seconds in sorted({0.2, 1.0, 10.0, 30.0, 60.0, 120.0, delay - 0.2}):
        if seconds >= delay:
            continue
        state.now = finished + seconds
        tab._tick()
        assert tab._overlay.value is None
        assert tab._search_worker is None
        assert len(state.captures) == captures

    state.now = tab._next_search + 0.001
    tab._tick()
    drain(app, tab)
    assert tab._overlay.value == 5 and not tab._tracking_lost
    assert tab._next_search == 0 and tab._region == original and not writes
    print(f"injected_search_cost={elapsed}s, no_read_cooldown={delay}s, recovered=5")


def test_visible_on_first_tick_reads_five_without_full_search(moving):
    app, tab, state, writes = moving
    visible_five(state)
    tab._tick()
    assert tab._overlay.value == 5 and not tab._tracking_lost
    assert tab._search_worker is None and not writes
    assert all(box[2:] != (260, 180) for box in state.captures)
