"""최적화 › 하프 채널 연결(docs/harp-channel-tcp-spec.md, 1절 끝 사용자 결정 1~3차 우선). 제작자만.

이 화면을 보는 동안만 잰다: 열면 바로 한 번, 한 회차가 끝나고 60초 뒤 다시. 다른 탭·최소화·트레이·전투 보조 일시정지면 멈춘다.
측정(소켓 연결)은 작업 스레드(harp_latency.Round)에서 하고, 결과는 신호로 화면 스레드에 넘긴다.
"""
from __future__ import annotations

from datetime import datetime
from time import monotonic

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import harp_latency as hl
from .palette import color
from .widgets import FeatureHeader, hint_label

INTERVAL = 60.0  # 한 회차가 끝난 뒤 다음 회차까지(초)
COLUMNS = 6
TITLE = "하프 채널 연결"
SUMMARY = "내 PC에서 하프 서버 채널별 접속 주소까지 TCP 연결에 걸리는 시간을 재요."
NOTICE = "TCP 연결 시간이며, 게임 안 핑이나 채널 혼잡도와 다를 수 있어요. 이 화면을 보는 동안 60초마다 다시 재요."


def clock_text(when: datetime) -> str:
    """오후 9:41:08"""
    return f"{'오전' if when.hour < 12 else '오후'} {when.hour % 12 or 12}:{when.minute:02d}:{when.second:02d}"


def _ms(value: float) -> str:
    return f"{value:.1f}"


def _tint(name: str, alpha: float) -> str:
    c = color(name).lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


class ChannelCard(QFrame):
    """채널 칸: 이름(+가장 빠름) · 큰 숫자 ms 또는 상태 글자 · 중앙값·성공/시도."""

    def __init__(self, number: int):
        super().__init__()
        self.number = number
        self.setObjectName("harpCard")
        self.setMinimumWidth(104)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = QLabel(f"{number}채널")
        self.name.setStyleSheet("font-size:15px; font-weight:bold;")
        self.badge = QLabel("가장 빠름")
        self.badge.setStyleSheet(f"background:{color('ok')}; color:#062F1A; font-size:10px; font-weight:bold;"
                                 " padding:1px 4px; border-radius:3px;")
        self.badge.hide()
        top.addWidget(self.name)
        top.addWidget(self.badge)
        top.addStretch(1)
        v.addLayout(top)
        self.value = QLabel()
        self.value.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.value)
        self.sub = QLabel()
        self.sub.setStyleSheet(f"color:{color('muted')}; font-size:11px;")
        v.addWidget(self.sub)
        self.fastest = False
        self.show_state("before", None)

    def _style(self) -> None:
        if self.fastest:
            self.setStyleSheet(f"#harpCard {{ background:{_tint('ok', 0.14)}; border:2px solid {color('ok')}; border-radius:6px; }}")
        else:
            self.setStyleSheet("#harpCard { border:1px solid palette(mid); border-radius:6px; }")

    def set_fastest(self, on: bool) -> None:
        self.fastest = on
        self.badge.setVisible(on)
        self._style()

    def show_state(self, state: str, stats: hl.ChannelStats | None) -> None:
        """state: before(측정 전) | waiting(대기) | measuring(측정 중) | done(이 채널 결과 있음)"""
        big = "font-size:22px; font-weight:bold;"
        muted = color("muted")
        last = stats.last if stats is not None else None
        if state == "measuring" and last is None:
            self.value.setText(f"<span style='{big} color:{muted}'>…</span>")
            self.sub.setText("측정 중")
        elif last is None:
            self.value.setText(f"<span style='{big} color:{muted}'>—</span>")
            self.sub.setText("대기" if state in ("waiting", "measuring") else "측정 전")
        elif last.kind == hl.OK:
            self.value.setText(f"<span style='{big}'>{_ms(last.ms)}</span> <span style='color:{muted}'>ms</span>")
            self.sub.setText(f"중앙값 {_ms(stats.median)} · {stats.successes}/{stats.attempts}")
        else:
            word, tone = {hl.TIMEOUT_KIND: ("시간 초과", "warn"), hl.REFUSED: ("연결 거부", "danger")}.get(
                last.kind, ("연결 실패", "danger"))
            self.value.setText(f"<span style='font-size:15px; font-weight:bold; color:{color(tone)}'>{word}</span>")
            self.sub.setText(f"중앙값 {_ms(stats.median)} · {stats.successes}/{stats.attempts}" if stats.median is not None
                             else f"성공 {stats.successes}/{stats.attempts}")
        if state == "measuring" and last is not None:
            self.sub.setText(self.sub.text() + " · 측정 중")


