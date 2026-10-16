from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mabinogi_addon import config
from mabinogi_addon.tracker import debuff_engine as module
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


@pytest.fixture
def inputs():
    rng = np.random.default_rng(47)
    icon = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
    floor = rng.integers(0, 256, (80, 160, 3), dtype=np.uint8)
    boss = floor.copy()
    boss[60:76] = (40, 80, 210)
    boss[8:24, 8:24] = icon
    icons_only = floor.copy()
    icons_only[8:24, 8:24] = icon
    hp = np.zeros((32, 160, 3), np.uint8)
    assert DebuffEngine._bar_present(boss)
    assert DebuffEngine._is_background(floor)
    assert not DebuffEngine._is_background(hp)
    return icon, floor, boss, icons_only, hp


def settle(engine, frame, start=0, bar=None, foreground=True):
    for index in range(12):
        result = engine.tick(frame, start + index * .15, bar_region=bar, foreground=foreground)
    return {entry.buff_id for entry in result.entries}


def engine(inputs):
    return DebuffEngine({"a": inputs[0]}, ["a"], gate_mode="auto")


def test_no_hp_region_or_boss_evidence_preserves_icon_only_monitoring(inputs):
    e = engine(inputs)
    assert settle(e, inputs[3]) == set()
    assert e.gate_diagnostics["reason"] == "icon_monitoring"
    assert not e.bar_seen
    assert settle(e, inputs[1], 2) == {"a"}
    assert e.gate_diagnostics["reason"] != "boss_absent"
    assert settle(e, inputs[3], 4) == set()


def test_unvalidated_hp_background_does_not_reset_icons(inputs):
    e = engine(inputs)
    assert settle(e, inputs[3], bar=inputs[1][:32]) == set()
    assert e.gate_diagnostics["hp"] == "unknown"
    assert not e.bar_seen


@pytest.mark.parametrize("reading", [None, -1, 101, float("nan"), "invalid"])
def test_uncertain_hp_reading_is_not_boss_absence(inputs, monkeypatch, reading):
    monkeypatch.setattr(module, "read_percent_cached", lambda *a, **k: (reading, None))
    e = engine(inputs)
    assert settle(e, inputs[3], bar=inputs[4]) == set()
    assert e.gate_diagnostics["hp"] == "unknown"
    assert e.gate_diagnostics["reason"] == "icon_monitoring"


def test_hp_reader_exception_recovers_and_is_throttled(inputs, monkeypatch):
    calls = []
    fail = [True]
    def read(*a, **k):
        calls.append(True)
        if fail[0]:
            raise RuntimeError("read failure")
        return 42, 0
    monkeypatch.setattr(module, "read_percent_cached", read)
    e = engine(inputs)
    assert settle(e, inputs[3], bar=inputs[4]) == set()
    assert len(calls) <= 3
    fail[0] = False
    assert settle(e, inputs[3], 2, inputs[4]) == set()
    assert e.bar_seen and e.gate_diagnostics["hp"] == "present"


def test_conflicts_missing_capture_dark_bar_and_boss_reentry(inputs, monkeypatch):
    monkeypatch.setattr(module, "read_percent_cached", lambda *a, **k: (40, 0))
    e = engine(inputs)
    assert settle(e, inputs[3], bar=inputs[4]) == set()
    assert settle(e, inputs[2], 2, inputs[4]) == set()
    assert e.bar_seen
    assert settle(e, inputs[2], 4, inputs[1][:32]) == set()
    assert e.gate_diagnostics["reason"] == "conflicting_evidence"
    assert settle(e, inputs[1], 6, inputs[4]) == {"a"}
    assert e.gate_diagnostics["reason"] == "conflicting_evidence"
    assert settle(e, inputs[3], 8, None) == set()
    assert e.gate_diagnostics["reason"] != "boss_absent"
    monkeypatch.setattr(module, "read_percent_cached", lambda *a, **k: (None, None))
    assert settle(e, inputs[3], 10, inputs[4]) == set()
    assert e.gate_diagnostics["hp"] == "unknown"
    # 불명 상태에서도 아이콘의 실제 감지/해제는 계속 진행한다.
    assert settle(e, inputs[1], 12, None) == {"a"}
    assert e.gate_diagnostics["reason"] != "boss_absent"
    assert settle(e, inputs[1], 14, inputs[1][:32]) == {"a"}
    assert e.gate_diagnostics["reason"] == "boss_absent"
    monkeypatch.setattr(module, "read_percent_cached", lambda *a, **k: (0, 0))
    assert settle(e, inputs[2], 16, inputs[4]) == set()
    assert e.gate_diagnostics["reason"] == "boss_present"


def test_single_scan_per_icon_and_no_state_accumulation(inputs, monkeypatch):
    e = engine(inputs)
    detect = e._detect
    calls = []
    def record(*args):
        calls.append(args[1])
        return detect(*args)
    monkeypatch.setattr(e, "_detect", record)
    for index in range(60):
        e.tick(inputs[2] if index % 2 else inputs[1], now=index * .15)
    assert calls == ["a"] * 60
    for state in (e._matched, e._shown, e._detect_since, e._absent_since):
        assert set(state) == {"a"}


