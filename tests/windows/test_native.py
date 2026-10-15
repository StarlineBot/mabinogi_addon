"""전용 Windows 단계에서만 실행하는 실제 네이티브 경계 검사. 게임 조작은 하지 않는다."""

import sys

import pytest

pytestmark = [pytest.mark.windows_integration,
              pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows")]


def test_native_dependencies_and_small_desktop_capture():
    import dxcam
    import mss
    import numpy as np
    import win32gui
    import win32process

    assert callable(dxcam.create) and callable(win32process.GetWindowThreadProcessId)
    assert callable(win32gui.IsWindow)
    with mss.mss() as source:
        monitor = source.monitors[1]
        shot = source.grab({"left": monitor["left"], "top": monitor["top"], "width": 8, "height": 8})
        assert np.asarray(shot).shape == (8, 8, 4)


def test_native_audio_objects_are_created_muted_and_disposed():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QMediaPlayer
    from shiboken6 import isValid
    from mabinogi_addon.ui.notifier import SoundNotifier

    app = QApplication.instance() or QApplication([])
    notifier = SoundNotifier({}, volume=0)
    player = notifier._player
    assert isinstance(player, QMediaPlayer)
    assert notifier._audio is not None
    notifier._audio.setMuted(True)
    player.stop()
    notifier.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not isValid(player)


def test_real_hwnd_is_destroyed_after_widget_cleanup():
    import win32gui
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setWindowTitle("Windows integration")
    try:
        window.show()
        app.processEvents()
        hwnd = int(window.winId())
        assert win32gui.IsWindow(hwnd)
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not win32gui.IsWindow(hwnd)
