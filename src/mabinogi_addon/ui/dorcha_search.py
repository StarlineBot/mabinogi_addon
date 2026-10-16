"""One bounded, cancellable detector job. Capture and widget updates stay on the UI thread."""

import time

from PySide6.QtCore import QThread

from ..detect.dorcha_anchor import locate_dorcha


class DorchaSearch(QThread):
    def __init__(self, frame, target, epoch):
        super().__init__()
        self.frame = frame
        self.target = target
        self.epoch = epoch
        self.box = None
        self.error = None
        self.elapsed = 0.0

    def run(self):
        started = time.monotonic()
        try:
            self.box = locate_dorcha(self.frame, cancelled=self.isInterruptionRequested)
        except Exception as exc:
            self.error = type(exc).__name__
        finally:
            self.frame = None
            self.elapsed = time.monotonic() - started
