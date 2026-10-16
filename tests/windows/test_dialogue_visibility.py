"""실제 HWND/DWM/Z-order 확인. 캡처·오디오·외부 통신은 사용하지 않는다."""

import sys
import pytest

pytestmark = [pytest.mark.windows_integration,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows HWND integration")]


def test_real_window_occlusion_without_foreground_requirement():
    import ctypes
    import win32con
    import win32gui
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from mabinogi_addon.system.dialogue_visibility import exposed

    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    blocker = QWidget()
    try:
        area = app.primaryScreen().availableGeometry()
        owner.setGeometry(area.x() + 10, area.y() + 10, 200, 160)
        owner.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        owner.show()
        app.processEvents()
        hwnd = int(owner.winId())
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        ctypes.windll.dwmapi.DwmFlush()
        target = [(20, 20, 60, 40)]
        assert exposed(hwnd, target, (owner.width(), owner.height()))
        point = owner.mapToGlobal(owner.rect().topLeft())
        blocker.setGeometry(point.x(), point.y(), 150, 120)
        blocker.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        blocker.show()
        app.processEvents()
        win32gui.SetWindowPos(int(blocker.winId()), win32con.HWND_TOPMOST, 0, 0, 0, 0,
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        ctypes.windll.dwmapi.DwmFlush()
        assert not exposed(hwnd, target, (owner.width(), owner.height()))
        blocker.hide()
        app.processEvents()
        ctypes.windll.dwmapi.DwmFlush()
        assert exposed(hwnd, target, (owner.width(), owner.height()))
        owner.hide()
        assert not exposed(hwnd, target, (owner.width(), owner.height()))
    finally:
        blocker.close()
        owner.close()