@pytest.mark.parametrize("legacy", [{}, {"debuffGateMode": "off"}, {"debuffGateMode": "band"},
                                    {"debuffGateMode": "percent"}, {"debuffBarGating": True}])
def test_automatic_default_preserves_legacy_choice_and_other_settings(tmp_path, legacy):
    path = tmp_path / "한글 경로" / "config.json"
    raw = {"general": deepcopy(legacy), "bossPattern": {"box": {"x": 1}}, "debuffTracker": [{"id": "a"}]}
    config._write_local_config(raw, path)
    assert config.load_debuff_runtime_mode(path) == "auto"
    assert config._read_local_config(path) == raw
    config.save_debuff_runtime_mode("auto", path)
    assert config._read_local_config(path)["general"] == {**legacy, "debuffAutoGate": True}
    config.save_debuff_runtime_mode("percent", path)
    assert config.load_debuff_runtime_mode(path) == "percent"
    assert config._read_local_config(path)["bossPattern"] == raw["bossPattern"]
    config.save_debuff_runtime_mode("auto", path)
    assert config.load_debuff_gate_mode(path) == "percent"
    assert config.load_debuff_runtime_mode(path) == "auto"


def test_bar_capture_exception_does_not_discard_primary_icon_frame(inputs):
    from mabinogi_addon.ui.buff_controller import _TrackWorker
    class Bar:
        def grab(self):
            raise OSError("capture failed")
    e = engine(inputs)
    worker = _TrackWorker(SimpleNamespace(grab=lambda: inputs[3]), e, None, bar_source=Bar())
    updates = []
    worker.updated.connect(updates.append)
    worker._tick_once(True)
    assert len(updates) == 1
    assert e.gate_diagnostics["hp_reason"] == "capture_missing"


def test_actual_game_images_work_with_auto_without_pattern_feature():
    from mabinogi_addon import image_io

    root = Path(__file__).resolve().parents[1]
    ids = ("프라가라흐(마법)", "프라가라흐(물리)")
    templates = {bid: image_io.imread(root / "src/mabinogi_addon/assets/debuff/icon" / f"{bid}.png")
                 for bid in ids}
    for name in ("213313", "213734"):
        shot = image_io.imread(root / "tests/data" / f"스크린샷 2026-10-15 {name}.png")
        e = DebuffEngine(templates, list(ids), gate_mode="auto")
        assert settle(e, shot[1195:1283, 1016:1537], bar=shot[1246:1283, 1016:1537]) == set()
        assert e.bar_seen
        assert e.gate_diagnostics["reason"] == "boss_present"


def test_auto_ui_is_default_logged_out_and_diagnostics_do_not_save(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui.debuff_tab import DebuffTab

    app = QApplication.instance() or QApplication([])
    writes = []
    raw = {"general": {"debuffGateMode": "percent"}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(raw))
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    tab = DebuffTab()
    try:
        tab.show()
        app.processEvents()
        assert tab.effective_gate_mode() == "auto"
        assert tab._method_row.isHidden()
        assert tab._bar_region_row.isVisible()
        assert not tab._bar_gating_notice.isVisible()
        tab.diagnostic_button.click()
        assert tab._method_row.isVisible()
        tab.set_gate_status({"reason": "conflicting_evidence"})
        assert tab.effective_gate_mode() == "auto"
        assert not writes
    finally:
        tab.close()


@pytest.mark.parametrize("value", [0, 1, 100])
def test_valid_hp_including_zero_is_presence(inputs, monkeypatch, value):
    monkeypatch.setattr(module, "read_percent_cached", lambda *a, **k: (value, 0))
    e = engine(inputs)
    assert settle(e, inputs[3], bar=inputs[4]) == set()
    assert e.gate_diagnostics["hp"] == "present"


def test_known_roi_presence_avoids_unneeded_percent_reader(inputs, monkeypatch):
    monkeypatch.setattr(module, "read_percent_cached", lambda *a, **k: pytest.fail("unneeded HP read"))
    assert settle(engine(inputs), inputs[2], bar=inputs[4]) == set()


def test_aux_capture_is_throttled_and_recovers_without_stale_frame(inputs, monkeypatch):
    from mabinogi_addon.ui import buff_controller as worker_module

    now = [0.0]
    calls = []
    def grab():
        calls.append(True)
        if len(calls) == 1:
            raise OSError("first capture failed")
        return inputs[4]
    monkeypatch.setattr(worker_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(module, "read_percent_cached", lambda *a, **k: (25, 0))
    e = engine(inputs)
    worker = worker_module._TrackWorker(SimpleNamespace(grab=lambda: inputs[3]), e, None,
                                        bar_source=SimpleNamespace(grab=grab))
    updates = []
    worker.updated.connect(updates.append)
    for value in (0.0, .15, .3, .45, .6):
        now[0] = value
        worker._tick_once(True)
    assert len(calls) == 2
    assert len(updates) == 5
    assert e.gate_diagnostics["hp"] == "present"
