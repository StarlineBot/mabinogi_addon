"""마우스 커서 표시 오버레이(마우스 커서 명세 3·4절).

- 원·스코프: 커서 크기만 한 투명 창이 커서를 따라 움직인다.
- 스코프(화면 선): 1px 두께 화면 길이 창 2개가 커서 줄·칸을 따라간다(화면 전체 창 없음).
- 꼬리: 최근 꼬리 범위만큼만 덮는 투명 창을 다시 그린다. 커서가 멈춰 꼬리가 다 사라지면 다시 그리지 않는다.
- 모든 창은 클릭 통과·항상 위·포커스 안 뺏음. 게임이 앞에 있고 일시정지가 아닐 때만 보인다.
- 커서 위치는 초당 60번 읽기만 한다(system.cursor). 입력은 만들지 않는다.
"""

from __future__ import annotations

import logging
import time
from collections import Counter

from PySide6.QtCore import QObject, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from .. import config
from ..cursor_fx import PARTICLE_KINDS, SHAKE_SCALE, TAIL_SECONDS, Particles, particle_bounds, ShakeDetector, Trail, bounds, clean_settings, shake_scale, sparkle_multicolor
from ..system import cursor as cursor_sys
from .cursor_paint import paint_particles, paint_ring, paint_scope, paint_tail

_log = logging.getLogger(__name__)
LAG_LOG_EVERY = 30.0  # 앱 안에서 틱이 얼마나 밀리는지 30초마다 로그(실사용 렉 원인 가르기, 0.36.1)
LATE_GAP = 0.033  # 60번 틱이 33ms 넘게 벌어지면 '늦은 틱'(한 프레임 이상 밀림)

TICK_MS = 16  # 초당 약 60번
IDLE_TICK_MS = 50  # 1초 넘게 멈춰 있고 그릴 것이 없으면 초당 20번만 읽는다(움직이면 바로 60번으로)
IDLE_AFTER = 1.0
VISIBILITY_EVERY = 0.25  # 게임이 앞에 있는지는 0.25초마다만 확인


