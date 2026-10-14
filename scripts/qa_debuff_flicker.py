"""Independent debuff flicker QA. Run explicitly with pytest."""

from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import image_io
from mabinogi_addon.catalog import BuffDef
from mabinogi_addon.tracker.debuff_engine import DebuffEngine
from mabinogi_addon.tracker.engine import BuffEngine
from mabinogi_addon.ui.buff_controller import BuffController


REPO = Path(__file__).resolve().parents[1]
ICONS = [
    "\ub9c8\ubc95 \ubc29\uc5b4\ub825 \ubcf4\ud638 \uac10\uc18c",
    "\ud504\ub77c\uac00\ub77c\ud750(\ub9c8\ubc95)",
]


@pytest.fixture(scope="session")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=ICONS, ids=["magic-defense-reduction", "fragarach-magic"])
def pipeline(request, application):
    bid = request.param
    path = REPO / "src/mabinogi_addon/assets/debuff/icon" / f"{bid}.png"
    template = image_io.imread(path)
    assert template is not None, path
    empty = np.zeros((40, 160, 3), np.uint8)
    empty[22:40] = (160, 60, 120)
    present = empty.copy()
    present[0:16, 32:48] = cv2.resize(template, (16, 16), interpolation=cv2.INTER_AREA)
    assert DebuffEngine._bar_present(empty)
    assert DebuffEngine._bar_present(present)
    engine = DebuffEngine({bid: template}, [bid])

    class Overlay:
        locked = True
        items = []
        visible = False

        def set_items(self, items):
            self.items = items

        def show(self):
            self.visible = True

        def hide(self):
            self.visible = False

    overlay = Overlay()
    catalog = {bid: BuffDef(bid, bid, path, None)}
    controller = BuffController(overlay, catalog, {bid: False})
    trace = []

    def step(now, frame):
        score = engine.best_scores(frame)[bid]
        result = engine.tick(frame, now=now)
        controller._on_updated(result.entries)
        trace.append({
            "time": now, "score": round(score, 4),
            "raw_matched": engine._matched[bid],
            "shown": bid in [entry.buff_id for entry in result.entries],
            "overlay_items": len(overlay.items),
            "overlay_visible": overlay.visible,
            "absent_since": engine._absent_since[bid],
            "detect_since": engine._detect_since[bid],
        })
        return trace[-1]

    assert engine.best_scores(present)[bid] >= engine.detect_threshold_for(bid)
    assert engine.best_scores(empty)[bid] < engine.release_threshold_for(bid)
    for now in (0.0, 0.151, 0.302):
        step(now, present)
    assert not trace[-1]["shown"]
    return engine, step, present, empty, trace


def test_redetection_before_reappear_deadline_must_not_flash(pipeline):
    engine, step, present, empty, trace = pipeline
    assert 0.755 - 0.453 < engine._reappear
    for now in (0.453, 0.604):
        assert not step(now, empty)["shown"]
    recovery = [step(now, present) for now in (0.755, 0.906, 1.057, 1.208)]
    assert all(row["raw_matched"] for row in recovery)
    assert [row["overlay_items"] for row in recovery] == [0, 0, 0, 0], {
        "times": [row["time"] for row in recovery],
        "scores": [row["score"] for row in recovery],
        "items": [row["overlay_items"] for row in recovery],
    }


def test_stable_applied_icon_does_not_flash(pipeline):
    _engine, step, present, _empty, _trace = pipeline
    for tick in range(1, 101):
        assert not step(0.302 + tick * 0.151, present)["shown"]


def test_single_bad_tick_does_not_flash(pipeline):
    _engine, step, present, empty, _trace = pipeline
    assert not step(0.453, empty)["shown"]
    for now in (0.604, 0.755, 0.906, 1.057):
        assert not step(now, present)["shown"]


def test_genuinely_missing_icon_reappears(pipeline):
    _engine, step, _present, empty, _trace = pipeline
    rows = [step(now, empty) for now in (0.453, 0.604, 0.755, 0.906)]
    assert not rows[0]["shown"]
    assert rows[-1]["shown"]
    assert rows[-1]["overlay_items"] == 1


def test_planning_document_delay_prevents_same_glitch(pipeline):
    engine, step, present, empty, _trace = pipeline
    engine._reappear = 1.5
    for now in (0.453, 0.604):
        assert not step(now, empty)["shown"]
    for now in (0.755, 0.906, 1.057, 1.208):
        assert not step(now, present)["shown"]


def test_buff_engine_keeps_state_across_same_short_gap(pipeline):
    debuff, _step, _present, _empty, _trace = pipeline
    bid = debuff._order[0]
    template = debuff._templates[bid]
    height, width = template.shape[:2]
    present = np.zeros((height + 10, width + 20, 3), np.uint8)
    present[0:height, 10:10 + width] = template
    empty = np.zeros_like(present)
    buff = BuffEngine({bid: template}, [bid], show_duration={bid: False},
                      icon_column=(0, width + 20))
    for now in (0.0, 0.151, 0.302):
        result = buff.tick(present, now=now)
    assert [entry.buff_id for entry in result.entries] == [bid]
    for now in (0.453, 0.604):
        result = buff.tick(empty, now=now)
        assert [entry.buff_id for entry in result.entries] == [bid]
    for now in (0.755, 0.906, 1.057, 1.208):
        result = buff.tick(present, now=now)
        assert [entry.buff_id for entry in result.entries] == [bid]


def test_tight_icon_crop_matches_but_loses_hp_bar_evidence(pipeline):
    engine, _step, present, _empty, _trace = pipeline
    bid = engine._order[0]
    tight = present[0:16]
    assert engine.best_scores(tight)[bid] >= engine.detect_threshold_for(bid)
    assert DebuffEngine._bar_present(present)
    assert not DebuffEngine._bar_present(tight)
