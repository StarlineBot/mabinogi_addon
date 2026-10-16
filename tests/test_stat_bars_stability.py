"""실제 저HP PNG의 부분 가림/미관측 구간을 탭과 오버레이까지 재생한다."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.detect.stat_bars import _bands, read_stat_bars
from mabinogi_addon.ui import stat_bars_tab

SHOT = Path(__file__).parent / "data/stat_bar_shots/hp021_mp100_sta100_007.png"


@pytest.fixture
def pipeline(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    source = image_io.imread(SHOT)
    assert source is not None
    state = SimpleNamespace(frame=source.copy(), now=0.0, active=True, boss=True, sounds=[])
    watcher = SimpleNamespace(is_game_active=lambda: state.active, is_self_active=lambda: False)
    tab = stat_bars_tab.StatBarsTab(watcher)
    tab._timer.stop()
    tab._enabled = True
    tab._region = {"x": 0, "y": 0, "w": source.shape[1], "h": source.shape[0]}
    tab._alert_sound_on = True
    for sid, values in tab._bars_cfg.items():
        values["alert"].update(on=sid == "hp", pct=30)
    tab.set_boss_presence_source(lambda: state.boss)
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: state.frame)
    monkeypatch.setattr(tab, "_show_preview", lambda *a: None)
    monkeypatch.setattr(tab, "_play_alert_sound", lambda: state.sounds.append(state.now))
    monkeypatch.setattr(stat_bars_tab.time, "monotonic", lambda: state.now)
    try:
        yield tab, state, source
    finally:
        tab.shutdown()
        for overlay in tab._overlays.values():
            overlay.close()
            overlay.deleteLater()
        tab.close()
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_each_missing_band_cannot_rename_other_resources(pipeline, index):
    tab, state, original = pipeline
    tab._tick()
    before = {sid: ov._ratio for sid, ov in tab._overlays.items()}
    start, end = _bands(original)[index]
    state.frame[start:end] = 0
    np.testing.assert_array_equal(state.frame[:start], original[:start])
    np.testing.assert_array_equal(state.frame[end:], original[end:])
    assert len(read_stat_bars(state.frame)) == 2  # 진단용 잠정 판독은 유지
    assert read_stat_bars(state.frame, require_complete=True) == []
    state.now = 10
    tab._tick()
    assert {sid: ov._ratio for sid, ov in tab._overlays.items()} == before
    assert tab.value_label.text() == "현재 값: —"
    assert state.sounds == [] and not tab._alert_low_since
    state.frame = original
    state.now = 10.01
    tab._tick()
    assert state.sounds == []
    state.now = 10.42
    tab._tick()
    assert state.sounds == [10.42]


def test_four_bands_cannot_be_silently_truncated(pipeline):
    _, _, original = pipeline
    _, end = _bands(original)[0]
    extra = np.vstack([original, np.zeros((3, original.shape[1], 3), np.uint8), original[:end]])
    assert len(_bands(extra)) == 4
    assert read_stat_bars(extra, require_complete=True) == []


def test_first_partial_capture_does_not_show_default_full_hp(pipeline):
    tab, state, source = pipeline
    start, end = _bands(source)[0]
    state.frame[start:end] = 0
    tab._tick()
    assert all(not overlay.isVisible() for overlay in tab._overlays.values())
    assert tab.value_label.text() == "현재 값: —"


@pytest.mark.parametrize("interruption", ["capture", "inactive", "paused", "disabled", "no_region", "boss"])
@pytest.mark.parametrize("already_fired", [False, True])
def test_interruption_breaks_debounce_without_rearming(pipeline, interruption, already_fired):
    tab, state, source = pipeline
    tab._tick()
    if already_fired:
        state.now = .41
        tab._tick()
        assert state.sounds == [.41]
    else:
        assert tab._alert_low_since["hp"] == 0
    state.now = 10
    if interruption == "capture":
        state.frame = None
    elif interruption == "inactive":
        state.active = False
    elif interruption == "paused":
        tab.set_paused(True)
    elif interruption == "disabled":
        tab._on_enable(False)
    elif interruption == "no_region":
        tab._region = None
    else:
        state.boss = False
    tab._tick()
    assert not tab._alert_low_since
    assert tab._alert_armed["hp"] is (not already_fired)
    state.frame, state.active, state.boss = source, True, True
    tab._paused, tab._enabled = False, True
    tab._region = {"x": 0, "y": 0, "w": source.shape[1], "h": source.shape[0]}
    state.now = 10.01
    tab._tick()
    assert state.sounds == ([.41] if already_fired else [])
    state.now = 10.42
    tab._tick()
    assert state.sounds == ([.41] if already_fired else [10.42])


def test_recovery_rearms_after_unknown_interval(pipeline):
    tab, state, original = pipeline
    tab._tick()
    state.now = .41
    tab._tick()
    state.frame = None
    state.now = 10
    tab._tick()
    full = image_io.imread(SHOT.with_name("hp100_mp100_sta100_001.png"))
    assert full is not None
    state.frame = full
    state.now = 10.1
    tab._tick()
    assert tab._alert_armed["hp"]
    state.frame = original
    state.now = 11
    tab._tick()
    state.now = 11.41
    tab._tick()
    assert state.sounds == [.41, 11.41]
