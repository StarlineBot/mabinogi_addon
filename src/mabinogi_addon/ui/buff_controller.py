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
    foreground_changed = Signal(bool, bool)  # (게임 활성, 자기 앱 활성)

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
        self._fg: tuple[bool, bool] | None = None

    def run(self) -> None:
        while self._running:
            game = self._watcher.is_game_active()
            selfa = self._watcher.is_self_active()
            if (game, selfa) != self._fg:
                self._fg = (game, selfa)
                self.foreground_changed.emit(game, selfa)
            if game:
                # 캡처·탐지는 게임이 포그라운드일 때만(다른 창을 캡처해 오탐 방지).
                region = self._source.grab()
                if region is not None:
                    result = self._engine.tick(region, time.monotonic())
                    self.updated.emit(result.entries)
                    if result.alerts:
                        self.alerted.emit(result.alerts)
            self._sleep()

    def _sleep(self) -> None:
        """주기를 작게 쪼개 자며 _running을 자주 확인(종료 요청 즉시 반응)."""
        step = 30
        waited = 0
        while self._running and waited < self._interval:
            self.msleep(min(step, self._interval - waited))
            waited += step

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
        self._source: FrameSource | None = None
        self._items: list[OverlayItem] = []
        self._game_active = True  # 게임 포그라운드
        self._self_active = False  # 우리 앱 포그라운드
        self._last_remaining: dict[str, float] = {}  # 표시 평활용 직전 표시값

    def start(
        self, source: FrameSource, engine: BuffEngine, interval_ms: int = 200
    ) -> None:
        self.stop()
        self._source = source
        self._worker = _TrackWorker(source, engine, self._watcher, interval_ms)
        self._worker.updated.connect(self._on_updated)
        self._worker.alerted.connect(self._on_alerted)
        self._worker.foreground_changed.connect(self._on_foreground_changed)
        self._worker.start()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None
        # 워커를 멈춘 뒤(캡처 중 아님) 소스를 닫는다 — dxcam 카메라를 제어된 시점에 해제
        # (안 닫으면 프로세스 종료 시점에 정리되며 종료가 느려진다).
        if self._source is not None:
            self._source.close()
            self._source = None

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

    def _on_foreground_changed(self, game: bool, selfa: bool) -> None:
        self._game_active = game
        self._self_active = selfa
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        locked = self._overlay.locked
        if self._game_active:
            # 게임이 포그라운드: 버프가 있거나, 해제(편집) 상태면 플레이스홀더 유지.
            show = bool(self._items) or not locked
        elif self._self_active and not locked:
            # 게임이 아니어도 '편집(해제)' 중엔 우리 앱 위에서 위치 조정 가능하게.
            show = True
        else:
            # 고정 상태인데 게임이 포그라운드 아님(앱·다른 창) → 숨김.
            show = False
        self._overlay.show() if show else self._overlay.hide()

    def _on_alerted(self, buff_ids) -> None:
        if self._on_alert is not None:
            self._on_alert(buff_ids)
