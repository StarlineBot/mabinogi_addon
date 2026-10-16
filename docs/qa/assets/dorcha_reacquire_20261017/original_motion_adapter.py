"""Keep original repro inputs/assertions; replace only OS target and Qt wait boundary."""

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QTest

from mabinogi_addon.ui.dorcha_tab import DorchaTab
from scripts.qa_dorcha_moved_ui import test_moving_source_must_be_reacquired_for_new_requirement as original_motion


def test_original_motion_in_application_event_loop(monkeypatch):
    monkeypatch.setattr(DorchaTab, "_search_target", lambda self: (1, 1, 0, 0, 260, 180))

    def wait(milliseconds):
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    monkeypatch.setattr(QTest, "qWait", wait)
    original_motion(monkeypatch)
