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

# 표시 평활: 판독 지터로 남은 시간이 이 값 이하만큼 '올라가는' 건 무시(단조 감소).
# 게임이 만료 직전 숫자를 깜빡이면 일부 프레임을 못 읽어 7↔6으로 튀는 걸 막는다.
# 실제 연장(유의미한 증가)은 이 값보다 크므로 그대로 반영된다.
_SMOOTH_EPS = 1.5


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
        blink_enabled: dict[str, bool] | None = None,
    ) -> None:
        super().__init__()
        self._overlay = overlay
        self._catalog = catalog  # id -> BuffDef
        self._show_duration = show_duration
        self._blink_enabled = blink_enabled or {}
        self._on_alert = on_alert
        self._watcher = watcher or AlwaysActiveWatcher()
        self._worker: _TrackWorker | None = None
        self._items: list[OverlayItem] = []
        self._active = True
        self._last_remaining: dict[str, float] = {}  # 표시 평활용 직전 표시값

    def start(
        self, source: FrameSource, engine: BuffEngine, interval_ms: int = 200
    ) -> None:
        self.stop()
        self._worker = _TrackWorker(source, engine, self._watcher, interval_ms)
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

    def set_blink_enabled(self, blink_enabled: dict[str, bool]) -> None:
        """점멸 설정 갱신(실행 중 폼 변경 반영)."""
        self._blink_enabled = blink_enabled

    def build_items(self, entries) -> list[OverlayItem]:
        items: list[OverlayItem] = []
        for buff_id, text, blinking in overlay_spec(entries, self._show_duration):
            buff = self._catalog.get(buff_id)
            if buff is None:
                continue
            # 임박(alerting)이어도 '점멸' 끈 버프는 깜빡이지 않는다.
            blink = blinking and self._blink_enabled.get(buff_id, True)
            pixmap = QPixmap(str(buff.display_image or buff.match_icon))
            items.append(OverlayItem(pixmap, text, blink))
        return items

    def _smooth(self, entries) -> None:
        """판독 지터로 인한 작은 상승을 억제해 표시 시간을 단조 감소시킨다."""
        seen: set[str] = set()
        for e in entries:
            if e.remaining is None:
                continue
            seen.add(e.buff_id)
            last = self._last_remaining.get(e.buff_id)
            # 직전보다 _SMOOTH_EPS 이하로만 올라가면(지터) 직전값 유지. 큰 증가(연장)는 통과.
            if last is not None and last < e.remaining <= last + _SMOOTH_EPS:
                e.remaining = last
            self._last_remaining[e.buff_id] = e.remaining
        for bid in [b for b in self._last_remaining if b not in seen]:
            del self._last_remaining[bid]  # 사라진 버프는 재등장 시 초기화

    def _on_updated(self, entries) -> None:
        self._smooth(entries)
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
