"""Actual GDI pixels and HWND affinity, without a game or synthetic capture backend."""

import ctypes
from ctypes import wintypes
import sys

import pytest

pytestmark = [pytest.mark.windows_integration,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows capture exclusion")]


@pytest.mark.parametrize("layered", [False, True])
def test_exclusion_reveals_covered_pixels_without_hiding_or_activating_window(layered):
    import mss
    import numpy as np
    import win32con
    import win32gui
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QApplication, QWidget
    from mabinogi_addon.system import capture_exclusion

    assert capture_exclusion.available(), "Windows runner must support true capture exclusion"
    app = QApplication.instance() or QApplication([])

    class Panel(QWidget):
        def __init__(self, color):
            super().__init__()
            self.color = QColor(color)

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), self.color)
            painter.end()

    source, blocker = Panel("#197b45"), Panel("#d53b34")
    user, dwm = capture_exclusion._api()

    def affinity(hwnd):
        value = wintypes.DWORD()
        assert user.GetWindowDisplayAffinity(hwnd, ctypes.byref(value))
        return value.value

    def flush():
        app.processEvents()
        assert dwm.DwmFlush() == 0

    try:
        area = app.primaryScreen().availableGeometry()
        for widget in (source, blocker):
            widget.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                  | Qt.WindowType.WindowStaysOnTopHint)
            widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            widget.setGeometry(area.x()+40, area.y()+40, 160, 120)
        blocker.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, layered)
        source.show()
        flush()
        left, top, right, bottom = win32gui.GetWindowRect(int(source.winId()))
        x, y = (left+right)//2-12, (top+bottom)//2-12
        box = (x, y, 24, 24)
        with mss.mss() as capture:
            def pixels():
                return np.array(capture.grab(dict(left=x, top=y, width=24, height=24)))[:, :, :3]

            baseline = pixels()
            blocker.show()
            hwnd = int(blocker.winId())
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                 win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
            flush()
            covered = pixels()
            assert not np.array_equal(baseline, covered)
            previous = affinity(hwnd)
            foreground = win32gui.GetForegroundWindow()
            geometry = win32gui.GetWindowRect(hwnd)
            for raises in (False, True):
                try:
                    with capture_exclusion.excluding_windows([hwnd], box):
                        assert affinity(hwnd) == 0x11
                        assert blocker.isVisible() and win32gui.IsWindowVisible(hwnd)
                        assert np.array_equal(pixels(), baseline)
                        if raises:
                            raise OSError("capture failure control")
                except OSError:
                    assert raises
                assert affinity(hwnd) == previous
                assert win32gui.GetForegroundWindow() == foreground
                assert win32gui.GetWindowRect(hwnd) == geometry
                assert blocker.isVisible() and np.array_equal(pixels(), covered)
    finally:
        for widget in (blocker, source):
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
