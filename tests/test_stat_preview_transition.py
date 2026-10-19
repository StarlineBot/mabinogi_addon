"""Preserve the independent real-page state-transition reproduction."""

from copy import deepcopy
import pytest
from test_navigation import window
from mabinogi_addon import config

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QWidget


@pytest.mark.parametrize("font_size", [12, 20])
@pytest.mark.parametrize("drain_each_control", [False, True])
def test_preview_repeated_scale_group_and_page_changes(window, font_size, tmp_path, drain_each_control):
    w, app = window
    tab = w.stat_bars_tab
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(font_size)
        widget.setFont(font)
    preview = tab.display_preview
    timers = set(w.findChildren(QTimer))
    tab._ensure_overlays()
    w._open_setup_feature("stat_bars")
    for cycle in range(3):
        for scale in (300, 50, 150):
            tab.scale_spin.setValue(scale)
            if drain_each_control:
                for _ in range(12): app.processEvents()
            for sid, check in tab._show_checks.items():
                check.setChecked(sid == "hp" or scale != 50)
                if drain_each_control:
                    for _ in range(12): app.processEvents()
            tab.diagnostics_btn.setChecked(cycle % 2 == 0)
            before = deepcopy(config._read_local_config())
            w._open_setup_feature("memo")
            w._open_setup_feature("stat_bars")
            for _ in range(12): app.processEvents()
            page = w._combat_pages["stat_bars"]
            assert page.horizontalScrollBar().maximum() == 0
            assert preview.widget().width() == preview.widget().sizeHint().width()
            assert preview.widget().width() <= preview.viewport().width()
            assert preview.viewport().height() >= preview.widget().height()
            assert preview.horizontalScrollBar().maximum() == 0
            assert not preview.horizontalScrollBar().isVisible()
            assert all(.5 <= bar._scale <= scale / 100 for bar in tab._preview_bars.values())
            assert all(bar._scale == scale / 100 for bar in tab._overlays.values())
            assert config._read_local_config() == before
            assert set(w.findChildren(QTimer)) == timers
    assert w.grab().save(str(tmp_path / f"preview-history-{font_size}.png"))


def test_layout_burst_coalesces_and_idle_does_not_poll(window):
    w, app = window
    w._open_setup_feature("stat_bars")
    preview = w.stat_bars_tab.display_preview
    for _ in range(12):
        app.processEvents()
    calls = []
    original = preview.fit_content
    def count():
        calls.append(1)
        original()
    preview._fit_timer.timeout.disconnect()
    preview._fit_timer.timeout.connect(count)
    for _ in range(100):
        QCoreApplication.sendEvent(preview.widget(), QEvent(QEvent.Type.LayoutRequest))
    assert preview._fit_timer.isActive()
    for _ in range(12):
        app.processEvents()
    assert calls == [1]
    assert not preview._fit_timer.isActive()
    for _ in range(12):
        app.processEvents()
    assert calls == [1]
    QCoreApplication.sendEvent(preview.widget(), QEvent(QEvent.Type.LayoutRequest))
    assert preview._fit_timer.isActive()
    w._open_setup_feature("memo")
    assert not preview._fit_timer.isActive()
    for _ in range(12):
        app.processEvents()
    assert calls == [1]
    w._open_setup_feature("stat_bars")
    for _ in range(12):
        app.processEvents()
    QCoreApplication.sendEvent(preview.widget(), QEvent(QEvent.Type.LayoutRequest))
    assert preview._fit_timer.isActive()
    w._force_quit = True
    w.close()
    assert not preview._fit_timer.isActive()
    closed_calls = len(calls)
    for _ in range(12):
        app.processEvents()
    assert len(calls) == closed_calls
