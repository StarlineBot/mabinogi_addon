"""Explicit independent QA of real startup/visibility handlers with fake capture."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mabinogi_addon import config, image_io, setup_state
from mabinogi_addon.ui import main_window as ui
from mabinogi_addon.ui import dpi


ROOT = Path(__file__).resolve().parents[4]
PAIR = ("프라가라흐(마법)", "프라가라흐(물리)")
NATIVE = ROOT / "docs/qa/assets/debuff_native_20261016/candidates"


def settle(engine, actual):
    frame = image_io.imread(NATIVE / f"{actual}.png")
    for index in range(12):
        result = engine.tick(frame, now=index * .15)
    return {entry.buff_id for entry in result.entries}


@pytest.fixture(params=("bundled", "native"))
def app_path(request, monkeypatch):
    folder = ROOT / "src/mabinogi_addon/assets/debuff/icon" if request.param == "bundled" else NATIVE
    catalog = [SimpleNamespace(id=name, match_icon=folder / f"{name}.png") for name in PAIR]
    settings = [SimpleNamespace(id=name, hidden=False) for name in PAIR]
    mode = {"value": "off"}
    controllers, sources = [], []

    class Source:
        def __init__(self, region):
            self.region = region
            sources.append(self)

    class Controller:
        def __init__(self, *args, **kwargs):
            self.stops = 0
            controllers.append(self)
        def stop(self):
            self.stops += 1
        def set_paused(self, paused):
            self.paused = paused
        def start(self, source, engine, **kwargs):
            self.source, self.engine, self.kwargs = source, engine, kwargs

    monkeypatch.setattr(config, "load_debuff_settings", lambda: settings)
    monkeypatch.setattr(config, "load_capture_region", lambda *args: dict(x=0,y=0,w=16,h=16))
    monkeypatch.setattr(config, "load_boss_bar_region", lambda: dict(x=0,y=16,w=521,h=37))
    monkeypatch.setattr(setup_state, "enabled", lambda *args: True)
    monkeypatch.setattr(dpi, "to_physical", lambda box: tuple(box[key] for key in ("x","y","w","h")))
    monkeypatch.setattr(ui, "available_debuff_catalog", lambda: catalog)
    monkeypatch.setattr(ui, "create_live_source", Source)
    monkeypatch.setattr(ui, "BuffController", Controller)
    window = SimpleNamespace(
        _closing=False, _config_pending_restart=False, debuff_controller=None,
        _debuff_engine=None, _paused=False, _watcher=None, debuff_overlay=object(),
        debuff_tab=SimpleNamespace(effective_gate_mode=lambda: mode["value"]),
        _debuff_warn_gone_ids=lambda: set(), _on_debuff_gone=lambda *args: None,
    )
    window._debuff_order = lambda items: ui.MainWindow._debuff_order(window, items)
    window._start_debuff_tracking = lambda: ui.MainWindow._start_debuff_tracking(window)
    return window, settings, catalog, mode, controllers, sources


@pytest.mark.parametrize("tracked", PAIR)
@pytest.mark.parametrize("mode", ("off", "band", "percent"))
def test_same_identity_before_hide_after_three_restarts_and_show(app_path, tracked, mode):
    window, settings, catalog, selected, controllers, sources = app_path
    selected["value"] = mode
    actual = next(name for name in PAIR if name != tracked)
    window._start_debuff_tracking()
    next(item for item in settings if item.id == actual).hidden = True
    ui.MainWindow._on_debuff_tracking_changed(window)
    assert settle(window._debuff_engine, actual) == {tracked}
    for _ in range(3):
        old = window.debuff_controller
        window._start_debuff_tracking()
        engine = window._debuff_engine
        assert old.stops == 1
        assert engine.gate_mode == mode
        assert set(engine._templates) == set(engine._gray_variants) == {tracked}
        assert set(engine._identity_variants) == set(PAIR)
        assert set(engine._shown) == set(engine._matched) == {tracked}
        assert settle(engine, actual) == {tracked}
        assert settle(engine, tracked) == set()
        assert (window.debuff_controller.kwargs["bar_source"] is not None) == (mode == "percent")
    previous = window.debuff_controller
    next(item for item in settings if item.id == actual).hidden = False
    ui.MainWindow._on_debuff_tracking_changed(window)
    assert previous.stops == 1
    assert set(window._debuff_engine._templates) == set(PAIR)
    assert settle(window._debuff_engine, actual) == {tracked}
    assert all(controller.stops == 1 for controller in controllers[:-1])


@pytest.mark.parametrize("tracked", PAIR)
def test_both_hidden_then_one_enabled_and_reordered(app_path, tracked):
    window, settings, *_ = app_path
    for item in settings:
        item.hidden = True
    window._start_debuff_tracking()
    assert not window._debuff_engine._templates
    previous = window.debuff_controller
    next(item for item in settings if item.id == tracked).hidden = False
    ui.MainWindow._on_debuff_tracking_changed(window)
    assert previous.stops == 1
    actual = next(name for name in PAIR if name != tracked)
    assert settle(window._debuff_engine, actual) == {tracked}
    settings.reverse()
    before = window.debuff_controller
    ui.MainWindow._on_debuff_tracking_changed(window)
    assert window.debuff_controller is before
    assert settle(window._debuff_engine, actual) == {tracked}


@pytest.mark.parametrize("tracked", PAIR)
def test_hidden_reference_uses_current_catalog_override(app_path, tracked):
    window, settings, catalog, *_ = app_path
    peer = next(name for name in PAIR if name != tracked)
    next(item for item in settings if item.id == peer).hidden = True
    target_path = next(item.match_icon for item in catalog if item.id == tracked)
    next(item for item in catalog if item.id == peer).match_icon = target_path
    window._start_debuff_tracking()
    engine = window._debuff_engine
    assert np.array_equal(engine._variants[tracked][0], engine._identity_variants[peer][0])
    assert settle(engine, tracked) == {tracked}, "identical user images are ambiguous, not positive identity"


@pytest.mark.parametrize("tracked", PAIR)
def test_reference_only_is_not_scanned_as_another_target(app_path, tracked, monkeypatch):
    window, settings, *_ = app_path
    peer = next(name for name in PAIR if name != tracked)
    next(item for item in settings if item.id == peer).hidden = True
    window._start_debuff_tracking()
    engine = window._debuff_engine
    original = engine._candidate_best
    searched = []
    def record(frame, identity, gray, **kwargs):
        searched.append(identity)
        return original(frame, identity, gray, **kwargs)
    monkeypatch.setattr(engine, "_candidate_best", record)
    assert settle(engine, peer) == {tracked}
    assert set(searched) == {tracked}
    assert set(engine.best_scores(image_io.imread(NATIVE / f"{peer}.png"))) == {tracked}
