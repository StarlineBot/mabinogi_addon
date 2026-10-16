"""Independent runtime stability probes; real crops plus explicit fault injection."""

from pathlib import Path
import re

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.detect.stat_bars import read_stat_bars
from mabinogi_addon.tracker.boss_pattern import BossPatternTracker
from mabinogi_addon.ui import boss_tab, stat_bars_tab
from test_support.boundaries import ExternalBoundaries


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "tests/data/stat_bar_shots"


class Watcher:
    def is_game_active(self):
        return True

    def is_self_active(self):
        return False


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def runtime(app, monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data, path))
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa", "name": "QA"})
    config._write_local_config({})
    with ExternalBoundaries() as boundary:
        yield
        assert not boundary.violations
    app.processEvents()


@pytest.fixture
def stat_pipeline(runtime, app, monkeypatch):
    image = image_io.imread(SHOTS / "hp021_mp100_sta100_007.png")
    assert image is not None and image.shape == (32, 104, 3)
    frame, clock, played = [image], [0.0], []
    tab = stat_bars_tab.StatBarsTab(Watcher())
    tab._timer.stop()
    tab._enabled = True
    tab._region = {"x": 0, "y": 0, "w": 104, "h": 32}
    tab._alert_sound_on = True
    for sid, values in tab._bars_cfg.items():
        values["alert"].update(on=sid == "hp", pct=30)
    tab.set_boss_presence_source(lambda: True)
    monkeypatch.setattr(tab, "_grab_rect", lambda *args: frame[0])
    monkeypatch.setattr(tab, "_show_preview", lambda *args: None)
    monkeypatch.setattr(tab, "_play_alert_sound", lambda: played.append(clock[0]))
    monkeypatch.setattr(stat_bars_tab.time, "monotonic", lambda: clock[0])
    try:
        yield tab, frame, clock, played
    finally:
        tab.shutdown()
        for overlay in tab._overlays.values():
            overlay.close()
            overlay.deleteLater()
        tab.close()
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("path", sorted(SHOTS.glob("hp???_mp100_sta100_*.png")), ids=lambda p: p.name)
def test_existing_labeled_stat_crops_keep_correct_identity_and_ratio(path):
    frame = image_io.imread(path)
    assert frame is not None
    expected = int(re.match(r"hp(\d+)_", path.name).group(1)) / 100
    values = {r.stat_id: r.ratio for r in read_stat_bars(frame)}
    assert set(values) == {"hp", "mp", "sta"}
    assert abs(values["hp"] - expected) <= 0.06
    assert values["mp"] >= 0.97 and values["sta"] >= 0.97


def test_partial_occlusion_must_not_replace_hp_with_full_mp(stat_pipeline):
    tab, frame, _clock, _played = stat_pipeline
    tab._tick()
    original_hp = tab._overlays["hp"]._ratio
    assert 0.15 < original_hp < 0.3
    hidden = frame[0].copy()
    hidden[:12] = 0  # Controlled occlusion of HP only; MP/STA pixels remain original.
    np.testing.assert_array_equal(hidden[12:], frame[0][12:])
    frame[0] = hidden
    assert len(read_stat_bars(hidden)) == 2
    tab._tick()
    assert not tab._overlays["hp"].isVisible() or tab._overlays["hp"]._ratio == original_hp, {
        "before_hp": original_hp,
        "after_hp": tab._overlays["hp"]._ratio,
        "status": tab.value_label.text(),
        "readings": [(r.stat_id, r.ratio) for r in read_stat_bars(hidden)],
    }


def test_capture_failure_breaks_continuous_low_hp_debounce(stat_pipeline):
    tab, frame, clock, played = stat_pipeline
    low = frame[0]
    tab._tick()
    assert played == []
    frame[0], clock[0] = None, 10.0
    tab._tick()
    frame[0], clock[0] = low, 10.01
    tab._tick()
    assert played == [], {"played": played, "low_since": tab._alert_low_since}
    clock[0] = 10.45
    tab._tick()
    assert played == [10.45]


def test_valid_low_hp_frames_warn_once_and_missing_bands_never_warn(stat_pipeline):
    tab, frame, clock, played = stat_pipeline
    for moment in (0.0, 0.2, 0.41, 0.8, 1.0):
        clock[0] = moment
        tab._tick()
    assert played == [0.41]
    hidden = frame[0].copy()
    hidden[:12] = 0
    frame[0] = hidden
    for moment in (2.0, 3.0):
        clock[0] = moment
        tab._tick()
    assert played == [0.41]


def test_boss_monotonic_decrease_and_real_phase_reset():
    tracker = BossPatternTracker("QA", [50])
    fired = [(a.threshold, a.stage) for hp in range(60, 49, -1) for a in tracker.observe(hp)]
    assert fired == [(50, "pre"), (50, "near")]
    tracker.observe(100)
    fired = [(a.threshold, a.stage) for hp in range(99, 49, -1) for a in tracker.observe(hp)]
    assert fired == [(50, "pre"), (50, "near")]


def test_boss_accepted_small_upward_readings_can_rearm_same_band(runtime, app, monkeypatch):
    tab = boss_tab.BossTab(Watcher())
    tab._timer.stop()
    tab._region = {"x": 0, "y": 0, "w": 150, "h": 36}
    tab.enable.setChecked(True)
    frame = np.zeros((36, 150, 3), np.uint8)
    value, messages = [56], []
    monkeypatch.setattr(tab, "_grab_rect", lambda *args: frame)
    monkeypatch.setattr(tab, "_show_preview", lambda *args: None)
    monkeypatch.setattr(boss_tab, "identify", lambda *args: "lenen_miir")
    monkeypatch.setattr(boss_tab, "read_percent", lambda *args: value[0])
    monkeypatch.setattr(tab._overlay, "show_message", lambda message, *args: messages.append(message))
    monkeypatch.setattr(tab, "_play", lambda *args: None)
    try:
        for value[0] in [56, 56, 56]:
            tab._tick()
        tab._tracker = BossPatternTracker("QA", [50])
        for value[0] in [55, 55, 56, 56, 55, 55]:
            tab._tick()
        assert messages == ["QA 50% \ud328\ud134 \uc900\ube44"] * 2
        # This confirms the conditional route, not that a real screenshot misreads 55 as 56.
    finally:
        tab.shutdown()
        tab.close()
        tab.deleteLater()
        app.processEvents()
