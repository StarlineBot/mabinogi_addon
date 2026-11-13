"""편의기능 › 알람(docs/alarm-spec.md, 0.48.0).

코드 → 동작:
- 판정은 새 타이머 없이 최적화 화면의 0.25초 주기에서 `tick()`을 불러 시각만 비교한다(alarm.AlarmClock).
- 울리면: 게임 창이 있으면 ② 게임 위 알림(상단 정중앙 큰 알약 5초, game_notice), 없으면 ③ 앱 알림(오른쪽 아래 토스트 5초).
  소리는 늘(전투 보조 일시정지와 무관) — 알람.mp3 / 타이머.mp3, 없으면 기본 알림음.
- 게임 위 알람 목록(alarm_overlay): 게임이 앞에 있고 다가오는 알람이 있을 때만, 가장 먼저 울릴 것부터 최대 3개.
- 알람 목록·설정은 config `alarms`(설정 동기화 대상).
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                               QStackedWidget, QTimeEdit, QVBoxLayout, QWidget)

from .. import alarm as model
from .. import config
from .palette import color
from .widgets import FeatureHeader, WrapRow, checkbox, divider, hint_label, switch

_log = logging.getLogger(__name__)

DESCRIPTION = "PC 시계(현실 시간) 기준이에요. 게임 안 시간 알람과는 달라요. 앱이 켜져 있으면 게임을 하지 않아도 울려요."
RING_HINT = "게임 중이면 게임 위 상단에, 아니면 화면 오른쪽 아래에 5초 띄우고 소리를 내요. 앱이 꺼져 있던 동안의 알람은 울리지 않아요."
NOTICE_MS = 5000
from .game_notice import ALARM_COLORS as NOTICE_COLORS  # noqa: E402 — 색은 게임 위 오버레이 쪽에
REPEAT_CHOICES = (("once", "한 번"), ("daily", "매일"), ("days", "요일 고르기…"))
PRE_TEXT = {0: "미리 알림 없음", 5: "5분 전", 10: "10분 전"}
QUICK_MINUTES = (5, 10, 30, 60)


def _group(*widgets) -> QWidget:
    """한 묶음(가로). 좁으면 WrapRow가 두 번째 묶음만 다음 줄로 내린다."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for item in widgets:
        widget, stretch = item if isinstance(item, tuple) else (item, 0)
        h.addWidget(widget, stretch)
    return w


def _wrap(first, second) -> WrapRow:
    """넓으면 한 줄(첫 묶음이 늘어나 두 번째 묶음은 오른쪽 끝), 좁으면 두 번째 묶음만 다음 줄."""
    row = WrapRow(first, second, spacing=8)
    row._box.setStretchFactor(first, 1)
    row._box.setStretch(2, 0)  # WrapRow 끝의 빈 늘림은 쓰지 않음(첫 묶음이 남는 폭을 다 가짐)
    return row


def _find_game_hwnd() -> int:
    from ..system.dwm_thumbnail import find_game_window
    from ..system.window_watcher import DEFAULT_GAME_TITLES
    try:
        return find_game_window(config.load_game_exe(), DEFAULT_GAME_TITLES)
    except Exception:  # noqa: BLE001
        return 0


def _toast(title: str, body: str) -> None:
    from .toast import show_toast
    show_toast(title, body, NOTICE_MS)


def _sound(kind: str) -> None:
    from .notifier import play_alarm_sound
    play_alarm_sound(kind)


