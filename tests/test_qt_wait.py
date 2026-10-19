import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from test_support.qt_wait import until


def test_wait_runs_events_until_actual_completion():
    app=QApplication.instance() or QApplication([])
    completed=[]
    timer=QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda:completed.append(True))
    try:
        timer.start(10)
        until(lambda:bool(completed),timeout_ms=500)
        assert completed==[True] and not timer.isActive()
    finally:
        timer.stop()
        timer.deleteLater()
        app.processEvents()


def test_wait_fails_if_completion_never_occurs():
    app=QApplication.instance() or QApplication([])
    with pytest.raises(AssertionError,match='did not complete'):
        until(lambda:False,timeout_ms=10)
