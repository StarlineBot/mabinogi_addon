"""버프 라이브 컨트롤러 (기획서 4.1 / 4.7).

FrameSource에서 버프 패널을 주기적으로 캡처 → BuffEngine.tick → 오버레이 갱신.
캡처·탐지는 백그라운드 스레드(UI 안 막음), 오버레이 갱신은 시그널로 메인 스레드에서.
FrameSource를 주입받으므로 Windows(dxcam)·개발(File) 모두 같은 코드로 동작.

포그라운드와 무관하게 계속 캡처·판독한다(지속시간이 끊기지 않고 동기화되게 —
파티 바드 노래처럼 내가 포커스 안 해도 들어오는 버프도 갱신). 엉뚱한 창을 캡처하는
오탐은 엔진의 앵커(기준 버프) 판정으로 막는다: 버프 바가 다른 창에 가려지면 앵커가
안 보여 frame_valid=False가 되고, 엔진이 감지·해제를 멈추고 내부 시계만 유지한다.
포커스가 없을 땐 주기를 늘려(_IDLE_INTERVAL_MS) CPU를 아낀다.
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

# 게임이 포그라운드가 아닐 때의 탐지 주기(ms). 포커스가 없어도 지속시간은 계속
# 읽어야 하지만(파티 버프 등), 포커스가 없는 동안엔 자주 볼 필요가 없어 주기를 늘려
# CPU를 아낀다(약 0.5초마다 — 카운트다운 표시엔 충분).
_IDLE_INTERVAL_MS = 500

# 사라짐 경고 타이밍.
# - 확정 대기: 버프가 목록에서 사라져도 이만큼(초) 연속으로 없어야 '완전히 사라짐'으로
#   확정한다(짧은 미검출·깜빡임 오탐 방지). 이 안에 다시 뜨면 아무 일도 없던 것으로.
# - 노출: 확정된 순간 빨간 테두리+X를 띄우고 소리를 1회 내며, 이만큼(초) 보여준 뒤 지운다.
_GONE_CONFIRM_SEC = 3.0
_GONE_SHOW_SEC = 5.0

# 제때(타임아웃 내) 안 멈춘 워커 보관소 — **모듈 전역**. 컨트롤러가 재시작/교체로 버려져도
# (예: main_window가 controller=None) 이 전역이 참조를 유지해, 실행 중인 QThread가 파괴돼
# 프로세스가 abort되는 걸 막는다. 워커가 실제로 끝나면 finished에서 스스로 빠진다.
_ZOMBIES: set = set()


class _TrackWorker(QThread):
    updated = Signal(list)  # list[OverlayEntry]
    alerted = Signal(list)  # list[buff_id] (1차 만료임박)
    alerted2 = Signal(list)  # list[buff_id] (2차 막차 경고)
    foreground_changed = Signal(bool, bool)  # (게임 활성, 자기 앱 활성)

    def __init__(
        self,
        source: FrameSource,
        engine: BuffEngine,
        watcher: WindowWatcher,
        interval_ms: int = 200,
        bar_source: FrameSource | None = None,
    ) -> None:
        super().__init__()
        self._source = source
        self._engine = engine
        self._watcher = watcher
        self._interval = interval_ms
        self._running = True
        self._fg: tuple[bool, bool] | None = None
        # 3차(percent)용 '보스 HP바 영역' 소스(있을 때만 grab해 tick에 bar_region으로 전달).
        self._bar_source = bar_source
        self._bar_capture_failed = False
        self._bar_last_capture = None
        self._bar_frame = None

    def run(self) -> None:
        while self._running:
            game = self._watcher.is_game_active()
            selfa = self._watcher.is_self_active()
            if (game, selfa) != self._fg:
                self._fg = (game, selfa)
                self.foreground_changed.emit(game, selfa)
            # 한 틱의 캡처·판독 예외가 **앱 전체를 죽이지 않게** 감싼다. QThread.run에서 올라간
            # 미처리 예외는 PySide6에서 프로세스를 abort시킬 수 있다(자동 찾기로 새 영역을
            # 지정한 직후 3차 판독 틱이 던지면 앱이 통째로 꺼지던 문제). 이 틱만 로그로 남기고
            # 건너뛰면 추적은 다음 틱에 스스로 복구된다.
            try:
                self._tick_once(game)
            except Exception:  # noqa: BLE001 — 추적 틱 격리(앱 생존 우선)
                _log.exception("추적 틱 실패 — 이 틱만 건너뛰고 계속(앱 유지)")
            self._sleep(active=game)

    def _tick_once(self, game: bool) -> None:
        # 포그라운드와 무관하게 계속 읽는다 — 지속시간이 끊기지 않고 계속 동기화되게.
        # (파티 바드 노래 등은 내가 포커스 안 해도 갱신된다.) 라이브 캡처는 게임이
        # 화면에 보이면 잡히고, 다른 창이 버프 바를 가리면 앵커(기준 버프)가 안 보여
        # 엔진이 frame_valid=False로 '동결'(감지·해제 멈추고 시계만 유지)하므로,
        # 비게임 화면을 캡처해도 오탐으로 터지지 않는다.
        region = self._source.grab()
        if region is None:
            return
        # 탐지·시간읽기는 포커스와 무관하게 계속(시간 동기화), 소리 알림은
        # 포그라운드일 때만(foreground=game) — 엔진이 알림 판정을 게이팅한다.
        if self._bar_source is not None:
            # 3차: 보스 HP바 영역을 따로 캡처해 bar_region으로 넘긴다(디버프 엔진만
            # 이 인자를 받으므로, 바 소스가 있을 때만 전달).
            now = time.monotonic()
            period = getattr(self._engine, "bar_capture_interval", 0)
            if self._bar_last_capture is None or now - self._bar_last_capture >= period:
                self._bar_last_capture = now
                try:
                    self._bar_frame = self._bar_source.grab()
                    self._bar_capture_failed = False
                except Exception:
                    if not self._bar_capture_failed:
                        _log.exception("보스 바 캡처 실패 — 아이콘 감시 유지")
                    self._bar_capture_failed = True
                    self._bar_frame = None
            result = self._engine.tick(
                region, now, foreground=game,
                bar_region=self._bar_frame,
            )
        else:
            result = self._engine.tick(region, time.monotonic(), foreground=game)
        self.updated.emit(result.entries)
        if result.alerts:
            self.alerted.emit(result.alerts)
        if result.alerts2:
            self.alerted2.emit(result.alerts2)

    def _sleep(self, active: bool = True) -> None:
        """주기를 작게 쪼개 자며 _running을 자주 확인(종료 요청 즉시 반응). 게임이
        포그라운드가 아니면 주기를 늘려 CPU를 아낀다(지속시간 표시엔 충분)."""
        target = self._interval if active else max(self._interval, _IDLE_INTERVAL_MS)
        step = 30
        waited = 0
        while self._running and waited < target:
            self.msleep(min(step, target - waited))
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
        on_alert2=None,
    ) -> None:
        super().__init__()
        self._overlay = overlay
        self._catalog = catalog  # id -> BuffDef
        self._show_duration = show_duration
        self._on_alert = on_alert
        self._on_alert2 = on_alert2  # 2차(막차) 알림 콜백(없으면 2차 소리 없음)
        self._watcher = watcher or AlwaysActiveWatcher()
        self._worker: _TrackWorker | None = None
        self._source: FrameSource | None = None
        self._bar_source: FrameSource | None = None  # 3차 보스 바 영역 소스(함께 닫기)
        self._items: list[OverlayItem] = []
        self._game_active = True  # 게임 포그라운드
        self._self_active = False  # 우리 앱 포그라운드
        self._paused = False  # 사용자 일시정지(사냥 안 할 때) → 숨김·알림 억제
        self._generation = 0
        self._last_remaining: dict[str, float] = {}  # 표시 평활용 직전 표시값
        # 사라짐 경고용 상태
        self._order: list[str] = []  # 표시 순서(고스트를 제자리에 끼우기 위함)
        self._warn_gone_ids: set[str] = set()  # '사라짐 경고' 켠 버프
        self._present_prev: set[str] = set()  # 직전 틱에 떠 있던 버프(사라짐 시작 감지)
        self._absent_since: dict[str, float] = {}  # 사라진 버프 → 사라지기 시작한 시각
        self._gone_show_until: dict[str, float] = {}  # 확정된 버프 → 경고 표시 종료 시각

    def start(
        self, source: FrameSource, engine: BuffEngine, interval_ms: int = 200,
        bar_source: FrameSource | None = None,
    ) -> None:
        self.stop()
        self._source = source
        self._bar_source = bar_source
        self._worker = _TrackWorker(
            source, engine, self._watcher, interval_ms, bar_source=bar_source
        )
        generation = self._generation
        for signal, callback in ((self._worker.updated, self._on_updated),
                                 (self._worker.alerted, self._on_alerted),
                                 (self._worker.alerted2, self._on_alerted2),
                                 (self._worker.foreground_changed, self._on_foreground_changed)):
            signal.connect(lambda *args, callback=callback: callback(*args)
                           if self._generation == generation else None)
        self._worker.start()

    def request_stop(self) -> None:
        """워커에 정지 신호만 보낸다(대기 없음). 여러 컨트롤러를 병렬로 멈출 때."""
        if self._worker is not None:
            self._worker.stop()

    def stop(self, timeout_ms: int = 2000) -> None:
        self._generation += 1
        w = self._worker
        if w is None:
            return
        for signal in (w.updated, w.alerted, w.alerted2, w.foreground_changed):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        w.stop()
        t = time.perf_counter()
        ok = w.wait(timeout_ms)
        _log.info(
            "워커 wait %.0fms (정상종료=%s)", (time.perf_counter() - t) * 1000, ok
        )
        # **항상** 참조를 비운다 — start()가 실행 중 스레드를 새 워커로 덮어써 파괴(=Qt abort)
        # 하지 못하게. 안 멈췄으면 아래에서 좀비로 보관해 파괴를 막는다.
        self._worker = None
        src, bsrc = self._source, self._bar_source
        self._source = None
        self._bar_source = None
        if ok:
            # 깨끗이 멈춤(캡처 중 아님) → 소스를 제어된 시점에 닫는다.
            self._close_sources(src, bsrc)
            return
        # 2초 내 안 멈춤(dxcam grab이 포커스 아웃 등으로 블록). 실행 중 QThread를 파괴하면
        # Qt가 프로세스를 abort시키므로, 참조를 좀비로 보관해 파괴를 막는다. 워커가 실제로
        # 끝나면(grab 반환) finished에서 수거하며 그때 소스를 닫는다(소스도 grab 중엔 못 닫음).
        _log.warning("워커 미정지 → 좀비 보관(앱 abort 방지), 종료 시 수거")
        for sig in (w.updated, w.alerted, w.alerted2, w.foreground_changed):
            try:
                sig.disconnect()  # 죽어가는 워커의 늦은 emit이 오버레이를 흔들지 않게
            except (RuntimeError, TypeError):
                pass

        def _reap() -> None:
            if w not in _ZOMBIES:
                return  # isFinished 폴백과 대기 중인 finished 콜백이 겹칠 수 있음
            try:
                w.finished.disconnect(_reap)
            except (RuntimeError, TypeError):
                pass
            _ZOMBIES.discard(w)
            self._close_sources(src, bsrc)

        w.finished.connect(_reap)
        _ZOMBIES.add(w)
        if w.isFinished():  # wait 타임아웃 직후 끝났을 수 있음(연결 전 발화 대비)
            _reap()

    def _close_sources(
        self, src: FrameSource | None, bsrc: FrameSource | None
    ) -> None:
        """워커가 멈춘 뒤 캡처 소스를 닫는다(dxcam 카메라 제어 해제). 실패는 무시."""
        if src is None:
            return
        try:
            t = time.perf_counter()
            src.close()
            if bsrc is not None:
                bsrc.close()
            _log.info("소스 close %.0fms", (time.perf_counter() - t) * 1000)
        except Exception:  # noqa: BLE001 — 종료 정리 실패는 무시(앱 생존 우선)
            _log.info("소스 close 실패(무시)", exc_info=True)

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
        # 사라짐 경고는 '게임이 포그라운드일 때만' 판정·발동한다 — 안 보는 동안(알트탭·
        # 가림)엔 떨어짐으로 보지 않는다(거짓 경고 방지). 비포커스면 진행 중인 확정 대기도
        # 비워, 복귀 시 깨끗이 다시 판정한다.
        if not self._game_active:
            self._absent_since.clear()
            self._present_prev = active_ids
            self._items = self.build_items(entries, now)
            self._overlay.set_items(self._items)
            self._apply_visibility()
            return
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

    def _on_alerted2(self, buff_ids) -> None:
        if self._paused:  # 일시정지 중엔 2차(막차) 알림도 울리지 않음
            return
        if self._on_alert2 is not None:
            self._on_alert2(buff_ids)
