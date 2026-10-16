"""B안의 실제 오버레이·경고 경로, 저장 좌표와 제한된 갱신을 검증한다."""

from types import SimpleNamespace
import time

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui import grid
from mabinogi_addon.ui.stat_overlay import StatBarOverlay, shake_offset
from test_stat_bars_stability import pipeline


def readings(hp=30, mp=85, sta=85):
    return {sid: SimpleNamespace(ratio=value / 100)
            for sid, value in zip(("hp", "mp", "sta"), (hp, mp, sta))}


def sample(pipeline, now, **values):
    tab, state, _ = pipeline
    state.now = now
    tab._apply_visibility()
    tab._check_alerts(readings(**values), now)
    return tab._overlays


def test_only_low_bars_animate_after_debounce_without_restarting_or_replaying_sound(pipeline):
    tab, state, _ = pipeline
    tab._bars_cfg["mp"]["alert"].update(on=True, pct=30)
    for t in (0, .2, .399):
        overlays = sample(pipeline, t, mp=30)
        assert not any(ov.warning_active for ov in overlays.values())
    overlays = sample(pipeline, .4, mp=30)
    assert {sid for sid, ov in overlays.items() if ov.warning_active} == {"hp", "mp"}
    start = overlays["hp"]._warning_started
    for index in range(3, 21):
        sample(pipeline, index * .2, mp=30)
        assert overlays["hp"]._warning_started == start
    assert state.sounds == [.4]
    sample(pipeline, 4.2, hp=31, mp=30)
    assert not overlays["hp"].warning_active and overlays["hp"]._shake_offset == 0
    assert overlays["mp"].warning_active
    sample(pipeline, 4.4, mp=30)
    sample(pipeline, 4.6, mp=30)
    sample(pipeline, 4.81, mp=30)
    assert state.sounds == [.4, 4.81]


def test_visual_warning_is_independent_of_sound(pipeline):
    tab, state, _ = pipeline
    tab._alert_sound_on = False
    sample(pipeline, 0)
    overlays = sample(pipeline, .4)
    assert overlays["hp"].warning_active and state.sounds == []


def test_three_low_bars_and_short_low_pulse(pipeline):
    tab, _, _ = pipeline
    for bar in tab._bars_cfg.values():
        bar["alert"].update(on=True, pct=30)
    sample(pipeline, 0, mp=30, sta=30)
    sample(pipeline, .2, mp=30, sta=30)
    sample(pipeline, .3, hp=31, mp=31, sta=31)
    sample(pipeline, .4, mp=30, sta=30)
    overlays = sample(pipeline, .79, mp=30, sta=30)
    assert not any(ov.warning_active for ov in overlays.values())
    sample(pipeline, .81, mp=30, sta=30)
    assert all(ov.warning_active for ov in overlays.values())


@pytest.mark.parametrize("reason", ["capture", "partial", "inactive", "paused", "disabled",
                                   "no_region", "boss", "logout", "show", "alert", "region", "shutdown"])
def test_interruptions_clear_effect_timer_and_require_new_debounce(pipeline, monkeypatch, reason):
    tab, state, _ = pipeline
    state.now = 0
    tab._tick()
    state.now = .4
    tab._tick()
    ov = tab._overlays["hp"]
    assert ov.warning_active
    state.now = .5
    if reason == "capture":
        state.frame = None
    elif reason == "partial":
        state.frame = np.zeros_like(state.frame)
    elif reason == "inactive":
        state.active = False
    elif reason == "paused":
        tab.set_paused(True)
    elif reason == "disabled":
        tab._on_enable(False)
    elif reason == "no_region":
        tab._region = None
    elif reason == "boss":
        state.boss = False
    elif reason == "logout":
        monkeypatch.setattr(config, "load_discord_user", lambda: None)
    elif reason == "show":
        tab._show_checks["hp"].setChecked(False)
    elif reason == "alert":
        tab._bars_cfg["hp"]["alert"]["on"] = False
        tab._update_visual_alerts(state.now)
    elif reason == "region":
        monkeypatch.setattr(tab, "_flash_region", lambda: None)
        tab._on_selected(1, 2, 200, 46)
    else:
        tab.shutdown()
    if reason not in ("region", "shutdown"):
        tab._tick()
    assert not ov.warning_active and not ov._warning_timer.isActive()
    assert ov._shake_offset == 0 and "hp" not in tab._visual_low_since
    assert state.sounds == [.4]