class AlarmTab(QWidget):
    def __init__(self, watcher=None, parent=None, *, now=time.time, game_hwnd=_find_game_hwnd, toast=_toast,
                 sound=_sound) -> None:
        super().__init__(parent)
        self._watcher = watcher
        self._now = now
        self._game_hwnd = game_hwnd
        self._toast = toast
        self._sound = sound
        self._notices: list = []
        self._overlay = None
        self._closed = False
        self._status_cache = None
        self._rows: list[tuple] = []
        self._cfg = config.load_alarms()
        items = [a for d in self._cfg["items"] if (a := model.Alarm.from_dict(d)) is not None]
        self.clock = model.AlarmClock(items)
        self.clock.start(self._now())
        if len(self.clock.alarms) != len(items):
            self._save_items()  # 앱이 꺼져 있던 동안 끝난 타이머는 빠짐(울리지 않음)

        v = QVBoxLayout(self)
        v.addWidget(FeatureHeader("알람", DESCRIPTION))
        box = QGroupBox("알람")
        bv = QVBoxLayout(box)
        self.enable = switch("알람 사용")
        self.enable.setChecked(self._cfg["enabled"])
        self.enable.toggled.connect(self._on_enable)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        top = QHBoxLayout()
        top.addWidget(self.enable)
        top.addWidget(self.status, 1)
        bv.addLayout(top)

        mode = QHBoxLayout()
        mode.addWidget(QLabel("새 알람"))
        from .cursor_tab import _Segments
        self.mode = _Segments({"time": "시각 지정", "timer": "몇 분 뒤"})
        self.mode.changed.connect(self._on_mode)
        mode.addWidget(self.mode, 1)
        bv.addLayout(mode)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._time_page())
        self.pages.addWidget(self._timer_page())
        bv.addWidget(self.pages)
        self.mode.set_value("time")
        bv.addWidget(divider())
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(6)
        bv.addLayout(self.list_box)
        self.empty = hint_label("아직 알람이 없어요.")
        bv.addWidget(self.empty)
        bv.addWidget(hint_label(RING_HINT))
        v.addWidget(box)
        v.addWidget(self._overlay_box())
        v.addStretch(1)
        self._rebuild_list()
        self._refresh_status(force=True)

    # ---- 화면 ----
    def _time_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        self.time_edit = QTimeEdit(QTime(21, 0))
        self.time_edit.setDisplayFormat("HH:mm")
        self.repeat = QComboBox()
        for key, text in REPEAT_CHOICES:
            self.repeat.addItem(text, key)
        self.repeat.currentIndexChanged.connect(self._on_repeat)
        self.time_name = QLineEdit()
        self.time_name.setPlaceholderText("이름 (예: 레이드)")
        self.time_name.setMaxLength(40)
        self.time_name.setMinimumWidth(120)
        self.pre = QComboBox()
        for minutes, text in PRE_TEXT.items():
            self.pre.addItem(text, minutes)
        self.pre.setCurrentIndex(1)
        self.add_btn = QPushButton("＋ 추가")
        self.add_btn.clicked.connect(self._add_time)
        col.addWidget(_wrap(_group(self.time_edit, self.repeat, (self.time_name, 1)), _group(self.pre, self.add_btn)))
        self.days_row = QWidget()
        days = QHBoxLayout(self.days_row)
        days.setContentsMargins(0, 0, 0, 0)
        days.addWidget(QLabel("요일"))
        self.day_checks = []
        for i, name in enumerate(model.DAY_NAMES):
            cb = checkbox(name)
            self.day_checks.append(cb)
            days.addWidget(cb)
        days.addStretch(1)
        self.days_row.hide()
        col.addWidget(self.days_row)
        return page

    def _timer_page(self) -> QWidget:
        page = QWidget()
        row = QVBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, model.TIMER_MAX_MIN)
        self.minutes.setValue(30)
        self.minutes.setSuffix(" 분 뒤")
        self.quick = []
        for m in QUICK_MINUTES:
            b = QPushButton(f"{m}분")
            b.clicked.connect(lambda _=False, m=m: self.minutes.setValue(m))
            self.quick.append(b)
        self.timer_name = QLineEdit()
        self.timer_name.setPlaceholderText("이름 (예: 요리)")
        self.timer_name.setMaxLength(40)
        self.timer_name.setMinimumWidth(120)
        self.start_btn = QPushButton("▶ 시작")
        self.start_btn.clicked.connect(self._add_timer)
        row.addWidget(_wrap(_group(self.minutes, *self.quick, (self.timer_name, 1)), _group(self.start_btn)))
        return page

    def _overlay_box(self) -> QGroupBox:
        box = QGroupBox("게임 위 알람 목록")
        outer = QVBoxLayout(box)
        ov = self._cfg["overlay"]
        self.show_check = checkbox("게임 위에 다가오는 알람 보이기 (최대 3개)")
        self.show_check.setChecked(ov["show"])
        self.show_check.toggled.connect(lambda on: self._save_overlay(show=bool(on)))
        options = QWidget()
        row = QHBoxLayout(options)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(ov["scale"])
        self.scale_spin.valueChanged.connect(self._on_scale)
        row.addWidget(self.scale_spin)
        from .settings_layout import lock_button, opacity_spin
        self.opacity_spin = opacity_spin(ov["opacity"])
        self.opacity_spin.valueChanged.connect(self._on_opacity)
        row.addWidget(self.opacity_spin)
        self.lock_btn = lock_button(ov["locked"])
        self.lock_btn.clicked.connect(self._on_lock)
        row.addWidget(self.lock_btn)
        outer.addWidget(_wrap(self.show_check, options))
        return box

    def _on_mode(self, key: str) -> None:
        self.mode.set_value(key)
        self.pages.setCurrentIndex(0 if key == "time" else 1)

    def _on_repeat(self, _i: int) -> None:
        self.days_row.setVisible(self.repeat.currentData() == "days")

    # ---- 목록 ----
    def _clear_list(self) -> None:
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows = []

    def _rebuild_list(self) -> None:
        self._clear_list()
        now = self._now()
        ordered = sorted(self.clock.alarms, key=lambda a: (a.kind != "time", a.hour * 60 + a.minute if a.kind == "time" else a.due or 0))
        for a in ordered:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            check = checkbox("")
            check.setMinimumWidth(0)
            check.setChecked(a.enabled)
            check.toggled.connect(lambda on, a=a: self._toggle(a, on))
            h.addWidget(check)
            gray = QLabel("")
            gray.setStyleSheet(f"color:{color('muted')};")
            h.addWidget(gray, 1)
            button = QPushButton("취소" if a.kind == "timer" else "삭제")
            button.clicked.connect(lambda _=False, a=a: self._remove(a))
            h.addWidget(button)
            self.list_box.addWidget(row)
            self._rows.append((a, check, gray, button))
        self.empty.setVisible(not ordered)
        self._refresh_rows(now)

    def _refresh_rows(self, now: float) -> None:
        for a, check, gray, _button in self._rows:
            if a.kind == "timer":
                check.setText(f"⏳ {model.remaining_text((a.due or now) - now)} 남음 · {a.label}")
                gray.setText(f"{model.clock_text(a.due or now)}에 울려요")
            else:
                check.setText(f"{a.hour:02d}:{a.minute:02d} · {a.repeat_text()} · {a.label}")
                gray.setText(f"{a.pre}분 전 알림" if a.pre else "미리 알림 없음")
            if check.isChecked() != a.enabled:
                check.blockSignals(True)
                check.setChecked(a.enabled)
                check.blockSignals(False)

    # ---- 바꾸기 ----
    def _save_items(self) -> None:
        try:
            config.save_alarms(items=[a.to_dict() for a in self.clock.alarms])
        except OSError:
            _log.warning("알람 저장 실패", exc_info=True)

    def _add_time(self) -> None:
        t = self.time_edit.time()
        repeat = self.repeat.currentData()
        days = [i for i, cb in enumerate(self.day_checks) if cb.isChecked()]
        alarm = model.new_time_alarm(t.hour(), t.minute(), name=self.time_name.text(), repeat=repeat, days=days,
                                     pre=self.pre.currentData())
        self.clock.alarms.append(alarm)
        self.time_name.clear()
        self._changed()

    def _add_timer(self) -> None:
        self.clock.alarms.append(model.new_timer(self.minutes.value(), self._now(), name=self.timer_name.text()))
        self.timer_name.clear()
        self._changed()

    def _toggle(self, alarm, on: bool) -> None:
        alarm.enabled = bool(on)
        self._changed(rebuild=False)

    def _remove(self, alarm) -> None:
        if alarm in self.clock.alarms:
            self.clock.alarms.remove(alarm)
        self._changed()

    def _changed(self, rebuild: bool = True) -> None:
        self._save_items()
        if rebuild:
            self._rebuild_list()
        self._refresh_status(force=True)
        self._update_overlay(self._now())

    def _on_enable(self, on: bool) -> None:
        try:
            config.save_alarms(enabled=bool(on))
        except OSError:
            _log.warning("알람 사용 저장 실패", exc_info=True)
        self.clock._last = self._now()  # 다시 켜도 꺼 둔 동안 지난 것은 울리지 않음
        self._refresh_status(force=True)
        self._update_overlay(self._now())

    # ---- 0.25초 주기(최적화 화면 타이머에서 부름) ----
    def tick(self) -> None:
        if self._closed:
            return
        now = self._now()
        if self.enable.isChecked():
            fires, changed = self.clock.check(now)
            for fire in fires:
                self._ring(fire)
            if changed:
                self._save_items()
                self._rebuild_list()
        else:
            self.clock._last = now
        self._refresh_status()
        self._update_overlay(now)

    def _ring(self, fire) -> None:
        text = model.notice_text(fire)
        _log.info("[알람] %s: %s", fire.kind, text)
        try:
            self._sound(fire.kind)
        except Exception:  # noqa: BLE001
            _log.debug("알람 소리 실패", exc_info=True)
        hwnd = self._game_hwnd()
        if hwnd:
            from .game_notice import GameNotice, screen_rect_for_hwnd
            self._notices = [n for n in self._notices if n.isVisible()]
            notice = GameNotice(size="large", colors=NOTICE_COLORS, show_ms=NOTICE_MS)
            notice.show_message(text, fire.kind, screen_rect_for_hwnd(hwnd))
            self._notices.append(notice)
        else:
            self._toast("알람" if fire.kind != "timer" else "타이머", text)

    def _refresh_status(self, force: bool = False) -> None:
        now = self._now()
        text = model.status_text(self.clock, now) if self.enable.isChecked() else "꺼짐"
        if text == self._status_cache and not force:
            return
        self._status_cache = text
        on = self.enable.isChecked() and text != "다가오는 알람 없음"
        self.status.setText(("● " if on else "") + text)
        self.status.setStyleSheet(f"color:{color('ok' if on else 'muted')};")
        self._refresh_rows(now)

    # ---- 게임 위 알람 목록 ----
    def _save_overlay(self, **data) -> None:
        self._cfg["overlay"].update(data)
        try:
            config.save_alarms(overlay=data)
        except OSError:
            _log.warning("알람 목록 설정 저장 실패", exc_info=True)
        self._update_overlay(self._now())

    def _on_scale(self, value: int) -> None:
        self._save_overlay(scale=int(value))
        if self._overlay is not None:
            self._overlay.set_scale(value)

    def _on_opacity(self, value: int) -> None:
        self._save_overlay(opacity=int(value))
        if self._overlay is not None:
            self._overlay.set_opacity(value)

    def _on_lock(self) -> None:
        locked = not self._cfg["overlay"]["locked"]
        from .settings_layout import set_lock_text
        set_lock_text(self.lock_btn, locked)
        if self._overlay is not None:
            self._overlay.set_locked(locked)
        self._save_overlay(locked=locked)

    def overlay_lines(self, now: float):
        return [model.list_line(t, a, now) for t, a in self.clock.upcoming(now, 3)]

    def _ensure_overlay(self):
        if self._overlay is None:
            from .alarm_overlay import AlarmListOverlay
            ov = self._cfg["overlay"]
            overlay = AlarmListOverlay(ov["scale"], ov["opacity"])
            overlay.set_locked(ov["locked"])
            if ov["pos"]:
                overlay.move(ov["pos"]["x"], ov["pos"]["y"])
            else:
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    g = screen.geometry()
                    overlay.move(g.x() + 40, g.y() + int(g.height() * 0.25))
            overlay.moved.connect(lambda: self._save_overlay(pos={"x": overlay.x(), "y": overlay.y()}))
            self._overlay = overlay
        return self._overlay

    def _update_overlay(self, now: float) -> None:
        ov = self._cfg["overlay"]
        game = self._watcher is not None and self._safe(self._watcher.is_game_active)
        own = self._watcher is not None and self._safe(self._watcher.is_self_active)
        lines = self.overlay_lines(now) if self.enable.isChecked() else []
        visible = ov["show"] and not self._closed and ((game and bool(lines)) or (own and not ov["locked"]))
        if not visible:
            if self._overlay is not None and self._overlay.isVisible():
                self._overlay.hide()
            return
        overlay = self._ensure_overlay()
        overlay.set_lines(lines)
        if not overlay.isVisible():
            overlay.show()

    @staticmethod
    def _safe(fn) -> bool:
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            return False

    def shutdown(self) -> None:
        self._closed = True
        if self._overlay is not None:
            self._overlay.close()
        for notice in self._notices:
            notice.hide_message()
