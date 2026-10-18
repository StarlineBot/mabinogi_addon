"""Preserve the independent real-page state-transition reproduction."""

from scripts.qa_stat_preview_transition_20261018 import (
    window,
    test_preview_repeated_scale_group_and_page_changes,
)

from PySide6.QtCore import QCoreApplication, QEvent


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