def test_hide_resume_rechecks_instead_of_restoring_phase(pipeline):
    tab, state, _ = pipeline
    sample(pipeline, 0)
    ov = sample(pipeline, .4)["hp"]
    state.now = .45
    ov._advance_warning()
    assert ov._shake_offset != 0
    ov.hide()
    assert not ov._warning_timer.isActive()
    sample(pipeline, .5)
    assert not ov.warning_active
    sample(pipeline, .91)
    assert ov.warning_active and ov._warning_started == .91


def test_stale_reading_stops_even_if_main_capture_loop_does_not_tick(pipeline):
    tab, state, _ = pipeline
    sample(pipeline, 0)
    ov = sample(pipeline, .4)["hp"]
    state.now = .45
    ov._advance_warning()
    assert ov._shake_offset != 0
    state.now = 1.06
    ov._advance_warning()
    assert not ov.warning_active and ov._shake_offset == 0
    assert not ov._warning_timer.isActive()
    sample(pipeline, 1.07)
    assert not ov.warning_active
    sample(pipeline, 1.48)
    assert ov.warning_active


def test_threshold_and_alert_changes_use_cached_sample_without_new_capture(pipeline, monkeypatch):
    tab, state, _ = pipeline
    # Synchronize controls with the fixture without manufacturing settings events.
    for sid, chk in tab._alert_checks.items():
        chk.blockSignals(True)
        chk.setChecked(sid == "hp")
        chk.blockSignals(False)
    sample(pipeline, 0)
    ov = sample(pipeline, .4)["hp"]
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: pytest.fail("settings must not capture"))
    state.now = .45
    tab._alert_spins["hp"].setValue(29)
    assert not ov.warning_active and ov._shake_offset == 0
    tab._alert_spins["hp"].setValue(30)
    assert not ov.warning_active
    sample(pipeline, .86)
    assert ov.warning_active
    state.boss = False
    tab.alert_sound_chk.setChecked(not tab.alert_sound_chk.isChecked())
    assert not ov.warning_active
    assert state.sounds == [.4]


@pytest.mark.parametrize("bad", [None, float("nan"), -1, 1.1])
def test_invalid_sample_cannot_sustain_warning(pipeline, bad):
    tab, _, _ = pipeline
    sample(pipeline, 0)
    ov = sample(pipeline, .4)["hp"]
    broken = readings()
    if bad is None:
        del broken["sta"]
    else:
        broken["sta"].ratio = bad
    tab._check_alerts(broken, .5)
    assert not ov.warning_active and not tab._visual_low_since


def test_approved_waveform_rest_and_scale():
    assert shake_offset(.05, 1) == pytest.approx(3)
    assert shake_offset(.15, 1) == pytest.approx(-3)
    assert shake_offset(.25, 1) == pytest.approx(3)
    assert shake_offset(.35, 1) == pytest.approx(-3)
    for value in (.4, .6, 1, 1.79):
        assert shake_offset(value, 1) == 0
    assert shake_offset(1.85, 1.5) == pytest.approx(4.5)


def image_pixels(ov):
    image = QImage(ov.size(), QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    ov.render(image)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4).copy()


@pytest.mark.parametrize("scale", [.5, 1, 1.5, 3])
def test_drawing_gutter_preserves_pixels_colors_size_and_anchor(scale):
    app = QApplication.instance() or QApplication([])
    ov = StatBarOverlay("hp", scale)
    try:
        ov.set_locked(True)
        ov.move_base(QPoint(-1200, 100))
        ov.set_value(.3)
        base = ov.base_position
        geometry = ov.geometry()
        stationary = image_pixels(ov)
        mass = stationary.sum(axis=(0, 1))
        x0 = np.where(stationary[:, :, 3] > 0)[1].min()
        for offset in (-int(3 * scale), int(3 * scale)):
            ov._shake_offset = offset
            moved = image_pixels(ov)
            assert ov.base_position == base and ov.geometry() == geometry
            np.testing.assert_array_equal(moved.sum(axis=(0, 1)), mass)
            assert np.where(moved[:, :, 3] > 0)[1].min() == x0 + offset
            assert not np.any(moved[:, (0, -1), 3])
    finally:
        ov.close()
        ov.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("snap", [False, True])
