"""Every selector exit reports exactly one outcome, including window-manager close."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.region_selector import RegionSelector
from scripts.qa_dorcha_selector_close_stall import (
    runtime,
    test_explicit_escape_resumes_tracking,
    test_regular_close_event_must_not_permanently_stop_tracking,
    test_shutdown_never_restarts_timer_from_late_cancel,
    test_successful_selection_resumes_tracking,
)


@pytest.mark.parametrize("mode,exit_kind", [
    (mode, kind) for mode in ("drag", "fixed", "crop")
    for kind in ("close", "escape", "selected", "tiny")
    if not (mode == "fixed" and kind == "tiny")
])
def test_exit_signal_is_single_and_selection_is_not_cancellation(tmp_path, mode, exit_kind):
    app = QApplication.instance() or QApplication([])
    output = tmp_path / "아이콘.png"
    selector = RegionSelector(save_path=output if mode == "crop" else None,
                              fixed_size=(28, 23) if mode == "fixed" else None)
    selector._shot = QPixmap(100, 100)
    selector._shot.fill(QColor("red"))
    selected = QSignalSpy(selector.selected)
    cancelled = QSignalSpy(selector.cancelled)
    captured = QSignalSpy(selector.captured)
    try:
        selector.show()
        app.processEvents()
        if exit_kind == "close":
            selector.close()
        elif exit_kind == "escape":
            QTest.keyClick(selector, Qt.Key.Key_Escape)
        else:
            start = QPoint(20, 20)
            end = start if exit_kind == "tiny" else QPoint(35, 35)
            QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(selector, end)
            QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=end)
        app.processEvents()
        # Repeated shutdown/key delivery must not deliver another result.
        selector.close()
        QTest.keyClick(selector, Qt.Key.Key_Escape)
        app.processEvents()
        assert not selector.isVisible()
        if mode == "crop":
            assert (selected.count(), cancelled.count(), captured.count()) == (0, 0, 1)
            assert captured.at(0) == [exit_kind == "selected"]
            assert output.exists() is (exit_kind == "selected")
        else:
            assert captured.count() == 0
            assert (selected.count(), cancelled.count()) == (
                (1, 0) if exit_kind == "selected" else (0, 1))
            if mode == "fixed" and exit_kind == "selected":
                assert selected.at(0)[2:] == [28, 23]
    finally:
        selector.close()
        selector.deleteLater()


def test_failed_crop_is_reported_once(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    selector = RegionSelector(save_path=tmp_path / "cannot-save.png")
    monkeypatch.setattr(selector, "_save_crop", lambda rect: False)
    captured = QSignalSpy(selector.captured)
    cancelled = QSignalSpy(selector.cancelled)
    try:
        selector.show()
        app.processEvents()
        QTest.mousePress(selector, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseMove(selector, QPoint(30, 30))
        QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        selector.close()
        assert captured.count() == 1 and captured.at(0) == [False]
        assert cancelled.count() == 0
    finally:
        selector.close()
        selector.deleteLater()


def test_dorcha_cancel_preserves_a_previously_stopped_timer(runtime):
    app, tab = runtime
    tab._timer.stop()
    tab._on_region()
    tab._selector.close()
    app.processEvents()
    assert not tab._timer.isActive()


def test_dorcha_repeated_close_restores_without_saving_region(runtime):
    app, tab = runtime
    before = dict(tab._region)
    timer = tab._timer
    for _ in range(100):
        tab._on_region()
        assert not timer.isActive()
        tab._selector.close()
        app.processEvents()
        assert timer is tab._timer and timer.isActive()
        assert tab._region == before
