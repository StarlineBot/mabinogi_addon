"""Bounded asynchronous completion; return early without starving Python workers."""

from time import monotonic

from PySide6.QtCore import QEventLoop, QTimer


def until(predicate, timeout_ms=1000):
    deadline = monotonic() + timeout_ms/1000
    while not predicate():
        assert monotonic() < deadline, 'asynchronous operation did not complete'
        loop = QEventLoop()
        QTimer.singleShot(5, loop.quit)
        loop.exec()