def test_save_scale_lock_and_drag_preserve_baseline_during_shake(pipeline, monkeypatch, snap):
    tab, state, _ = pipeline
    sample(pipeline, 0)
    ov = sample(pipeline, .4)["hp"]
    ov.move_base(QPoint(-800, 250))
    state.now = .45
    ov._advance_warning()
    assert ov._shake_offset != 0
    for scale in (50, 300, 150):
        tab._on_scale(scale)
        assert ov.base_position == QPoint(-800, 250)
        assert abs(ov._shake_offset) <= 3 * scale / 100
        tab._set_locked_all(True)
        assert ov.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert config.load_stat_bars()["bars"]["hp"]["pos"] == {"x": -800, "y": 250}
    ov.set_locked(False)
    monkeypatch.setattr(grid, "enabled", lambda: snap)
    monkeypatch.setattr(grid, "size", lambda: 10)
    monkeypatch.setattr(grid, "show_guide", lambda: None)
    monkeypatch.setattr(grid, "hide_guide", lambda: None)
    monkeypatch.setattr(grid, "snap", lambda point, size: QPoint(round(point.x() / size) * size,
                                                               round(point.y() / size) * size))
    point = ov.base_position + QPoint(20, 10)
    event = lambda pos: SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton,
                                       globalPosition=lambda: QPointF(pos), accept=lambda: None)
    ov.mousePressEvent(event(point))
    ov.mouseMoveEvent(event(point + QPoint(37, 11)))
    ov.mouseReleaseEvent(event(point + QPoint(37, 11)))
    expected = QPoint(-760, 260) if snap else QPoint(-763, 261)
    assert ov.base_position == expected
    assert config.load_stat_bars()["bars"]["hp"]["pos"] == {"x": expected.x(), "y": expected.y()}
    state.now = .6
    sample(pipeline, .6, hp=80)
    assert ov.base_position == expected and ov._shake_offset == 0


def test_long_repetition_keeps_three_idle_timers_and_capture_count(pipeline, monkeypatch):
    tab, state, _ = pipeline
    captures = []
    original_grab = tab._grab_rect
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: (captures.append(1), original_grab(*a))[1])
    for index in range(500):
        state.now = index * .2
        tab._tick()
        if index % 10 == 0:
            state.active = False
            tab._apply_visibility()
            assert all(not ov._warning_timer.isActive() for ov in tab._overlays.values())
            state.active = True
    assert len(captures) == 500
    assert len(tab._overlays) == 3
    assert all(len(ov.findChildren(QTimer)) == 1 for ov in tab._overlays.values())
    sample(pipeline, 100.2, hp=80)
    assert all(not ov._warning_timer.isActive() for ov in tab._overlays.values())
    assert state.sounds == [.4]


def test_rest_schedules_one_wakeup_not_continuous_frames(pipeline):
    _, state, _ = pipeline
    sample(pipeline, 0)
    ov = sample(pipeline, .4)["hp"]
    sample(pipeline, .6)
    sample(pipeline, .8)
    state.now = .81
    ov._advance_warning()
    assert ov._shake_offset == 0
    assert 600 < ov._warning_timer.interval() <= 650


def test_real_qt_timer_moves_drawing_then_stops_when_hidden(monkeypatch):
    app = QApplication.instance() or QApplication([])
    ov = StatBarOverlay("hp")
    offsets = []
    update = ov.update
    monkeypatch.setattr(ov, "update", lambda: (offsets.append(ov._shake_offset), update())[1])
    try:
        ov.set_locked(True)
        ov.show()
        app.processEvents()
        geometry = ov.geometry()
        ov.set_warning(True, time.monotonic())
        QTest.qWait(150)
        assert ov.warning_active and any(abs(offset) > 1 for offset in offsets)
        assert ov.geometry() == geometry
        ov.hide()
        assert not ov.warning_active and not ov._warning_timer.isActive()
        app.processEvents()
        count = len(offsets)
        QTest.qWait(100)
        assert len(offsets) == count
        ov.show()
        assert not ov.warning_active
        ov.close()
        assert not ov._warning_timer.isActive()
    finally:
        ov.close()
        ov.deleteLater()
        app.processEvents()