class RecommendBox(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("harpRecommend")
        self.setStyleSheet(f"#harpRecommend {{ background:{_tint('ok', 0.10)}; border:1px solid {color('ok')}; border-radius:6px; }}")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(12)
        label = QLabel("추천 채널")
        label.setStyleSheet(f"color:{color('muted')};")
        h.addWidget(label)
        self.main = QLabel()
        self.main.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(self.main)
        h.addStretch(1)
        self.others = QLabel()
        self.others.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(self.others)

    def show_message(self, text: str) -> None:
        self.main.setText(f"<span style='color:{color('muted')}'>{text}</span>")
        self.others.setText("")

    def show_result(self, history: hl.History) -> bool:
        top, rest = history.recommendation()
        if top is None:
            return False
        s = history.stats[top]
        muted = color("muted")
        self.main.setText(f"<span style='font-size:24px; font-weight:bold; color:{color('ok')}'>{top}채널</span>"
                          f"&nbsp;&nbsp;<span style='font-size:16px; font-weight:bold'>{_ms(s.median if s.last is None or s.last.kind != hl.OK else s.last.ms)}</span>"
                          f" <span style='color:{muted}'>ms · 중앙값 {_ms(s.median)}</span>")
        if rest:
            items = " · ".join(f"<b>{n}채널</b> {_ms(history.stats[n].median)}" for n in rest)
            self.others.setText(f"<span style='color:{muted}'>다음으로 빠른 채널</span>&nbsp;&nbsp;{items}")
        else:
            self.others.setText("")
        return True


class HarpChannelTab(QWidget):
    _started = Signal(int, int)        # 회차 번호, 채널
    _result = Signal(int, int, object)  # 회차 번호, 채널, Result
    _finished = Signal(int, bool)       # 회차 번호, 취소됨

    def __init__(self, *, channels: list[hl.Channel] | None = None, connect=hl.connect_time,
                 now=datetime.now, clock=monotonic, timeout: float = hl.TIMEOUT):
        super().__init__()
        self.channels = hl.load_channels() if channels is None else channels
        self.history = hl.History(self.channels)
        self._connect, self._now, self._clock, self._timeout = connect, now, clock, timeout
        self._round: hl.Round | None = None
        self._generation = 0
        self._measuring: set[int] = set()
        self._done_count = 0
        self._last_time: datetime | None = None
        self._next_at: float | None = None
        self._paused = False
        self._active = False

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(FeatureHeader(TITLE, SUMMARY))
        self.recommend = RecommendBox()
        v.addWidget(self.recommend)
        row = QHBoxLayout()
        from .calculator_sidebar import refresh_button
        self.refresh = refresh_button("지금 다시 측정")
        self.refresh.setAccessibleName("지금 다시 측정")
        self.refresh.clicked.connect(self.measure_now)
        row.addWidget(self.refresh)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.status, 1)
        v.addLayout(row)
        v.addWidget(hint_label(NOTICE))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.cards: dict[int, ChannelCard] = {}
        for i, channel in enumerate(self.channels):
            card = ChannelCard(channel.number)
            self.cards[channel.number] = card
            grid.addWidget(card, i // COLUMNS, i % COLUMNS)
        for col in range(COLUMNS):
            grid.setColumnStretch(col, 1)
        v.addLayout(grid)
        v.addStretch(1)

        self._started.connect(self._on_started)
        self._result.connect(self._on_result)
        self._finished.connect(self._on_finished)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)  # 남은 시간 표시·화면 상태 확인(가벼움)
        self._timer.timeout.connect(self._tick)
        self._refresh_view()

    # ---- 화면을 보는 동안만 ----------------------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self._tick()

    def _viewing(self) -> bool:
        window = self.window()
        return (self.isVisible() and not self._paused
                and not (window is not None and window.isMinimized()))

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()
        self._tick()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()
        self._set_active(False)

    def _set_active(self, on: bool) -> None:
        if on == self._active:
            return
        self._active = on
        if on:
            self._next_at = None
            self.measure_now()  # 다시 보면 바로 한 번
        else:
            self.cancel()
            self._next_at = None
            self._refresh_view()

    def _tick(self) -> None:
        self._set_active(self._viewing())
        if self._active and self._round is None and self._next_at is not None and self._clock() >= self._next_at:
            self.measure_now()
        self._refresh_status()

    # ---- 회차 ---------------------------------------------------------------------------------
    def measure_now(self) -> None:
        if self._round is not None or not self._viewing():
            return  # 회차가 겹치지 않게
        self._generation += 1
        generation = self._generation
        self._measuring.clear()
        self._done_count = 0
        self._next_at = None
        self._round = hl.Round(
            self.channels,
            on_start=lambda n: self._started.emit(generation, n),
            on_result=lambda n, r: self._result.emit(generation, n, r),
            on_done=lambda cancelled: self._finished.emit(generation, cancelled),
            connect=self._connect, timeout=self._timeout)
        self._round.start()
        self._refresh_view()

    def cancel(self) -> None:
        round_ = self._round
        if round_ is None:
            return
        round_.cancel()
        self._generation += 1  # 늦게 오는 결과는 버린다(취소는 시도에 넣지 않음)
        self._round = None
        self._measuring.clear()

    def shutdown(self) -> None:
        self._timer.stop()
        round_ = self._round
        self.cancel()
        if round_ is not None:
            round_.join(3.0)

    def _on_started(self, generation: int, number: int) -> None:
        if generation != self._generation:
            return
        self._measuring.add(number)
        self.cards[number].show_state("measuring", self.history.stats[number])

    def _on_result(self, generation: int, number: int, result: hl.Result) -> None:
        if generation != self._generation:
            return
        self._measuring.discard(number)
        self.history.record(number, result)
        if result.kind != hl.CANCELLED:
            self._done_count += 1
        self.cards[number].show_state("done", self.history.stats[number])
        self._refresh_status()

    def _on_finished(self, generation: int, cancelled: bool) -> None:
        if generation != self._generation:
            return
        self._round = None
        self._measuring.clear()
        if not cancelled:
            self._last_time = self._now()
            self._next_at = self._clock() + INTERVAL
        self._refresh_view()

    # ---- 표시 ---------------------------------------------------------------------------------
    def _refresh_status(self) -> None:
        ok = color("ok")
        if self._round is not None:
            self.status.setText(f"<span style='color:{ok}'>● 측정 중 · {self._done_count} / {len(self.channels)}</span>")
        elif self._last_time is None:
            self.status.setText(f"<span style='color:{color('muted')}'>● 아직 측정 안 함</span>")
        else:
            text = f"마지막 측정 {clock_text(self._last_time)}"
            if self._paused:
                text += " · 전투 보조 일시정지 중에는 재지 않아요"
            elif self._active and self._next_at is not None:
                text += f" · 다음 측정까지 {max(0, int(round(self._next_at - self._clock())))}초"
            self.status.setText(f"<span style='color:{color('muted')}'>{text}</span>")
        self.refresh.setEnabled(self._round is None and self._viewing())

    def _refresh_view(self) -> None:
        fastest = self.history.fastest() if self._round is None or self._last_time is not None else set()
        for number, card in self.cards.items():
            stats = self.history.stats[number]
            if self._round is not None:
                state = "measuring" if number in self._measuring else ("done" if stats.last is not None else "waiting")
            else:
                state = "done" if stats.last is not None else "before"
            card.show_state(state, stats)
            card.set_fastest(number in fastest)
        if not self.recommend.show_result(self.history):
            if self._round is not None:
                self.recommend.show_message("측정하고 있어요 — 끝나면 알려줘요")
            elif self._last_time is not None:
                self.recommend.show_message("연결된 채널이 없어요")
            else:
                self.recommend.show_message("측정이 끝나면 지금 가장 빠른 채널을 알려줘요")
        self._refresh_status()
