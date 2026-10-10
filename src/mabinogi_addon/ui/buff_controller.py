"""버프 라이브 컨트롤러 (기획서 4.1 / 4.7).

FrameSource에서 버프 패널을 주기적으로 캡처 → BuffEngine.tick → 오버레이 갱신.
캡처·탐지는 백그라운드 스레드(UI 안 막음), 오버레이 갱신은 시그널로 메인 스레드에서.
FrameSource를 주입받으므로 Windows(dxcam)·개발(File) 모두 같은 코드로 동작.

포그라운드 감지(WindowWatcher): 게임(또는 자기 앱)이 활성일 때만 캡처·표시한다.
비활성이면 상태를 동결하고 오버레이를 숨긴다(엉뚱한 창을 캡처해 오탐하는 것 방지).
"""

from __future__ import annotations

import logging
import time

_log = logging.getLogger("mabinogi_addon.close")

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

# 사라짐 경고 타이밍.
# - 확정 대기: 버프가 목록에서 사라져도 이만큼(초) 연속으로 없어야 '완전히 사라짐'으로
#   확정한다(짧은 미검출·깜빡임 오탐 방지). 이 안에 다시 뜨면 아무 일도 없던 것으로.
# - 노출: 확정된 순간 빨간 테두리+X를 띄우고 소리를 1회 내며, 이만큼(초) 보여준 뒤 지운다.
_GONE_CONFIRM_SEC = 3.0
_GONE_SHOW_SEC = 3.0


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
    ) -> None:
        super().__init__()
        self._overlay = overlay
        self._catalog = catalog  # id -> BuffDef
        self._show_duration = show_duration
        self._on_alert = on_alert
        self._watcher = watcher or AlwaysActiveWatcher()
        self._worker: _TrackWorker | None = None
        self._source: FrameSource | None = None
        self._items: list[OverlayItem] = []
        self._game_active = True  # 게임 포그라운드
        self._self_active = False  # 우리 앱 포그라운드
        self._paused = False  # 사용자 일시정지(사냥 안 할 때) → 숨김·알림 억제
        self._last_remaining: dict[str, float] = {}  # 표시 평활용 직전 표시값
        # 사라짐 경고용 상태
        self._order: list[str] = []  # 표시 순서(고스트를 제자리에 끼우기 위함)
        self._warn_gone_ids: set[str] = set()  # '사라짐 경고' 켠 버프
        self._present_prev: set[str] = set()  # 직전 틱에 떠 있던 버프(사라짐 시작 감지)
        self._absent_since: dict[str, float] = {}  # 사라진 버프 → 사라지기 시작한 시각
        self._gone_show_until: dict[str, float] = {}  # 확정된 버프 → 경고 표시 종료 시각

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

    def request_stop(self) -> None:
        """워커에 정지 신호만 보낸다(대기 없음). 여러 컨트롤러를 병렬로 멈출 때."""
        if self._worker is not None:
            self._worker.stop()

    def stop(self, timeout_ms: int = 2000) -> None:
        if self._worker is not None:
            self._worker.stop()
            t = time.perf_counter()
            ok = self._worker.wait(timeout_ms)
            _log.info(
                "워커 wait %.0fms (정상종료=%s)",
                (time.perf_counter() - t) * 1000, ok,
            )
            if ok:
                self._worker = None  # 정상 종료한 것만 참조 해제(아니면 유지해 파괴 방지)
        # 워커를 멈춘 뒤(캡처 중 아님) 소스를 닫는다 — dxcam 카메라를 제어된 시점에 해제
        # (안 닫으면 프로세스 종료 시점에 정리되며 종료가 느려진다).
        if self._worker is None and self._source is not None:
            t = time.perf_counter()
            self._source.close()
            _log.info("소스 close %.0fms", (time.perf_counter() - t) * 1000)
            self._source = None

    @property
    def item_count(self) -> int:
        """현재 오버레이에 표시 중인 항목 수(진단 상태 표시용)."""
        return len(self._items)

    @property
    def game_active(self) -> bool:
        """게임이 포그라운드로 판정되는지(진단 상태 표시용)."""
        return self._game_active

    def set_paused(self, paused: bool) -> None:
        """사용자 일시정지: 오버레이를 숨기고 알림을 억제(캡처 스레드는 유지).

        추적 자체는 계속 돌지만 화면 표시·알림만 끈다 → 다시 켜면 즉시 현재 상태가
        보인다(재시작 비용 없음).
        """
        self._paused = paused
        self._apply_visibility()

    def set_show_duration(self, show_duration: dict[str, bool]) -> None:
        """지속시간 표시 설정 갱신(실행 중 폼 변경 반영)."""
        self._show_duration = show_duration

    def set_order(self, order: list[str]) -> None:
        """표시 순서 갱신(사라짐 고스트를 제자리에 끼우는 데 사용)."""
        self._order = list(order)

    def set_warn_gone_ids(self, ids: set[str]) -> None:
        """'사라짐 경고' 켠 버프 집합 갱신."""
        self._warn_gone_ids = set(ids)

    def _pixmap(self, buff_id: str):
        buff = self._catalog.get(buff_id)
        if buff is None:
            return None
        return QPixmap(str(buff.display_image or buff.match_icon))

    def build_items(self, entries, now: float) -> list[OverlayItem]:
        # 활성 항목: id -> OverlayItem. warn=남은시간<60s(숫자 빨강),
        # gone=엔진이 표시한 사라짐 경고(디버프가 보스에서 떨어짐) → 빨간 테두리+X.
        active: dict[str, OverlayItem] = {}
        for buff_id, text, warn, gone in overlay_spec(entries, self._show_duration):
            pm = self._pixmap(buff_id)
            if pm is not None:
                active[buff_id] = OverlayItem(pm, None if gone else text, warn, gone=gone)
        # 순서대로 활성 + 고스트(사라짐 확정) 병합. 활성이면 고스트보다 우선.
        items: list[OverlayItem] = []
        placed: set[str] = set()
        order = self._order or list(active)
        for bid in order:
            if bid in active:
                items.append(active[bid])
                placed.add(bid)
            elif bid in self._gone_show_until and now < self._gone_show_until[bid]:
                pm = self._pixmap(bid)
                if pm is not None:
                    items.append(OverlayItem(pm, None, gone=True))
                    placed.add(bid)
        # order에 없는 활성 버프(혹시 모를 누락)는 뒤에 붙인다.
        for bid, item in active.items():
            if bid not in placed:
                items.append(item)
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
        now = time.monotonic()
        active_ids = {e.buff_id for e in entries}
        # 다시 보이면(또는 아직 보이면) 사라짐 진행/확정 모두 취소 — 오탐 방지.
        for bid in active_ids:
            self._absent_since.pop(bid, None)
            self._gone_show_until.pop(bid, None)
        # 사라지기 시작: 직전 틱엔 있었는데 이번엔 없는 '사라짐 경고' 버프 → 확정 대기 시작.
        for bid in (self._present_prev - active_ids):
            if bid in self._warn_gone_ids and bid not in self._gone_show_until:
                self._absent_since.setdefault(bid, now)
        self._present_prev = active_ids
        # 확정: 확정 대기 시간(_GONE_CONFIRM_SEC) 연속으로 없으면 '완전히 사라짐' 확정 →
        # 경고 아이콘 노출 시작 + 소리 1회. (그 전에 다시 뜨면 위에서 취소되어 조용.)
        just_confirmed = []
        for bid, since in list(self._absent_since.items()):
            if now - since >= _GONE_CONFIRM_SEC:
                self._gone_show_until[bid] = now + _GONE_SHOW_SEC
                del self._absent_since[bid]
                just_confirmed.append(bid)
        if just_confirmed and not self._paused:
            from .notifier import play_warn_gone_sound

            play_warn_gone_sound()  # 여러 개 동시 확정돼도 소리는 한 번
        self._items = self.build_items(entries, now)
        self._overlay.set_items(self._items)
        self._apply_visibility()

    def _on_foreground_changed(self, game: bool, selfa: bool) -> None:
        self._game_active = game
        self._self_active = selfa
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        if self._paused:  # 일시정지: 포그라운드·고정 상태와 무관하게 무조건 숨김
            self._overlay.hide()
            return
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
        if self._paused:  # 일시정지 중엔 종료 알림(소리)도 울리지 않음
            return
        if self._on_alert is not None:
            self._on_alert(buff_ids)
