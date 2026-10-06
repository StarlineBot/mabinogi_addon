"""버프 라이브 컨트롤러 (기획서 4.1).

FrameSource에서 버프 패널을 주기적으로 캡처 → BuffEngine.tick → 오버레이 갱신.
캡처·탐지는 백그라운드 스레드(UI 안 막음), 오버레이 갱신은 시그널로 메인 스레드에서.
FrameSource를 주입받으므로 Windows(dxcam)·개발(File) 모두 같은 코드로 동작.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QPixmap

from ..capture.base import FrameSource
from ..tracker.engine import BuffEngine
from .overlay import BuffOverlay, OverlayItem, overlay_spec


class _TrackWorker(QThread):
    updated = Signal(list)  # list[OverlayEntry]
    alerted = Signal(list)  # list[buff_id]

    def __init__(
        self, source: FrameSource, engine: BuffEngine, interval_ms: int = 200
    ) -> None:
        super().__init__()
        self._source = source
        self._engine = engine
        self._interval = interval_ms
        self._running = True

    def run(self) -> None:
        while self._running:
            region = self._source.grab()
            if region is not None:
                result = self._engine.tick(region, time.monotonic())
                self.updated.emit(result.entries)
                if result.alerts:
                    self.alerted.emit(result.alerts)
            self.msleep(self._interval)

    def stop(self) -> None:
        self._running = False


class BuffController(QObject):
    def __init__(
        self,
        overlay: BuffOverlay,
        catalog: dict,
        show_duration: dict[str, bool],
        on_alert=None,
    ) -> None:
        super().__init__()
        self._overlay = overlay
        self._catalog = catalog  # id -> BuffDef
        self._show_duration = show_duration
        self._on_alert = on_alert
        self._worker: _TrackWorker | None = None

    def start(self, source: FrameSource, engine: BuffEngine) -> None:
        self.stop()
        self._worker = _TrackWorker(source, engine)
        self._worker.updated.connect(self._on_updated)
        self._worker.alerted.connect(self._on_alerted)
        self._worker.start()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None

    def build_items(self, entries) -> list[OverlayItem]:
        items: list[OverlayItem] = []
        for buff_id, text, blinking in overlay_spec(entries, self._show_duration):
            buff = self._catalog.get(buff_id)
            if buff is None:
                continue
            pixmap = QPixmap(str(buff.display_image or buff.match_icon))
            items.append(OverlayItem(pixmap, text, blinking))
        return items

    def _on_updated(self, entries) -> None:
        items = self.build_items(entries)
        self._overlay.set_items(items)
        if items:
            self._overlay.show()
        else:
            self._overlay.hide()

    def _on_alerted(self, buff_ids) -> None:
        if self._on_alert is not None:
            self._on_alert(buff_ids)