def _bucket(n: int, step: int = 64) -> int:
    return max(step, -(-int(n) // step) * step)


class _FxWindow(QWidget):
    def __init__(self, painter, stats=None) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._painter = painter
        self._stats = stats
        self._prepared = False

    def show_fx(self) -> None:
        if not self.isVisible():
            self.show()
            if not self._prepared:
                self._prepared = True
                from ..system.clickthrough import set_click_through
                set_click_through(self, True)
                # 캡처 제외는 0.37.1부터 오버레이 공통(ui/overlay_capture)
                from . import overlay_capture
                overlay_capture.apply(self)

    def paintEvent(self, _event):
        if self._stats is not None:
            self._stats['paints'] += 1
        p = QPainter(self)
        self._painter(p, self)
        p.end()


class CursorFx(QObject):
    """설정·표시 조건·창 3종(원, 화면 선 2개, 꼬리)을 관리한다."""

    def __init__(self, watcher, parent=None, pos_source=None, clock=None) -> None:
        super().__init__(parent)
        self._watcher = watcher
        self._pos = pos_source or cursor_sys.cursor_pos
        self._clock = clock or time.monotonic
        self.settings = clean_settings(config.load_cursor_fx())
        self._paused = False
        self._allowed = True  # 공개 범위(feature_access.cursor_fx_available) — 아니면 설정이 켜져 있어도 돌지 않음
        self._visible = False
        self._checked_at = -1e9
        self._last_pos: tuple[int, int] | None = None
        self._moved_at = -1e9
        self._trail = Trail()
        self._shake = ShakeDetector()
        self._shake_at = -1e9
        self.stats = Counter()  # 측정 스크립트용 횟수(틱·움직임·창 이동·그리기) — 더하기만 해서 비용 없음
        self._ring = _FxWindow(self._paint_ring, self.stats)
        self._hline = _FxWindow(self._paint_line, self.stats)
        self._vline = _FxWindow(self._paint_line, self.stats)
        self._tail = _FxWindow(self._paint_tail, self.stats)
        self._tail_origin = QPointF(0, 0)
        self._tail_points = []
        self._tail_size = (0, 0)
        self._ring_drawn = None
        self._particles = None
        self._timer = QTimer(self)
        # 정밀 타이머: 기본(대략) 타이머는 다른 타이머가 많은 앱 안에서 실행 시점이 크게 흔들린다(0.36.1 — 앱에서만 렉)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(TICK_MS)
        self._lag = Counter()
        self._lag_since = None
        self._last_tick = None
        self._timer.timeout.connect(self.tick)
        self._sync_timer()

    # ---- 설정 ------------------------------------------------------------------------------
    def update_settings(self, **changes) -> None:
        self.settings = clean_settings({**self.settings, **changes})
        config.save_cursor_fx(self.settings)
        self._trail.clear()
        self._last_pos = None
        self._hide_all()
        self._checked_at = -1e9
        self._sync_timer()

    def set_allowed(self, allowed: bool) -> None:
        self._allowed = bool(allowed)
        self._checked_at = -1e9
        self._sync_timer()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self._checked_at = -1e9
        if paused:
            self._hide_all()
        self._sync_timer()

    def shutdown(self) -> None:
        self._timer.stop()
        for w in self.windows():
            w.close()

    def windows(self):
        return (self._ring, self._hline, self._vline, self._tail)

    def is_enabled(self) -> bool:
        return bool(self.settings["enabled"]) and self._allowed

    def _sync_timer(self) -> None:
        run = self.is_enabled() and not self._paused
        if run and not self._timer.isActive():
            self._timer.start()
        elif not run:
            self._timer.stop()
            self._hide_all()

    def _hide_all(self) -> None:
        self._visible = False
        if getattr(self, "_particles", None) is not None:
            self._particles.clear()
        self._ring_drawn = None
        self._tail_size = (0, 0)
        for w in self.windows():
            if w.isVisible():
                w.hide()

    # ---- 매 틱 -----------------------------------------------------------------------------
    def tick(self) -> None:
        started = time.perf_counter()
        try:
            self._tick()
        finally:
            self._note_lag(started)

    def _note_lag(self, started: float) -> None:
        """보이는 동안(빠른 틱) 틱 간격과 틱 자체 시간을 모아 30초마다 로그. 늦은 틱이 많은데 자체 시간이 짧으면
        다른 작업(판독 등)이 같은 화면 스레드를 막는 것, 자체 시간이 길면 그리기가 무거운 것."""
        now = time.perf_counter()
        last, self._last_tick = self._last_tick, now
        # 직전 틱이 빠른 틱(16ms)일 때만 간격을 센다 — 멈춤(50ms)→움직임 첫 틱을 '늦은 틱'으로 세지 않게(0.37.0 QA)
        fast_before, self._fast_before = getattr(self, "_fast_before", False), self._timer.interval() == TICK_MS
        if not self._visible or self._timer.interval() != TICK_MS:
            return
        if not fast_before:
            last = None
        lag = self._lag
        if self._lag_since is None:
            self._lag_since = now
        if last is not None:
            gap = now - last
            lag["ticks"] += 1
            lag["late"] += gap > LATE_GAP
            lag["max_gap_ms"] = max(lag["max_gap_ms"], round(gap * 1000))
        own = (now - started) * 1000
        lag["own_total_ms"] += own
        lag["max_own_ms"] = max(lag["max_own_ms"], round(own, 1))
        if now - self._lag_since >= LAG_LOG_EVERY and lag["ticks"]:
            s = self.settings
            _log.info("마우스 커서 틱 %.0f초(%s·%s): 틱 %d · 늦은 틱(>33ms) %d(%.0f%%) · 최대 간격 %dms · 틱 자체 평균 %.2fms · 최대 %.1fms",
                      now - self._lag_since, s["shape"], s["tail"], lag["ticks"], lag["late"],
                      lag["late"] * 100 / lag["ticks"], lag["max_gap_ms"], lag["own_total_ms"] / lag["ticks"], lag["max_own_ms"])
            lag.clear()
            self._lag_since = now

    def _tick(self) -> None:
        now = self._clock()
        self.stats['ticks'] += 1
        if now - self._checked_at >= VISIBILITY_EVERY:
            self._checked_at = now
            show = self.is_enabled() and not self._paused and bool(self._watcher.is_game_active())
            if not show:
                if self._visible or any(w.isVisible() for w in self.windows()):
                    self._hide_all()
                    self._trail.clear()
                    self._last_pos = None
                return
            self._visible = True
        if not self._visible:
            return
        s = self.settings
        x, y = self._pos()
        moved = (x, y) != self._last_pos
        self._last_pos = (x, y)
        if moved:
            self.stats['moved'] += 1
            self._moved_at = now
            self._trail.add(now, x, y)
            if s["shake"] and self._shake.add(now, x):
                self._shake_at = now
        pulse = shake_scale(now - self._shake_at) if s["shake"] else 1.0
        pulsing = pulse > 1.0 or (0 <= now - self._shake_at < 1.1)
        # 원·스코프: 움직였거나 커지는 중일 때만 옮기고 다시 그린다
        ring_on = s["shape"] in ("ring", "scope") or (s["shake"] and pulsing and pulse > 1.0)
        if ring_on:
            if moved or pulsing or not self._ring.isVisible():
                self._ring_scale = pulse
                # 창 크기는 설정마다 고정(흔들기 켬이면 가장 클 때 크기) — 반투명 창은 크기를 바꿀 때마다 버퍼를 다시
                # 만들고 합성해서 무겁다(0.36.1 QA: 흔들 때 렉). 틱마다 위치만 옮기고, 안에서 배율만 바꿔 그린다.
                side = int(s["size"] * (SHAKE_SCALE if s["shake"] else 1.0)) + 8
                self.stats['ring_moves'] += 1
                if self._ring.width() != side or self._ring.height() != side:
                    self.stats['resizes'] += 1
                    self._ring.setGeometry(x - side // 2, y - side // 2, side, side)
                else:
                    self._ring.move(x - side // 2, y - side // 2)
                self._ring.show_fx()
                if pulsing or not moved or self._ring_drawn != pulse:
                    self._ring_drawn = pulse
                    self._ring.update()  # 움직이기만 하면 그림은 그대로(다시 그리지 않음)
        elif self._ring.isVisible():
            self._ring.hide()
        # 화면 선
        if s["shape"] == "lines":
            if moved or not self._hline.isVisible():
                screen = QGuiApplication.screenAt(self._qpoint(x, y)) or QGuiApplication.primaryScreen()
                g = screen.geometry()
                self._hline.setGeometry(g.x(), y, g.width(), 1)
                self._vline.setGeometry(x, g.y(), 1, g.height())
                self._hline.show_fx()
                self._vline.show_fx()
        else:
            for w in (self._hline, self._vline):
                if w.isVisible():
                    w.hide()
        # 꼬리
        seconds = TAIL_SECONDS[s["tailLength"]]
        particle = s["tail"] in PARTICLE_KINDS
        if particle:
            if self._particles is None or self._particles.kind != s["tail"]:
                self._particles = Particles(s["tail"])
            if moved:
                self._particles.spawn(now, x, y)
        live = (self._particles.active(now) if particle
                else s["tail"] != "none" and self._trail.active(now, seconds))
        if live:
            if particle:
                points = self._particles.alive(now)
                box = particle_bounds(points, 4)
            else:
                points = self._trail.points(now, seconds)
                box = bounds(points, s["size"] * 0.4 + 6)
            if box is not None:
                self._tail_points = points
                # 꼬리 창 크기는 64px 단위로 맞춰 꼬리가 그 단위를 넘을 때만 바꾸고, 아니면 옮기기만 한다.
                # 키우기만 하면(0.36.1 첫 수정) 창이 너무 커져 매번 다시 칠하는 반투명 면적이 늘었다(선 꼬리 0.66→1.37%).
                # 줄이기는 두 단위 이상 작아졌을 때만(왔다 갔다 하며 크기를 자주 바꾸지 않게).
                w0, h0 = self._tail_size
                need_w, need_h = _bucket(box[2]), _bucket(box[3])
                if (need_w > w0 or need_h > h0 or need_w <= w0 - 128 or need_h <= h0 - 128
                        or not self._tail.isVisible()):
                    w0, h0 = need_w, need_h
                    self._tail_size = (w0, h0)
                ox = box[0] + box[2] // 2 - w0 // 2
                oy = box[1] + box[3] // 2 - h0 // 2
                self._tail_origin = QPointF(ox, oy)
                if self._tail.width() != w0 or self._tail.height() != h0:
                    self.stats['resizes'] += 1
                    self._tail.setGeometry(QRect(ox, oy, w0, h0))
                else:
                    self._tail.move(ox, oy)
                self._tail.show_fx()
                self.stats['tail_updates'] += 1
                self._tail.update()
        elif self._tail.isVisible():
            self._tail_points = []
            self._tail_size = (0, 0)
            self._tail.hide()  # 멈춰서 꼬리가 다 사라지면 창을 숨기고 더 그리지 않는다
        idle = now - self._moved_at > IDLE_AFTER and not pulsing and not self._tail.isVisible()
        interval = IDLE_TICK_MS if idle else TICK_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    @staticmethod
    def _qpoint(x, y):
        from PySide6.QtCore import QPoint
        return QPoint(int(x), int(y))

    # ---- 그리기 ----------------------------------------------------------------------------
    def _opacity(self) -> float:
        return self.settings["opacity"] / 100

    def _paint_ring(self, p: QPainter, w: QWidget) -> None:
        s = self.settings
        center = QPointF(w.width() / 2, w.height() / 2)
        scale = getattr(self, "_ring_scale", 1.0)
        size = s["size"] * scale
        if s["shape"] == "scope" and scale <= 1.0:
            paint_scope(p, center, size, s["color"], self._opacity())
        else:
            paint_ring(p, center, size, s["color"], self._opacity())

    def _paint_line(self, p: QPainter, w: QWidget) -> None:
        c = QColor(self.settings["color"])
        c.setAlphaF(self._opacity() * 0.8)
        p.fillRect(w.rect(), c)

    def _paint_tail(self, p: QPainter, w: QWidget) -> None:
        s = self.settings
        if s["tail"] in PARTICLE_KINDS:
            paint_particles(p, self._tail_points, s["tail"], s["color"], self._opacity(), self._tail_origin,
                            multicolor=sparkle_multicolor(s))
            return
        paint_tail(p, self._tail_points, s["tail"], s["color"], s["size"], self._opacity(), self._tail_origin,
                   multicolor=sparkle_multicolor(s))
