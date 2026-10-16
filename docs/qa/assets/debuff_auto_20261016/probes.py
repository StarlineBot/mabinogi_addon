"""Explicit independent auto-mode QA; no product implementation changes."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.tracker import debuff_engine as engine_module
from mabinogi_addon.tracker.debuff_engine import DebuffEngine
from mabinogi_addon.ui import buff_controller, debuff_tab, dpi, main_window


ROOT = Path(__file__).resolve().parents[4]
PAIR = ("프라가라흐(마법)", "프라가라흐(물리)")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def templates():
    folder = ROOT / "src/mabinogi_addon/assets/debuff/icon"
    return {name: image_io.imread(folder / f"{name}.png") for name in PAIR}


def native(name):
    return image_io.imread(ROOT / "docs/qa/assets/debuff_native_20261016/candidates" / f"{name}.png")


def settle(engine, frame, start=0, bar=None):
    for index in range(12):
        result = engine.tick(frame, start + index * .15, bar_region=bar)
    return {entry.buff_id for entry in result.entries}


@pytest.mark.parametrize("scene", ("213313", "213734"))
@pytest.mark.parametrize("has_hp", (False, True))
def test_actual_full_roi_auto_matches_off_without_double_identity(scene, has_hp):
    shot = image_io.imread(ROOT / "tests/data" / f"스크린샷 2026-10-15 {scene}.png")
    roi, hp = shot[1195:1283,1016:1537], shot[1246:1283,1016:1537]
    e = DebuffEngine(templates(), list(PAIR), gate_mode="auto")
    old = DebuffEngine(templates(), list(PAIR), gate_mode="off")
    assert settle(e, roi, bar=hp if has_hp else None) == settle(old, roi) == set()
    assert e.gate_diagnostics["reason"] == "boss_present"


def test_auxiliary_cache_failure_is_bounded_and_primary_updates_continue(app, monkeypatch, caplog):
    pixels = native(PAIR[0])
    hp = np.zeros((37,521,3), np.uint8)
    now, calls = [0.0], []
    def capture():
        calls.append(now[0])
        if len(calls) in (2,3,4,6):
            raise OSError("controlled auxiliary failure")
        return hp
    monkeypatch.setattr(buff_controller.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(engine_module, "read_percent_cached", lambda *a, **k: (45,0))
    engine = DebuffEngine(templates(), list(PAIR), gate_mode="auto")
    worker = buff_controller._TrackWorker(SimpleNamespace(grab=lambda: pixels), engine, None,
                                          bar_source=SimpleNamespace(grab=capture))
    updates = []
    worker.updated.connect(updates.append)
    for value in (0,.15,.3,.45,.6001,.75,.9,1.05,1.2002,1.35,1.5,1.65,1.8003,2,2.4004,3.0005):
        now[0] = value
        worker._tick_once(True)
        if .6001 <= value < 2.4004 or value == 3.0005:
            assert engine.gate_diagnostics["hp_reason"] == "capture_missing"
            assert worker._bar_frame is None
        assert {entry.buff_id for entry in updates[-1]} in (set(PAIR), {PAIR[1]})
    assert len(updates) == 16 and len(calls) == 6
    failures = [r for r in caplog.records if r.getMessage() == "보스 바 캡처 실패 — 아이콘 감시 유지"]
    assert len(failures) == 2
    assert engine._shown[PAIR[0]] is False


@pytest.mark.parametrize("has_hp", (False, True))
@pytest.mark.parametrize("tracked", PAIR)
def test_logged_out_real_ui_and_factory_keep_boss_off_and_settings(app, tmp_path, monkeypatch, has_hp, tracked):
    path = tmp_path / "한글 공백 경로" / "설정.json"
    raw = {
        "general": {"debuffGateMode": "percent", "skipSetup": True},
        "bossPattern": {"enabled": False},
        "debuffTracker": {"enabled": True, "captureRegion": dict(x=0,y=0,w=16,h=16),
                          "debuffs": [{"id": name, "hidden": name != tracked} for name in PAIR]},
    }
    if has_hp:
        raw["bossPattern"]["box"] = dict(x=0,y=16,w=521,h=37)
    read, write = config._read_local_config, config._write_local_config
    write(deepcopy(raw), path)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data,path))
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    folder = ROOT / "src/mabinogi_addon/assets/debuff/icon"
    catalog = [SimpleNamespace(id=name, name=name, match_icon=folder/f"{name}.png", display_image=None) for name in PAIR]
    monkeypatch.setattr(main_window, "available_debuff_catalog", lambda: catalog)
    monkeypatch.setattr(debuff_tab, "available_debuff_catalog", lambda: catalog)
    monkeypatch.setattr(dpi, "to_physical", lambda box: tuple(box[k] for k in ("x","y","w","h")))
    sources, controllers = [], []
    def source(region):
        value = object()
        sources.append(value)
        return value
    class Controller:
        def __init__(self, *a, **k):
            self.stops = 0
            controllers.append(self)
        def stop(self):
            self.stops += 1
        def set_paused(self, value):
            pass
        def start(self, source, engine, **kwargs):
            self.kwargs = kwargs
    monkeypatch.setattr(main_window, "create_live_source", source)
    monkeypatch.setattr(main_window, "BuffController", Controller)
    tab = debuff_tab.DebuffTab()
    window = SimpleNamespace(_closing=False, _config_pending_restart=False, _booting=False,
                             debuff_controller=None, _debuff_engine=None, _paused=False,
                             _watcher=None, debuff_overlay=object(), debuff_tab=tab,
                             _debuff_warn_gone_ids=lambda: set(), _on_debuff_gone=lambda *a: None)
    window._debuff_order = lambda items: main_window.MainWindow._debuff_order(window, items)
    window._start_debuff_tracking = lambda: main_window.MainWindow._start_debuff_tracking(window)
    try:
        tab.show()
        app.processEvents()
        before = path.read_bytes()
        window._start_debuff_tracking()
        tab.gate_mode_changed.connect(lambda mode: main_window.MainWindow._on_debuff_gate_mode(window,mode))
        assert tab.effective_gate_mode() == window._debuff_engine.gate_mode == "auto"
        assert len(sources) == (2 if has_hp else 1)
        assert (controllers[-1].kwargs["bar_source"] is not None) == has_hp
        assert not tab._bar_gating_notice.isVisible()
        assert path.read_bytes() == before
        tab.diagnostic_button.click()
        assert tab._method_row.isVisible() and len(controllers) == 1
        assert path.read_bytes() == before
        actual = next(name for name in PAIR if name != tracked)
        assert settle(window._debuff_engine, native(actual)) == {tracked}
        for _ in range(5):
            for mode in ("off","auto"):
                tab.method_combo.setCurrentIndex(tab.method_combo.findData(mode))
                assert window._debuff_engine.gate_mode == mode
                assert settle(window._debuff_engine, native(actual)) == {tracked}
        saved = config._read_local_config()
        assert saved["bossPattern"] == raw["bossPattern"]
        assert saved["debuffTracker"] == raw["debuffTracker"]
        assert saved["general"]["debuffAutoGate"] is True
        assert saved["general"]["debuffGateMode"] == "off"
        assert len(controllers) == 11
        assert all(controller.stops == 1 for controller in controllers[:-1])
    finally:
        tab.close()
        app.processEvents()
