"""버프 라이브 컨트롤러 (기획서 4.1 / 4.7).

FrameSource에서 버프 패널을 주기적으로 캡처 → BuffEngine.tick → 오버레이 갱신.
캡처·탐지는 백그라운드 스레드(UI 안 막음), 오버레이 갱신은 시그널로 메인 스레드에서.
FrameSource를 주입받으므로 Windows(dxcam)·개발(File) 모두 같은 코드로 동작.

포그라운드 감지(WindowWatcher): 게임(또는 자기 앱)이 활성일 때만 캡처·표시한다.
비활성이면 상태를 동결하고 오버레이를 숨긴다(엉뚱한 창을 캡처해 오탐하는 것 방지).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QPixmap

from ..capture.base import FrameSource
from ..system.window_watcher import AlwaysActiveWatcher, WindowWatcher
from ..tracker.engine import BuffEngine
from .overlay import BuffOverlay, OverlayItem, overlay_spec


class _TrackWorker(QThread):
    updated = Signal(list)  # list[OverlayEntry]
    alerted = Signal(list)  # list[buff_id]
    active_changed = Signal(bool)  # 포그라운드(게임/자기 앱) 활성 여부 변경

    def __init__(
        self,
        source: FrameSource,
        engine: BuffEngine,
        watcher: WindowWatcher,
        interval_ms: int = 200,
    ) -> None:
        super().__init__()
        self._source = source
        self._engine = engine
        self._watcher = watcher
        self._interval = interval_ms
        self._running = True
        self._active = True

    def run(self) -> None:
        while self._running:
            active = self._watcher.is_active()
            if active != self._active:
                self._active = active
                self.active_changed.emit(active)
            if not active:
                # 비활성: 캡처·탐지 안 함(상태 동결), 오버레이는 숨김 처리.
                self.msleep(self._interval)
                continue
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
        watcher: WindowWatcher | None = None,
    ) -> None:
        super().__init__()
        self._overlay = overlay
        self._catalog = catalog  # id -> BuffDef
        self._show_duration = show_duration
        self._on_alert = on_alert
        self._watcher = watcher or AlwaysActiveWatcher()
        self._worker: _TrackWorker | None = None
        self._items: list[OverlayItem] = []
        self._active = True

    def start(self, source: FrameSource, engine: BuffEngine) -> None:
        self.stop()
        self._worker = _TrackWorker(source, engine, self._watcher)
        self._worker.updated.connect(self._on_updated)
        self._worker.alerted.connect(self._on_alerted)
        self._worker.active_changed.connect(self._on_active_changed)
        self._worker.start()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None

    def set_show_duration(self, show_duration: dict[str, bool]) -> None:
        """지속시간 표시 설정 갱신(실행 중 폼 변경 반영)."""
        self._show_duration = show_duration

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
        self._items = self.build_items(entries)
        self._overlay.set_items(self._items)
        self._apply_visibility()

    def _on_active_changed(self, active: bool) -> None:
        self._active = active
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        # 비활성(게임·자기 앱이 포그라운드 아님) → 무조건 숨김.
        if not self._active:
            self._overlay.hide()
            return
        # 활성: 버프가 있거나, 해제(드래그) 상태면 플레이스홀더 유지.
        if self._items or not self._overlay.locked:
            self._overlay.show()
        else:
            self._overlay.hide()

    def _on_alerted(self, buff_ids) -> None:
        if self._on_alert is not None:
            self._on_alert(buff_ids)
