"""Manual update state in the shared Qt startup layout, without dialogue."""

from PySide6.QtCore import QMetaObject, QThread, Qt, Slot

from .splash import Splash


class UpdateSplash(Splash):
    def __init__(self, version: str) -> None:
        self.version = version
        self._downloading = True
        super().__init__(typing=False, status=self._download_text(0))

    def _download_text(self, percent: int) -> str:
        return f"새 버전 v{self.version} 받는 중 {percent}%"

    def download_progress(self, percent: int) -> None:
        if self._downloading:
            self.step(percent, self._download_text(percent))

    def prepare_apply(self) -> None:
        # Marshal synchronously: the existing worker must not replace files before
        # the GUI has painted the real transition. No sleep, polling or new worker.
        if QThread.isMainThread():
            self._show_applying()
        else:
            QMetaObject.invokeMethod(
                self, "_show_applying", Qt.ConnectionType.BlockingQueuedConnection
            )

    @Slot()
    def _show_applying(self) -> None:
        self._downloading = False
        self.step(100, "업데이트 적용 중")
        self.repaint()
