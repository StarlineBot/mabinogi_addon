"""Explicit QA probe: reuse actual selectors; mock only desktop snapshots."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.region_selector import RegionSelector


class Screen:
    def grabWindow(self, *args):
        shot = QPixmap(120, 120)
        shot.fill(QColor("black"))
        return shot


@pytest.mark.parametrize("mode", ["drag", "fixed", "crop"])
def test_actual_start_can_reuse_selector_after_close_and_escape(mode, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    output = tmp_path / "unused.png"
    selector = RegionSelector(
        save_path=output if mode == "crop" else None,
        fixed_size=(28, 23) if mode == "fixed" else None,
    )
    signals = QSignalSpy(selector.captured if mode == "crop" else selector.cancelled)
    selected = QSignalSpy(selector.selected)
    monkeypatch.setattr("mabinogi_addon.ui.region_selector.QGuiApplication.primaryScreen", lambda: Screen())
    try:
        for index in range(100):
            selector.start()
            app.processEvents()
            if index % 2:
                QTest.keyClick(selector, Qt.Key.Key_Escape)
            else:
                selector.close()
            selector.close()
            QTest.keyClick(selector, Qt.Key.Key_Escape)
            assert signals.count() == index + 1
            assert selected.count() == 0
            assert selector._finished and not selector.isVisible()
            if mode == "crop":
                assert signals.at(index) == [False]
        assert not output.exists()
    finally:
        selector.close()
        selector.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
